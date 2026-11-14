"""S1/S2 regression for the scan-PDF path (#5568).

The PDF fixtures are built here with the app's reviewed renderer: text pages
carry a real text layer, scan pages carry only an image, and the mixed document
carries both so the split is proven page by page. The B14 lane is a local HTTP
stub, so no model call and no platform credential leaves this process.
"""

from __future__ import annotations

import io
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

fitz = pytest.importorskip("fitz", reason="scan fixtures need the reviewed renderer")
pypdf = pytest.importorskip("pypdf")
from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_markdown import convert_pdf_to_markdown
from PIL import Image

from app.pdfmd_scan_ocr import (
    DEFAULT_MAX_SCAN_PAGES,
    DEFAULT_OUTPUT_TOKENS,
    ERROR_MODEL_MISMATCH,
    ERROR_PROOF_UNCONFIGURED,
    ERROR_TRANSPORT,
    PAGE_KIND_SCAN,
    PAGE_KIND_TEXT,
    READ_STATUS_FAILED,
    READ_STATUS_OK,
    READ_STATUS_PARTIAL_LENGTH,
    B14PageReader,
    plan_scan_pages,
    scan_ocr_enabled,
)

MEDIA = "application/pdf"
NAME = "sample.pdf"
MODEL = "grade/free-test-model"
OTHER_MODEL = "grade/other-test-model"
PROOF_SECRET = "synthetic-proof-secret-" + "x" * 32


def _image_jpeg(text: str = "SCANNED") -> bytes:
    image = Image.new("RGB", (900, 1200), (245, 244, 240))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def _pdf(pages: list[str]) -> bytes:
    """Build one PDF: 'text:<ascii>' inserts a text layer, 'scan:' an image."""

    document = fitz.open()
    try:
        for kind in pages:
            page = document.new_page(width=595, height=842)
            if kind.startswith("text:"):
                page.insert_text((72, 100), kind[5:], fontsize=12)
            else:
                page.insert_image(fitz.Rect(40, 40, 555, 800), stream=_image_jpeg())
        return document.tobytes()
    finally:
        document.close()


def _encrypted_pdf() -> bytes:
    document = fitz.open()
    try:
        document.new_page().insert_text((72, 100), "locked")
        return document.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )
    finally:
        document.close()


CORRUPT = b"%PDF-1.7\nthis is not a page tree\n"


def _error_code(callable_) -> str:
    with pytest.raises(DocumentNormalizationError) as caught:
        callable_()
    return caught.value.code


# ---------------------------------------------------------------- S1 splitter


def test_the_switch_is_off_unless_exactly_true(monkeypatch) -> None:
    monkeypatch.delenv("PADIEM_PDFMD_SCAN_OCR_ENABLED", raising=False)
    assert scan_ocr_enabled() is False
    for value in ("", "false", "0", "yes", "TRUE "):
        expected = value.strip().lower() == "true"
        assert scan_ocr_enabled({"PADIEM_PDFMD_SCAN_OCR_ENABLED": value}) is expected
    assert scan_ocr_enabled({"PADIEM_PDFMD_SCAN_OCR_ENABLED": "true"}) is True


def test_a_disabled_switch_refuses_the_split_without_reading_the_pdf(monkeypatch) -> None:
    monkeypatch.delenv("PADIEM_PDFMD_SCAN_OCR_ENABLED", raising=False)
    assert _error_code(
        lambda: plan_scan_pages(name=NAME, media_type=MEDIA, payload=CORRUPT)
    ) == "scan_ocr_disabled"


def test_a_text_pdf_keeps_every_page_on_the_existing_path() -> None:
    plan = plan_scan_pages(
        name=NAME, media_type=MEDIA, payload=_pdf(["text:article one", "text:article two"]),
        enabled=True,
    )
    assert plan.page_count == 2
    assert [page.kind for page in plan.pages] == [PAGE_KIND_TEXT, PAGE_KIND_TEXT]
    assert all(page.image_jpeg is None for page in plan.pages)
    assert plan.scan_pages == ()


