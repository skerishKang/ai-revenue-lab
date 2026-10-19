"""Server-reviewed bridge from B67 browser PDF extraction to Drive-fresh Core segments (#3357).

The browser is only an extraction worker. It may submit parser facts and page
text, but it cannot submit workspace/binding authority, Drive source identity,
source_ref, a locator, or a freshness verdict. The Engine re-acquires the
authorized PDF, verifies the extraction came from the same bytes, mints
canonical page locators, binds the derived index to a server-owned Drive source
snapshot, and passes every retrieval item through Core's CURRENT freshness
gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from collections.abc import Mapping
from typing import Any

from padiem_ai_core.document_normalization import (
    MAX_PDF_PAGES,
    MAX_PDF_PAGE_TEXT_CHARS,
    normalize_document_text,
)
from padiem_ai_core.document_semantics import (
    DocumentLocator,
    DocumentSegment,
    LocatorKind,
    LocatorPrecision,
)
from padiem_ai_core.drive_capability import DriveFileProjection
from padiem_ai_core.drive_index_freshness import DriveIndexSourceSnapshot
from padiem_ai_core.drive_index_retrieval import (
    DriveIndexedSegment,
    DriveIndexRetrievalError,
    retrieve_current_drive_index_segment,
)
from padiem_ai_core.retrieval import MAX_RETRIEVAL_ITEM_CHARS, RetrievedItem


B67_BROWSER_EXTRACTION_CONTRACT_VERSION = "b67-browser-pdf-extraction.v1"
B67_BROWSER_PARSER = "pdfjs-dist"
B67_BROWSER_PARSER_VERSION = "6.3.289"
B67_BROWSER_MAX_PAGES = 512
B67_BROWSER_MAX_PAGE_CHARS = 40_000
B67_BROWSER_MAX_TOTAL_CHARS = 2_000_000
B67_CANONICAL_MAX_PAGES = MAX_PDF_PAGES
B67_CANONICAL_MAX_PAGE_CHARS = MAX_PDF_PAGE_TEXT_CHARS
B67_LEGAL_RETRIEVAL_NAMESPACE = "project.legal"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXTRACTION_KEYS = frozenset(
    {
        "ok",
        "contract_version",
        "parser",
        "parser_version",
        "source_sha256",
        "page_count",
        "pages",
        "total_text_chars",
        "native_text_state",
        "ocr_candidate_pages",
    }
)
_PAGE_KEYS = frozenset({"page_number", "text", "text_chars", "native_text"})


class BrowserPdfBridgeError(ValueError):
    """Bounded bridge failure safe for first-party transport classification."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code
        super().__init__(safe_message)


@dataclass(frozen=True, slots=True)
class BrowserPdfDriveReview:
    """Canonical server-owned result; source identity remains private."""

    source_snapshot: DriveIndexSourceSnapshot
    segments: tuple[DocumentSegment, ...]
    retrieved_items: tuple[RetrievedItem, ...]
    source_sha256: str
    page_count: int
    blank_page_count: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "contract_version": B67_BROWSER_EXTRACTION_CONTRACT_VERSION,
            "source_freshness": "current",
            "page_count": self.page_count,
            "indexed_page_count": len(self.segments),
            "blank_page_count": self.blank_page_count,
            "segments": [segment.to_public_dict() for segment in self.segments],
            "retrieved_items": [item.to_public_dict() for item in self.retrieved_items],
        }


def _invalid(code: str, message: str, *, status_code: int = 422) -> BrowserPdfBridgeError:
    return BrowserPdfBridgeError(code, message, status_code=status_code)


