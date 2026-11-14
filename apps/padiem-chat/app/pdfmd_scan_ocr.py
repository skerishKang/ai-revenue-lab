"""Scan-page splitter (S1) and page reader adapter (S2) for PDF to Markdown.

Why this module sits beside the conversion route
------------------------------------------------
``padiem_ai_core.pdf_markdown`` converts a page's native text layer and
deliberately never calls a model. A scanned page has no layer, so the only
honest thing that module can do is report the page as unreadable. Reading that
page needs an authority outside Core: this app's CPython host already carries
the reviewed PDF renderer and the server-to-server caller proof for the B14
lane, so the split and the read live here.

What this module does
---------------------
* S1 ``plan_scan_pages`` decides, per page, whether the canonical Core reader
  found a native text layer. Text pages are left to the existing conversion;
  scan pages are rasterised to one JPEG whose long edge is 1,000 px.
* S2 ``B14PageReader`` sends exactly one page image to the B14 platform lane
  and returns a closed result: ``ok``, ``partial_length`` or ``failed``, with
  the served-model check, token accounting and one retry limited to 502/504
  and transport failures.

What it deliberately does not do
--------------------------------
* It is off unless ``PADIEM_PDFMD_SCAN_OCR_ENABLED`` is ``true``. No route
  calls it yet; when the switch is off nothing in the product changes.
* It never guesses: an unreadable glyph is ``[?]``, a form grid becomes list
  items instead of invented cells, and a page that ran out of output budget is
  reported as partial.
* No model id is written here. The caller passes the grade's model, so a model
  change stays a configuration decision, not a code change.
* The original PDF bytes are only read. The planner returns page images; it
  never rewrites the document.

The page count ceiling is the product decision recorded for this slice: 20
pages by default, 30 as the hard ceiling.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    inspect_pdf,
)

from .b14_service_proof import service_proof_headers

SCAN_OCR_ENABLED_ENV = "PADIEM_PDFMD_SCAN_OCR_ENABLED"

#: A page with this kind is converted by the existing text-layer path.
PAGE_KIND_TEXT = "text"
#: A page with this kind is rasterised and read by the adapter.
PAGE_KIND_SCAN = "scan"

#: Long edge of the one image one page is reduced to.
DEFAULT_PAGE_LONG_EDGE_PX = 1000
MIN_PAGE_LONG_EDGE_PX = 400
MAX_PAGE_LONG_EDGE_PX = 2000
#: Default and hard ceilings for one scan conversion.
DEFAULT_MAX_SCAN_PAGES = 20
HARD_MAX_SCAN_PAGES = 30

#: Output budget: the measurement showed dense prose truncating at 8,192.
DEFAULT_OUTPUT_TOKENS = 16_384
#: Client wait; the next slice may raise the lane's own ceiling instead.
DEFAULT_TIMEOUT_SECONDS = 120.0
#: The lowest thinking setting observed on this lane.
DEFAULT_REASONING_EFFORT = "minimal"
DEFAULT_B14_ORIGIN = "http://127.0.0.1:8789"
B14_CHAT_PATH = "/api/pilot/v1/chat/completions"

READ_STATUS_OK = "ok"
READ_STATUS_PARTIAL_LENGTH = "partial_length"
READ_STATUS_FAILED = "failed"

ERROR_MODEL_MISMATCH = "model_mismatch"
ERROR_TRANSPORT = "transport"
ERROR_PROOF_UNCONFIGURED = "proof_unconfigured"
ERROR_RESPONSE_INVALID = "response_invalid"

#: Only these failures are retried once. A length stop is not a failure of the
#: request; it is the page's own budget, so retrying the identical request
#: would spend the same budget again and return the same partial page.
_RETRYABLE_HTTP_STATUSES = frozenset({502, 504})
_MAX_ATTEMPTS = 2

#: One page, transcribed verbatim. The grid rule is the product decision for
#: this slice: a form cell becomes a list item, never an invented table cell.
SCAN_OCR_PROMPT = (
    "다음 이미지는 스캔한 문서의 한 쪽입니다. 이미지에 실제로 보이는 글자만 그대로 "
    "전사해 Markdown으로 출력하세요.\n"
    "- 제목·소제목은 Markdown 제목(#, ##)으로 표시합니다.\n"
    "- 표처럼 보이는 격자와 서식 칸은 억지로 표를 만들지 말고, 행마다 '- 항목: 값' "
    "목록으로 옮깁니다. 비어 있는 칸을 새로 만들지 않습니다.\n"
    "- 목록은 '- ' 항목으로 표시합니다.\n"
    "- 읽을 수 없는 글자는 [?]로 표시합니다.\n"
    "- 원문에 없는 내용을 추측해 채우거나 요약하지 마세요. 설명 문장이나 코드펜스 "
    "없이 Markdown 본문만 출력하세요."
)


def scan_ocr_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the scan path is switched on.

    Only the exact value ``true`` enables it. An unset, empty, misspelled or
    ``false`` value keeps the existing behaviour, which is the safe direction
    for a path that spends platform credentials.
    """

    source = os.environ if environ is None else environ
    raw = source.get(SCAN_OCR_ENABLED_ENV, "")
    return isinstance(raw, str) and raw.strip().lower() == "true"


