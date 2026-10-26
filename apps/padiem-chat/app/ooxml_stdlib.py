from __future__ import annotations

from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_OOXML_ENTRIES,
    MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES,
    MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES,
    DocumentNormalizationError,
    extract_docx_text as _core_extract_docx_text,
    extract_pptx_text as _core_extract_pptx_text,
    validate_ooxml_archive as _core_validate_ooxml_archive,
)

# Aliases of Core's retired capacity constants (#5734 stage 2). Core no longer
# refuses an archive for its size, member count or uncompressed total, so nothing
# here enforces them; the names stay because the reader's own tests build archives
# at these magnitudes to prove a large package is read rather than rejected.
MAX_ARCHIVE_BYTES = MAX_BINARY_DOCUMENT_BYTES
MAX_ENTRIES = MAX_OOXML_ENTRIES
MAX_ENTRY_UNCOMPRESSED_BYTES = MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES
MAX_TOTAL_UNCOMPRESSED_BYTES = MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES


class OOXMLExtractionError(ValueError):
    pass


_MESSAGES = {
    "ooxml_archive_size": "archive size out of bounds",
    "ooxml_unsafe_path": "unsafe OOXML archive member path",
    "ooxml_encrypted": "encrypted OOXML entries are not supported",
    "ooxml_entry_size": "entry exceeds size limit",
    "ooxml_dtd_rejected": "DTDs are not supported",
    "ooxml_malformed": "malformed OOXML ZIP archive",
    "ooxml_invalid_xml": "invalid OOXML XML part",
    "docx_missing_part": "missing OOXML part",
    "pptx_missing_slides": "missing PPTX slide XML parts",
    "docx_empty": "no readable DOCX text",
    "pptx_empty": "no readable PPTX text",
}


def _translate(exc: DocumentNormalizationError) -> OOXMLExtractionError:
    return OOXMLExtractionError(_MESSAGES.get(exc.code, "OOXML extraction failed safely"))


def validate_ooxml_archive(payload: bytes) -> None:
    try:
        _core_validate_ooxml_archive(payload)
    except DocumentNormalizationError as exc:
        raise _translate(exc) from exc


def extract_docx_text(payload: bytes) -> str:
    try:
        return _core_extract_docx_text(payload)
    except DocumentNormalizationError as exc:
        raise _translate(exc) from exc


def extract_pptx_text(payload: bytes) -> str:
    try:
        return _core_extract_pptx_text(payload)
    except DocumentNormalizationError as exc:
        raise _translate(exc) from exc