def test_a_scanned_pdf_reports_one_jpeg_per_page_at_the_bounded_long_edge() -> None:
    plan = plan_scan_pages(name=NAME, media_type=MEDIA, payload=_pdf(["scan:", "scan:"]), enabled=True)
    assert [page.kind for page in plan.pages] == [PAGE_KIND_SCAN, PAGE_KIND_SCAN]
    assert [page.number for page in plan.pages] == [1, 2]
    for page in plan.pages:
        assert page.image_jpeg is not None
        assert page.image_jpeg.startswith(b"\xff\xd8\xff")
        with Image.open(io.BytesIO(page.image_jpeg)) as decoded:
            assert max(decoded.size) == 1000


def test_a_mixed_pdf_renders_only_the_scan_page() -> None:
    plan = plan_scan_pages(
        name=NAME, media_type=MEDIA, payload=_pdf(["text:cover letter", "scan:"]), enabled=True
    )
    assert [page.kind for page in plan.pages] == [PAGE_KIND_TEXT, PAGE_KIND_SCAN]
    assert plan.pages[0].image_jpeg is None
    assert plan.pages[1].image_jpeg is not None
    assert plan.pages[0].text_characters > 0


def test_the_page_ceiling_defaults_to_twenty_and_refuses_more() -> None:
    assert DEFAULT_MAX_SCAN_PAGES == 20
    payload = _pdf(["text:page"] * 21)
    assert _error_code(
        lambda: plan_scan_pages(name=NAME, media_type=MEDIA, payload=payload, enabled=True)
    ) == "pdf_scan_page_limit"
    plan = plan_scan_pages(
        name=NAME, media_type=MEDIA, payload=payload, enabled=True, max_pages=21
    )
    assert plan.page_count == 21


def test_the_hard_ceiling_cannot_be_raised_by_a_caller() -> None:
    with pytest.raises(ValueError):
        plan_scan_pages(
            name=NAME, media_type=MEDIA, payload=_pdf(["text:page"]), enabled=True, max_pages=31
        )


def test_corrupt_and_encrypted_documents_keep_the_conversion_error_codes() -> None:
    core_invalid = _error_code(
        lambda: convert_pdf_to_markdown(name=NAME, media_type=MEDIA, payload=CORRUPT)
    )
    scan_invalid = _error_code(
        lambda: plan_scan_pages(name=NAME, media_type=MEDIA, payload=CORRUPT, enabled=True)
    )
    assert core_invalid == scan_invalid

    encrypted = _encrypted_pdf()
    core_encrypted = _error_code(
        lambda: convert_pdf_to_markdown(name=NAME, media_type=MEDIA, payload=encrypted)
    )
    scan_encrypted = _error_code(
        lambda: plan_scan_pages(name=NAME, media_type=MEDIA, payload=encrypted, enabled=True)
    )
    assert core_encrypted == scan_encrypted == "pdf_encrypted"


# ---------------------------------------------------------------- S2 adapter