@dataclass(frozen=True, slots=True)
class ScanPage:
    """One page's conversion kind, with its image only when it is a scan."""

    number: int
    kind: str
    text_characters: int
    image_jpeg: bytes | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "kind": self.kind,
            "text_characters": self.text_characters,
            "image_bytes": len(self.image_jpeg or b""),
        }


@dataclass(frozen=True, slots=True)
class ScanPlan:
    """The split of one PDF: text pages keep the existing path, scans get images."""

    name: str
    page_count: int
    pages: tuple[ScanPage, ...]
    long_edge_px: int

    @property
    def scan_pages(self) -> tuple[ScanPage, ...]:
        return tuple(page for page in self.pages if page.kind == PAGE_KIND_SCAN)

    @property
    def text_pages(self) -> tuple[ScanPage, ...]:
        return tuple(page for page in self.pages if page.kind == PAGE_KIND_TEXT)


def _bounded_long_edge(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("long_edge_px must be an integer")
    if not MIN_PAGE_LONG_EDGE_PX <= value <= MAX_PAGE_LONG_EDGE_PX:
        raise ValueError("long_edge_px is outside the supported range")
    return value


def _bounded_max_pages(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_pages must be an integer")
    if not 1 <= value <= HARD_MAX_SCAN_PAGES:
        raise ValueError("max_pages must be between 1 and the hard ceiling")
    return value


def _payload_bytes(payload: Any) -> bytes:
    """Accept the same payload shapes the conversion accepts, and nothing new."""

    if isinstance(payload, (bytes, bytearray)):
        source = bytes(payload)
    elif all(callable(getattr(payload, method, None)) for method in ("read", "seek", "tell")):
        payload.seek(0, 2)
        size = payload.tell()
        payload.seek(0)
        source = payload.read(size)
    else:
        raise DocumentNormalizationError(
            "invalid_binary_payload", "PDF payload must be bytes or a seekable file."
        )
    if not source:
        raise DocumentNormalizationError("invalid_binary_payload", "PDF payload is empty.")
    return source


def _render_scan_pages(source: bytes, numbers: list[int], long_edge_px: int) -> dict[int, bytes]:
    """Rasterise exactly the requested pages to JPEG through the app's renderer."""

    try:
        import fitz  # PyMuPDF: the reviewed renderer this host already ships.
    except ModuleNotFoundError as exc:  # pragma: no cover - deployment guarantees it
        raise DocumentNormalizationError(
            "document_dependency_unavailable",
            "PDF rendering dependency is unavailable.",
        ) from exc

    images: dict[int, bytes] = {}
    try:
        document = fitz.open(stream=source, filetype="pdf")
    except Exception as exc:
        raise DocumentNormalizationError(
            "pdf_invalid", "PDF could not be opened for rendering."
        ) from exc
    try:
        for number in numbers:
            page = document[number - 1]
            width = float(page.rect.width) or 1.0
            height = float(page.rect.height) or 1.0
            scale = long_edge_px / max(width, height)
            try:
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB
                )
                image = pixmap.tobytes("jpeg")
            except Exception as exc:
                raise DocumentNormalizationError(
                    "pdf_page_render_failed",
                    "PDF page could not be rendered safely.",
                ) from exc
            if not image.startswith(b"\xff\xd8\xff"):
                raise DocumentNormalizationError(
                    "pdf_page_render_failed",
                    "PDF page could not be rendered safely.",
                )
            images[number] = image
    finally:
        document.close()
    return images


def plan_scan_pages(
    *,
    name: Any,
    media_type: Any,
    payload: Any,
    max_pages: int = DEFAULT_MAX_SCAN_PAGES,
    long_edge_px: int = DEFAULT_PAGE_LONG_EDGE_PX,
    enabled: bool | None = None,
) -> ScanPlan:
    """Split one PDF into text and scan pages, rendering only the scan pages.

    Native-text presence comes from the canonical Core inspection boundary, so
    the decision, the page numbering and the error codes are the ones the
    conversion already uses. Rendering happens here, after that decision.
    """

    if enabled is None:
        enabled = scan_ocr_enabled()
    if not enabled:
        raise DocumentNormalizationError(
            "scan_ocr_disabled",
            "Scan reading is switched off on this deployment.",
        )
    limit = _bounded_max_pages(max_pages)
    edge = _bounded_long_edge(long_edge_px)
    source = _payload_bytes(payload)
    inspection = inspect_pdf(name=name, media_type=media_type, payload=source)
    if inspection.page_count > limit:
        raise DocumentNormalizationError(
            "pdf_scan_page_limit",
            f"This PDF has {inspection.page_count} pages; one scan conversion reads at most {limit}.",
        )
    scan_numbers = [
        page.page_number for page in inspection.pages if not page.text.strip()
    ]
    images = _render_scan_pages(source, scan_numbers, edge) if scan_numbers else {}
    pages = tuple(
        ScanPage(
            number=page.page_number,
            kind=PAGE_KIND_SCAN if not page.text.strip() else PAGE_KIND_TEXT,
            text_characters=len(page.text),
            image_jpeg=images.get(page.page_number),
        )
        for page in inspection.pages
    )
    return ScanPlan(
        name=inspection.name,
        page_count=inspection.page_count,
        pages=pages,
        long_edge_px=edge,
    )


@dataclass(frozen=True, slots=True)
class PageReadResult:
    """One page's closed result. Every field is evidence for the caller."""

    status: str
    markdown: str
    requested_model: str
    served_model: str | None
    model_matches: bool
    attempts: int
    seconds: float
    prompt_tokens: int | None
    reasoning_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
    http_status: int | None
    error_code: str | None

    @property
    def ok(self) -> bool:
        return self.status == READ_STATUS_OK

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "served_model_matches": self.model_matches,
            "attempts": self.attempts,
            "seconds": round(self.seconds, 3),
            "prompt_tokens": self.prompt_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason,
            "http_status": self.http_status,
            "error_code": self.error_code,
            "markdown_characters": len(self.markdown),
        }