def _validate_extraction(extraction: object) -> tuple[str, tuple[tuple[int, str], ...], int, int]:
    if not isinstance(extraction, Mapping) or set(extraction) != _EXTRACTION_KEYS:
        raise _invalid("browser_pdf_extraction_invalid", "Browser PDF extraction does not match the reviewed contract.")
    if extraction.get("ok") is not True:
        raise _invalid("browser_pdf_extraction_invalid", "Browser PDF extraction was not successful.")
    if extraction.get("contract_version") != B67_BROWSER_EXTRACTION_CONTRACT_VERSION:
        raise _invalid("browser_pdf_contract_version_mismatch", "Browser PDF extraction contract version is not accepted.")
    if extraction.get("parser") != B67_BROWSER_PARSER or extraction.get("parser_version") != B67_BROWSER_PARSER_VERSION:
        raise _invalid("browser_pdf_parser_version_mismatch", "Browser PDF parser identity does not match the reviewed version.")

    source_sha256 = extraction.get("source_sha256")
    if not isinstance(source_sha256, str) or _SHA256_RE.fullmatch(source_sha256) is None:
        raise _invalid("browser_pdf_source_hash_invalid", "Browser PDF source fingerprint is invalid.")

    page_count = extraction.get("page_count")
    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1:
        raise _invalid("browser_pdf_page_count_invalid", "Browser PDF page count is invalid.")
    if page_count > B67_BROWSER_MAX_PAGES:
        raise _invalid("browser_pdf_page_count_invalid", "Browser PDF page count exceeds the parser contract.")
    if page_count > B67_CANONICAL_MAX_PAGES:
        raise _invalid(
            "browser_pdf_page_bound_exceeds_core",
            "Browser PDF extraction exceeds the current canonical page bound.",
            status_code=413,
        )

    pages = extraction.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        raise _invalid("browser_pdf_page_provenance_invalid", "Browser PDF page provenance is inconsistent.")

    observed: list[tuple[int, str]] = []
    missing_text_pages: list[int] = []
    total_chars = 0
    for index, value in enumerate(pages):
        if not isinstance(value, Mapping) or set(value) != _PAGE_KEYS:
            raise _invalid("browser_pdf_page_invalid", "Browser PDF page does not match the reviewed contract.")
        page_number = value.get("page_number")
        text = value.get("text")
        text_chars = value.get("text_chars")
        native_text = value.get("native_text")
        if page_number != index + 1:
            raise _invalid("browser_pdf_page_provenance_invalid", "Browser PDF page numbers must remain exact and ordered.")
        if not isinstance(text, str) or isinstance(text_chars, bool) or not isinstance(text_chars, int):
            raise _invalid("browser_pdf_page_invalid", "Browser PDF page text is invalid.")
        if text_chars != len(text):
            raise _invalid("browser_pdf_page_invalid", "Browser PDF page character count is inconsistent.")
        if len(text) > B67_BROWSER_MAX_PAGE_CHARS:
            raise _invalid("browser_pdf_page_invalid", "Browser PDF page text exceeds the parser bound.")
        if len(text) > B67_CANONICAL_MAX_PAGE_CHARS:
            raise _invalid(
                "browser_pdf_page_text_exceeds_core",
                "Browser PDF page text exceeds the current canonical page-text bound.",
                status_code=413,
            )
        if not isinstance(native_text, bool) or native_text is not (len(text) > 0):
            raise _invalid("browser_pdf_page_invalid", "Browser PDF native-text marker is inconsistent.")
        total_chars += len(text)
        if total_chars > B67_BROWSER_MAX_TOTAL_CHARS:
            raise _invalid("browser_pdf_total_text_limit", "Browser PDF extraction exceeds the total text bound.")
        if not native_text:
            missing_text_pages.append(page_number)
        observed.append((page_number, text))

    if extraction.get("total_text_chars") != total_chars:
        raise _invalid("browser_pdf_total_text_invalid", "Browser PDF total character count is inconsistent.")
    ocr_pages = extraction.get("ocr_candidate_pages")
    if ocr_pages != missing_text_pages:
        raise _invalid("browser_pdf_ocr_pages_invalid", "Browser PDF OCR-candidate page list is inconsistent.")

    native_pages = page_count - len(missing_text_pages)
    expected_state = "none" if native_pages == 0 else ("all" if not missing_text_pages else "mixed")
    if extraction.get("native_text_state") != expected_state:
        raise _invalid("browser_pdf_native_text_state_invalid", "Browser PDF native-text state is inconsistent.")
    if native_pages == 0:
        raise _invalid("browser_pdf_no_native_text", "Browser PDF contains no usable native text.")

    return source_sha256, tuple(observed), page_count, len(missing_text_pages)


def _segments(pages: tuple[tuple[int, str], ...]) -> tuple[DocumentSegment, ...]:
    segments: list[DocumentSegment] = []
    for page_number, text in pages:
        if not text.strip():
            continue
        normalized = normalize_document_text(text)
        segments.append(
            DocumentSegment(
                text=normalized,
                order=page_number - 1,
                locator=DocumentLocator(
                    kind=LocatorKind.PAGE,
                    value=str(page_number),
                    precision=LocatorPrecision.EXACT,
                ),
            )
        )
    if not segments:
        raise _invalid("browser_pdf_empty_text", "Browser PDF contains no canonical native-text segments.")
    return tuple(segments)


