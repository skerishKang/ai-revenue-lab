"""#2013: shared binary-document intake for the review and draft flows.

Routes PDF/DOCX/HWPX files through the existing Core document normalization
(``padiem_ai_core.document_normalization.extract_binary_document``) when the
file magic and extension agree, so both flows receive extracted text through
the same per-chunk pipeline with unchanged limits and pacing. HWPX read
support landed in #2012; legacy ``.hwp`` stays unsupported by decision (OLE2
compound binary) and yields a deterministic note. A Core rejection
(encrypted, corrupt, over-limit, dependency-unavailable, no extractable text /
OCR disabled) yields a note carrying the Core reason code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError,
    extract_binary_document,
)

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
HWPX_MEDIA_TYPE = "application/hwp+zip"

LEGACY_HWP_NOTE = "legacy HWP 미지원(OLE2 바이너리, #2012 결정)"

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK"
_DOCX_SIGNATURE = b"word/document.xml"
_HWPX_SIGNATURE = b"Contents/section"

_MEDIA_BY_SUFFIX = {
    ".pdf": PDF_MEDIA_TYPE,
    ".docx": DOCX_MEDIA_TYPE,
    ".hwpx": HWPX_MEDIA_TYPE,
}

_LEGACY_HWP_SUFFIXES = frozenset({".hwp"})


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """Outcome of a document intake attempt.

    ``text`` is set on a successful binary-document extraction; ``note`` is set
    when the file must be skipped (legacy ``.hwp``, or Core rejection). When both
    are ``None`` the file is not a routed document and the caller falls back to
    the existing UTF-8 text path.
    """

    text: str | None = None
    note: str | None = None


def _magic_matches(media_type: str, data: bytes) -> bool:
    if media_type == PDF_MEDIA_TYPE:
        return data.startswith(_PDF_MAGIC)
    if media_type == DOCX_MEDIA_TYPE:
        return data.startswith(_ZIP_MAGIC) and _DOCX_SIGNATURE in data
    if media_type == HWPX_MEDIA_TYPE:
        return data.startswith(_ZIP_MAGIC) and _HWPX_SIGNATURE in data
    return False


def _rejection_note(exc: DocumentNormalizationError) -> str:
    code = exc.code
    if code == "pdf_empty_text":
        return f"PDF 텍스트 추출 불가(OCR 미지원) — {code}"
    if code == "document_dependency_unavailable":
        return f"문서 추출 의존성 미설치 — {code}"
    return f"문서 변환 실패 — {code}"


def intake_document(name: str, data: bytes) -> IntakeResult | None:
    """Route a supported binary document through Core normalization.

    Returns an ``IntakeResult`` for PDF/DOCX/HWPX inputs (extracted text or a
    skip note) and for legacy ``.hwp`` inputs (unsupported note), or ``None``
    when the file is not a supported binary document and the caller should
    carry on with the existing text path.
    """
    suffix = Path(name).suffix.lower()
    if suffix in _LEGACY_HWP_SUFFIXES:
        return IntakeResult(note=LEGACY_HWP_NOTE)
    media_type = _MEDIA_BY_SUFFIX.get(suffix)
    if media_type is None:
        return None
    if not _magic_matches(media_type, data):
        return None
    try:
        document = extract_binary_document(
            name=name, media_type=media_type, payload=data
        )
    except DocumentNormalizationError as exc:
        return IntakeResult(note=_rejection_note(exc))
    return IntakeResult(text=document.text)


__all__ = [
    "LEGACY_HWP_NOTE",
    "IntakeResult",
    "intake_document",
]