def _data_url(image_jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class B14PageReader:
    """Send one page image to the B14 lane and return its closed result."""

    def __init__(
        self,
        *,
        model: str,
        proof_secret: str | None,
        origin: str = DEFAULT_B14_ORIGIN,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
        prompt: str = SCAN_OCR_PROMPT,
        opener: Callable[[urllib.request.Request, float], tuple[int, bytes]] | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model is required")
        if not isinstance(origin, str) or not origin.startswith(("http://", "https://")):
            raise ValueError("origin must be an http(s) URL")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be a number")
        if not 1.0 <= float(timeout_seconds) <= 600.0:
            raise ValueError("timeout_seconds is outside the supported range")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 256:
            raise ValueError("max_tokens is outside the supported range")
        self._model = model.strip()
        self._proof_secret = proof_secret
        self._origin = origin.rstrip("/")
        self._timeout = float(timeout_seconds)
        self._max_tokens = max_tokens
        self._reasoning = reasoning_effort
        self._prompt = prompt
        self._opener = opener or _urlopen
        self._url = self._origin + B14_CHAT_PATH

    def _payload(self, image_jpeg: bytes) -> dict[str, Any]:
        # No deprecated request fields: the lane ignores them, and sending them
        # would advertise a fallback control this adapter does not have.
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._prompt},
                        {"type": "image_url", "image_url": {"url": _data_url(image_jpeg)}},
                    ],
                }
            ],
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        if self._reasoning:
            payload["reasoning_effort"] = self._reasoning
        return payload

    def read_page(self, image_jpeg: bytes) -> PageReadResult:
        """Read one page. Retries face no more than one extra identical attempt."""

        if not image_jpeg.startswith(b"\xff\xd8\xff"):
            return self._failed(ERROR_RESPONSE_INVALID, attempts=0, seconds=0.0)
        raw_body = json.dumps(
            self._payload(image_jpeg), separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        # The proof is body-bound, so it signs the exact bytes sent. An absent or
        # too-short secret yields no header, and the request is never made.
        headers = service_proof_headers(self._proof_secret, raw_body)
        if not headers:
            return self._failed(ERROR_PROOF_UNCONFIGURED, attempts=0, seconds=0.0)
        started = time.monotonic()
        attempts = 0
        http_status: int | None = None
        while attempts < _MAX_ATTEMPTS:
            attempts += 1
            request = urllib.request.Request(
                self._url,
                data=raw_body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **headers,
                },
            )
            try:
                http_status, body = self._opener(request, self._timeout)
            except (OSError, ValueError, http.client.HTTPException):
                if attempts < _MAX_ATTEMPTS:
                    continue
                return self._failed(
                    ERROR_TRANSPORT, attempts=attempts, seconds=time.monotonic() - started
                )
            if http_status in _RETRYABLE_HTTP_STATUSES and attempts < _MAX_ATTEMPTS:
                continue
            return self._result(
                http_status,
                body,
                attempts=attempts,
                seconds=time.monotonic() - started,
            )
        return self._failed(ERROR_TRANSPORT, attempts=attempts, seconds=time.monotonic() - started)

    def _result(
        self,
        http_status: int,
        body: bytes,
        *,
        attempts: int,
        seconds: float,
    ) -> PageReadResult:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._failed(
                f"http_{http_status}" if http_status != 200 else ERROR_RESPONSE_INVALID,
                attempts=attempts,
                seconds=seconds,
                http_status=http_status,
            )
        if not isinstance(data, dict):
            return self._failed(
                ERROR_RESPONSE_INVALID, attempts=attempts, seconds=seconds, http_status=http_status
            )
        error = data.get("error")
        if http_status != 200 or isinstance(error, dict):
            code = None
            if isinstance(error, dict):
                candidate = error.get("code")
                code = candidate if isinstance(candidate, str) and candidate else None
            return self._failed(
                code or f"http_{http_status}",
                attempts=attempts,
                seconds=seconds,
                http_status=http_status,
            )
        choice = (data.get("choices") or [{}])[0]
        if not isinstance(choice, dict):
            return self._failed(
                ERROR_RESPONSE_INVALID, attempts=attempts, seconds=seconds, http_status=http_status
            )
        message = choice.get("message") or {}
        markdown = message.get("content") if isinstance(message, dict) else None
        if not isinstance(markdown, str):
            markdown = ""
        finish = choice.get("finish_reason")
        served = data.get("model") if isinstance(data.get("model"), str) else None
        usage = data.get("usage") or {}
        prompt_tokens = _int_or_none(usage.get("prompt_tokens"))
        completion_tokens = _int_or_none(usage.get("completion_tokens"))
        total_tokens = _int_or_none(usage.get("total_tokens"))
        reasoning_tokens = None
        if None not in (prompt_tokens, completion_tokens, total_tokens):
            reasoning_tokens = max(0, total_tokens - prompt_tokens - completion_tokens)
        matches = served == self._model
        if not matches:
            return PageReadResult(
                status=READ_STATUS_FAILED,
                markdown="",
                requested_model=self._model,
                served_model=served,
                model_matches=False,
                attempts=attempts,
                seconds=seconds,
                prompt_tokens=prompt_tokens,
                reasoning_tokens=reasoning_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish if isinstance(finish, str) else None,
                http_status=http_status,
                error_code=ERROR_MODEL_MISMATCH,
            )
        status = READ_STATUS_PARTIAL_LENGTH if finish == "length" else READ_STATUS_OK
        return PageReadResult(
            status=status,
            markdown=markdown,
            requested_model=self._model,
            served_model=served,
            model_matches=True,
            attempts=attempts,
            seconds=seconds,
            prompt_tokens=prompt_tokens,
            reasoning_tokens=reasoning_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish if isinstance(finish, str) else None,
            http_status=http_status,
            error_code=None,
        )

    def _failed(
        self,
        error_code: str,
        *,
        attempts: int,
        seconds: float,
        http_status: int | None = None,
    ) -> PageReadResult:
        return PageReadResult(
            status=READ_STATUS_FAILED,
            markdown="",
            requested_model=self._model,
            served_model=None,
            model_matches=False,
            attempts=attempts,
            seconds=seconds,
            prompt_tokens=None,
            reasoning_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            finish_reason=None,
            http_status=http_status,
            error_code=error_code,
        )


def _urlopen(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    """Return (status, body) and let an HTTP error carry its own body."""

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(500_000)


__all__ = [
    "DEFAULT_MAX_SCAN_PAGES",
    "DEFAULT_OUTPUT_TOKENS",
    "DEFAULT_PAGE_LONG_EDGE_PX",
    "DEFAULT_TIMEOUT_SECONDS",
    "ERROR_MODEL_MISMATCH",
    "ERROR_PROOF_UNCONFIGURED",
    "ERROR_TRANSPORT",
    "HARD_MAX_SCAN_PAGES",
    "PAGE_KIND_SCAN",
    "PAGE_KIND_TEXT",
    "READ_STATUS_FAILED",
    "READ_STATUS_OK",
    "READ_STATUS_PARTIAL_LENGTH",
    "SCAN_OCR_ENABLED_ENV",
    "SCAN_OCR_PROMPT",
    "B14PageReader",
    "PageReadResult",
    "ScanPage",
    "ScanPlan",
    "plan_scan_pages",
    "scan_ocr_enabled",
]