class _StubB14:
    """A local HTTP lane. It answers queued (status, body) pairs and records requests."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                raw = self.rfile.read(length)
                stub.requests.append(
                    {
                        "path": self.path,
                        "headers": {key.lower(): value for key, value in self.headers.items()},
                        "body": raw,
                    }
                )
                status, payload = stub.responses.pop(0) if stub.responses else (500, {})
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def origin(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def stub():
    server = _StubB14()
    try:
        yield server
    finally:
        server.close()


def _chat_body(*, model: str = MODEL, content: str = "본문", finish: str = "stop") -> dict:
    return {
        "model": model,
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 800, "total_tokens": 5000},
    }


def _reader(stub: _StubB14, **overrides) -> B14PageReader:
    options = {"model": MODEL, "proof_secret": PROOF_SECRET, "origin": stub.origin}
    options.update(overrides)
    return B14PageReader(**options)


def test_a_successful_page_carries_its_tokens_and_the_served_model(stub) -> None:
    stub.responses.append((200, _chat_body()))
    result = _reader(stub).read_page(_image_jpeg())

    assert result.status == READ_STATUS_OK
    assert result.ok is True
    assert result.markdown == "본문"
    assert result.served_model == MODEL
    assert result.model_matches is True
    assert result.attempts == 1
    assert (result.prompt_tokens, result.completion_tokens) == (1200, 800)
    # 5,000 total - 1,200 prompt - 800 answer = the thinking part.
    assert result.reasoning_tokens == 3000
    assert result.error_code is None


def test_the_request_carries_the_proof_and_no_deprecated_fallback_fields(stub) -> None:
    stub.responses.append((200, _chat_body()))
    _reader(stub).read_page(_image_jpeg())

    sent = stub.requests[0]
    assert sent["path"] == "/api/pilot/v1/chat/completions"
    assert len(sent["headers"]["x-padiem-b14-proof"]) == 64
    assert sent["headers"]["x-padiem-b14-time"].isdigit()
    body = json.loads(sent["body"])
    assert "business14" not in body
    assert "allow_external_fallback" not in body
    assert "max_attempts" not in body
    assert body["max_tokens"] == DEFAULT_OUTPUT_TOKENS
    assert body["reasoning_effort"] == "minimal"
    assert body["stream"] is False
    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "text" and "[?]" in parts[0]["text"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_a_length_stop_is_partial_and_is_not_retried(stub) -> None:
    stub.responses.append((200, _chat_body(finish="length")))
    result = _reader(stub).read_page(_image_jpeg())

    assert result.status == READ_STATUS_PARTIAL_LENGTH
    assert result.attempts == 1
    assert len(stub.requests) == 1


def test_a_502_is_retried_once_and_can_succeed(stub) -> None:
    stub.responses.append((502, {"error": {"code": "upstream_unavailable"}}))
    stub.responses.append((200, _chat_body()))
    result = _reader(stub).read_page(_image_jpeg())

    assert result.status == READ_STATUS_OK
    assert result.attempts == 2
    assert len(stub.requests) == 2


def test_two_504s_fail_with_the_status_code(stub) -> None:
    stub.responses.append((504, {"error": {"code": "upstream_timeout"}}))
    stub.responses.append((504, {"error": {"code": "upstream_timeout"}}))
    result = _reader(stub).read_page(_image_jpeg())

    assert result.status == READ_STATUS_FAILED
    assert result.attempts == 2
    assert result.http_status == 504
    assert result.error_code == "upstream_timeout"


def test_a_different_served_model_fails_the_page_without_a_retry(stub) -> None:
    stub.responses.append((200, _chat_body(model=OTHER_MODEL)))
    result = _reader(stub).read_page(_image_jpeg())

    assert result.status == READ_STATUS_FAILED
    assert result.model_matches is False
    assert result.served_model == OTHER_MODEL
    assert result.error_code == ERROR_MODEL_MISMATCH
    assert result.attempts == 1
    assert len(stub.requests) == 1


def test_a_missing_proof_makes_no_request_at_all(stub) -> None:
    reader = _reader(stub, proof_secret=None)
    result = reader.read_page(_image_jpeg())

    assert result.status == READ_STATUS_FAILED
    assert result.error_code == ERROR_PROOF_UNCONFIGURED
    assert result.attempts == 0
    assert stub.requests == []


def test_an_unreachable_lane_is_a_transport_failure_after_one_retry() -> None:
    socket_ = socket.socket()
    socket_.bind(("127.0.0.1", 0))
    port = socket_.getsockname()[1]
    socket_.close()
    reader = B14PageReader(
        model=MODEL, proof_secret=PROOF_SECRET, origin=f"http://127.0.0.1:{port}", timeout_seconds=5
    )
    result = reader.read_page(_image_jpeg())

    assert result.status == READ_STATUS_FAILED
    assert result.error_code == ERROR_TRANSPORT
    assert result.attempts == 2


def test_the_page_count_ceiling_is_the_product_default() -> None:
    assert DEFAULT_MAX_SCAN_PAGES == 20