def _retrieval_items(
    *,
    segments: tuple[DocumentSegment, ...],
    source_snapshot: DriveIndexSourceSnapshot,
    current_source: DriveFileProjection,
    source_sha256: str,
) -> tuple[RetrievedItem, ...]:
    items: list[RetrievedItem] = []
    digest_prefix = source_sha256[:16]
    for segment in segments:
        page = segment.locator.value if segment.locator is not None else "unknown"
        for chunk_index, start in enumerate(range(0, len(segment.text), MAX_RETRIEVAL_ITEM_CHARS), start=1):
            chunk = segment.text[start : start + MAX_RETRIEVAL_ITEM_CHARS]
            indexed = DriveIndexedSegment(
                item_id=f"b67_{digest_prefix}_p{page}_c{chunk_index}",
                namespace=B67_LEGAL_RETRIEVAL_NAMESPACE,
                source_snapshot=source_snapshot,
                segment=segment,
            )
            try:
                items.append(
                    retrieve_current_drive_index_segment(
                        indexed,
                        current_source,
                        content=chunk,
                    )
                )
            except DriveIndexRetrievalError as exc:
                status_code = 409 if exc.code == "stale_drive_index" else 422
                raise _invalid(exc.code, exc.safe_message, status_code=status_code) from exc
    return tuple(items)


def review_browser_pdf_extraction(
    *,
    extraction: object,
    current_source: DriveFileProjection,
    current_pdf_bytes: bytes,
) -> BrowserPdfDriveReview:
    """Review one browser extraction against a fresh server-authorized Drive PDF."""

    if not isinstance(current_source, DriveFileProjection):
        raise TypeError("current_source must be a canonical DriveFileProjection")
    if current_source.mime_type != "application/pdf":
        raise _invalid("browser_pdf_source_not_pdf", "Current Drive source is not an eligible PDF.", status_code=415)
    if not isinstance(current_pdf_bytes, bytes) or not current_pdf_bytes.startswith(b"%PDF-"):
        raise _invalid("browser_pdf_source_invalid", "Current Drive PDF bytes are invalid.", status_code=415)
    if current_source.size_bytes is not None and current_source.size_bytes != len(current_pdf_bytes):
        raise _invalid("browser_pdf_source_size_changed", "Current Drive PDF size no longer matches its metadata.", status_code=409)

    source_sha256, pages, page_count, blank_page_count = _validate_extraction(extraction)
    current_sha256 = hashlib.sha256(current_pdf_bytes).hexdigest()
    if not hmac.compare_digest(source_sha256, current_sha256):
        raise _invalid(
            "browser_pdf_source_changed",
            "Drive PDF changed after browser extraction and must be parsed again.",
            status_code=409,
        )

    source_snapshot = DriveIndexSourceSnapshot.from_projection(current_source)
    if not source_snapshot.has_version_evidence:
        raise _invalid(
            "unverifiable_drive_index",
            "Drive source version cannot be verified for canonical retrieval.",
            status_code=422,
        )

    segments = _segments(pages)
    items = _retrieval_items(
        segments=segments,
        source_snapshot=source_snapshot,
        current_source=current_source,
        source_sha256=source_sha256,
    )
    return BrowserPdfDriveReview(
        source_snapshot=source_snapshot,
        segments=segments,
        retrieved_items=items,
        source_sha256=source_sha256,
        page_count=page_count,
        blank_page_count=blank_page_count,
    )


def browser_pdf_drive_bridge_snapshot() -> dict[str, Any]:
    return {
        "contract_version": B67_BROWSER_EXTRACTION_CONTRACT_VERSION,
        "browser_parser": B67_BROWSER_PARSER,
        "browser_parser_version": B67_BROWSER_PARSER_VERSION,
        "browser_parser_max_pages": B67_BROWSER_MAX_PAGES,
        "canonical_max_pages": B67_CANONICAL_MAX_PAGES,
        "browser_parser_max_page_chars": B67_BROWSER_MAX_PAGE_CHARS,
        "canonical_max_page_chars": B67_CANONICAL_MAX_PAGE_CHARS,
        "page_bound_widened": False,
        "silent_truncation": False,
        "browser_drive_authority": False,
        "caller_source_ref_authority": False,
        "caller_locator_authority": False,
        "server_reacquires_current_pdf": True,
        "source_bytes_sha256_bound": True,
        "current_freshness_required": True,
        "second_evidence_authority": False,
        "production_mutation": False,
    }


__all__ = [
    "B67_BROWSER_EXTRACTION_CONTRACT_VERSION",
    "B67_BROWSER_PARSER",
    "B67_BROWSER_PARSER_VERSION",
    "B67_BROWSER_MAX_PAGES",
    "B67_CANONICAL_MAX_PAGES",
    "BrowserPdfBridgeError",
    "BrowserPdfDriveReview",
    "browser_pdf_drive_bridge_snapshot",
    "review_browser_pdf_extraction",
]
