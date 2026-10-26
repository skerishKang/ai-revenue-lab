"""Reuse Core parser authorities on CPython; no Worker allocation ceiling."""
from padiem_ai_core.document_normalization import extract_binary_document, normalize_text_document
from padiem_ai_core.pdf_markdown import convert_pdf_to_markdown

MEDIA = {
    "txt": "text/plain", "md": "text/markdown", "csv": "text/csv", "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def parse_text(path, kind):
    # The original name stays in metadata; Core's display-name shortening must
    # not remove a long filename's extension before format validation.
    identity = {"name": "file." + kind, "media_type": MEDIA[kind]}
    if kind == "pdf":
        with path.open("rb") as source:
            return convert_pdf_to_markdown(**identity, payload=source).markdown
    if kind in {"txt", "md", "csv"}:
        return normalize_text_document(**identity, text=path.read_text(encoding="utf-8-sig")).text
    return extract_binary_document(
        **identity, payload=path.read_bytes(), ooxml_member_max_bytes=None,
    ).text
