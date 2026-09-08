"""Document export for quote and order drafts (#2016).

Generates Korean business format files (DOCX) from draft outcomes.
- DOCX: Standard-conforming ECMA-376 / ISO/IEC 29500 WordprocessingML zip package (stdlib only).
- HWPX: Documented decision; fails closed with explicit explanation.
- Legacy HWP: Explicit non-goal; fails closed.
- MD: Preserved default byte-identical behavior.

#2115 adds the web/mobile-safe in-memory artifact handoff built on exactly the
same deterministic renderer: ``build_document_artifact`` returns bounded bytes
plus product-safe metadata, with no filesystem write. Raw document bytes stay
private to the result object; ``public_projection()`` is the JSON-safe
descriptor for later UI/transport consumers. Storage, HTTP routes, R2/DB,
share links, and connector sending are out of scope for this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.sax.saxutils as saxutils
import zipfile

from .p01_adapter import P01AdapterError


SUPPORTED_DOCUMENT_FORMATS = ("md", "docx", "hwpx")
HWPX_EXPORT_DECISION = "DOCUMENTED_DECISION"
LEGACY_HWP_EXPORT_DECISION = "UNSUPPORTED_BINARY_HWP_NON_GOAL"

DOCUMENT_ARTIFACT_KIND = "claw.generated_document"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MD_MEDIA_TYPE = "text/markdown"
DOCUMENT_ARTIFACT_MEDIA_TYPES = {"docx": DOCX_MEDIA_TYPE, "md": MD_MEDIA_TYPE}
# Conservative bound for in-memory handoff artifacts: deterministic business
# documents are a few KB; this only stops pathological inputs from pinning RAM.
MAX_DOCUMENT_ARTIFACT_BYTES = 8 * 1024 * 1024
DOCUMENT_FILENAME_MAX_CHARS = 120
DOCUMENT_DISPLAY_TEXT_MAX_CHARS = 120
_SAFE_FILENAME_FALLBACK_BASE = "document"
_SAFE_FILENAME_KEEP_RE = re.compile(
    r"[^0-9A-Za-z\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3._\-]"
)
_SAFE_FILENAME_COLLAPSE_RE = re.compile(r"[-_.]{2,}")


class DocumentExportError(P01AdapterError):
    """Fail-closed document export error."""


def escape_xml(text: str) -> str:
    """Escapes XML entities safely for OOXML."""
    return saxutils.escape(text, entities={'"': "&quot;", "'": "&apos;"})


def _normalize_export_format(file_format: str) -> str:
    """Fail-closed format gate shared by file export and artifact handoff.

    Returns the normalized exportable format ("md" or "docx"); unsupported
    HWP/HWPX and unknown formats raise exactly the historical error codes and
    messages preserved from #2016.
    """
    normalized_format = file_format.strip().lower()

    if normalized_format == "hwp":
        raise DocumentExportError(
            "document_format_unsupported",
            "legacy HWP binary format is unsupported (non-goal); use docx or md instead",
        )

    if normalized_format == "hwpx":
        raise DocumentExportError(
            "document_format_unsupported",
            "HWPX export is deferred per documented architecture decision; use docx or md instead",
        )

    if normalized_format not in ("md", "docx"):
        raise DocumentExportError(
            "document_format_unsupported",
            f"unsupported document format: {file_format} (allowed: md, docx, hwpx)",
        )
    return normalized_format


def _outcome_docx_bytes(
    *,
    title: str,
    metadata_fields: Sequence[tuple[str, str]],
    section_title: str,
    body_text: str,
    items: Sequence[Sequence[str]],
    total: str,
) -> bytes:
    """The single deterministic DOCX composition for quote/order outcomes."""
    table_headers = ("품명", "수량", "단가", "금액")
    table_rows = list(items)
    table_rows.append(("합계", "", "", total))
    return generate_docx_bytes(
        title=title,
        metadata_fields=metadata_fields,
        section_title=section_title,
        body_text=body_text,
        table_headers=table_headers,
        table_rows=table_rows,
        footer_text="Padiem Claw · Deterministic Flow Calculation Verified",
    )


def safe_document_filename(display_title: str, file_format: str) -> str:
    """Product-safe filename: bounded, path-free, extension-controlled.

    Whitespace and unsafe characters collapse; path separators, traversal,
    control characters, drive letters, and caller-supplied trailing
    extensions cannot survive. Korean (Hangul) titles are preserved.
    """
    normalized_format = _normalize_export_format(file_format)
    base = display_title if isinstance(display_title, str) else ""
    # Strip anything path-like the sanitizer might otherwise keep.
    for separator in ("\\", "/"):
        base = base.replace(separator, " ")
    base = base.replace(":", " ")
    base = _SAFE_FILENAME_KEEP_RE.sub("-", base)
    base = _SAFE_FILENAME_COLLAPSE_RE.sub("-", base).strip("-")
    base = base.strip(".")
    if len(base) > DOCUMENT_FILENAME_MAX_CHARS:
        base = base[:DOCUMENT_FILENAME_MAX_CHARS].rstrip("-.")
    if not base:
        base = _SAFE_FILENAME_FALLBACK_BASE
    return f"{base}.{normalized_format}"


def _build_content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        '</Types>'
    )


def _build_root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        '</Relationships>'
    )


def _build_table_xml(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    xml_parts = [
        '<w:tbl>',
        '  <w:tblPr>',
        '    <w:tblW w:w="5000" w:type="pct"/>',
        '    <w:tblBorders>',
        '      <w:top w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '      <w:left w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '      <w:bottom w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '      <w:right w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '      <w:insideH w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '      <w:insideV w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '    </w:tblBorders>',
        '  </w:tblPr>',
    ]
    # Header row
    xml_parts.append('  <w:tr>')
    for cell in headers:
        esc = escape_xml(str(cell))
        xml_parts.append(
            '    <w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/></w:tcPr>'
            f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{esc}</w:t></w:r></w:p></w:tc>'
        )
    xml_parts.append('  </w:tr>')

    # Data rows
    for row in rows:
        xml_parts.append('  <w:tr>')
        for cell in row:
            esc = escape_xml(str(cell))
            xml_parts.append(f'    <w:tc><w:p><w:r><w:t>{esc}</w:t></w:r></w:p></w:tc>')
        xml_parts.append('  </w:tr>')

    xml_parts.append('</w:tbl>')
    return "".join(xml_parts)


def generate_docx_bytes(
    *,
    title: str,
    metadata_fields: Sequence[tuple[str, str]],
    section_title: str,
    body_text: str,
    table_headers: Sequence[str] | None = None,
    table_rows: Sequence[Sequence[str]] | None = None,
    footer_text: str | None = None,
) -> bytes:
    """Generates valid OOXML DOCX bytes in memory."""
    body_parts = []

    # Title paragraph
    esc_title = escape_xml(title)
    body_parts.append(
        f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>{esc_title}</w:t></w:r></w:p>'
    )
    body_parts.append('<w:p/>')

    # Metadata list/paragraphs
    if metadata_fields:
        for k, v in metadata_fields:
            esc_k = escape_xml(k)
            esc_v = escape_xml(v)
            body_parts.append(
                f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{esc_k}: </w:t></w:r><w:r><w:t>{esc_v}</w:t></w:r></w:p>'
            )
        body_parts.append('<w:p/>')

    # Section title
    esc_sect = escape_xml(section_title)
    body_parts.append(
        f'<w:p><w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr><w:t>{esc_sect}</w:t></w:r></w:p>'
    )
    body_parts.append('<w:p/>')

    # Body paragraphs
    for line in body_text.splitlines():
        trimmed = line.rstrip()
        if not trimmed:
            body_parts.append('<w:p/>')
        else:
            esc_line = escape_xml(trimmed)
            body_parts.append(f'<w:p><w:r><w:t>{esc_line}</w:t></w:r></w:p>')
    body_parts.append('<w:p/>')

    # Table if present
    if table_headers and table_rows is not None:
        body_parts.append(_build_table_xml(table_headers, table_rows))
        body_parts.append('<w:p/>')

    # Footer if present
    if footer_text:
        esc_footer = escape_xml(footer_text)
        body_parts.append(
            f'<w:p><w:r><w:rPr><w:i/><w:color w:val="777777"/></w:rPr><w:t>{esc_footer}</w:t></w:r></w:p>'
        )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>'
        + "".join(body_parts)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        '</w:body>'
        '</w:document>'
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _build_content_types_xml().encode("utf-8"))
        zf.writestr("_rels/.rels", _build_root_rels_xml().encode("utf-8"))
        zf.writestr("word/document.xml", document_xml.encode("utf-8"))

    return buffer.getvalue()


def export_outcome_to_file(
    *,
    out_path: Path,
    file_format: str,
    title: str,
    metadata_fields: Sequence[tuple[str, str]],
    section_title: str,
    body_text: str,
    items: Sequence[Sequence[str]],
    total: str,
    markdown_fallback_text: str,
) -> Path:
    """Exports outcome to out_path according to requested file_format."""
    normalized_format = _normalize_export_format(file_format)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if normalized_format == "md":
        out_path.write_text(markdown_fallback_text, encoding="utf-8")
        return out_path

    out_path.write_bytes(
        _outcome_docx_bytes(
            title=title,
            metadata_fields=metadata_fields,
            section_title=section_title,
            body_text=body_text,
            items=items,
            total=total,
        )
    )
    return out_path


def _bounded_display_text(value: str | None, *, limit: int = DOCUMENT_DISPLAY_TEXT_MAX_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class GeneratedDocumentArtifact:
    """Server-side bounded document result for later web/mobile handoff (#2115).

    ``content`` holds the real document bytes but is excluded from ``repr`` and
    never appears in :meth:`public_projection`. Only the private result object
    carries bytes; public JSON stays metadata-only by default (no base64).
    """

    kind: str
    document_type: str
    filename: str
    format: str
    media_type: str
    byte_length: int
    title: str
    summary: str
    content: bytes = field(repr=False)

    def content_bytes(self) -> bytes:
        """Server-side accessor for the bounded document bytes."""
        return bytes(self.content)

    def public_projection(self) -> dict[str, Any]:
        """JSON-safe descriptor for UI/transport consumers — never raw bytes."""
        return {
            "kind": self.kind,
            "document_type": self.document_type,
            "filename": self.filename,
            "format": self.format,
            "media_type": self.media_type,
            "byte_length": self.byte_length,
            "title": self.title,
            "summary": self.summary,
        }


def build_document_artifact(
    *,
    document_type: str,
    file_format: str,
    title: str,
    metadata_fields: Sequence[tuple[str, str]],
    section_title: str,
    body_text: str,
    items: Sequence[Sequence[str]],
    total: str,
    markdown_fallback_text: str,
    summary: str | None = None,
    max_bytes: int = MAX_DOCUMENT_ARTIFACT_BYTES,
) -> GeneratedDocumentArtifact:
    """Produces the in-memory artifact handoff using the deterministic #2016 renderer.

    DOCX/MD semantics are byte-identical to ``export_outcome_to_file``; HWP,
    HWPX, and unknown formats fail closed with the same errors. No filesystem
    access is performed. The result bytes are size-bound by ``max_bytes``
    (module default: conservative 8 MiB).
    """
    if not isinstance(document_type, str) or not document_type.strip():
        raise DocumentExportError(
            "document_artifact_invalid",
            "document_type must be a non-empty product label (e.g. quote, order)",
        )
    if max_bytes <= 0:
        raise DocumentExportError(
            "document_artifact_invalid",
            "max_bytes must be a positive byte bound",
        )

    normalized_format = _normalize_export_format(file_format)
    if normalized_format == "md":
        content = markdown_fallback_text.encode("utf-8")
    else:
        content = _outcome_docx_bytes(
            title=title,
            metadata_fields=metadata_fields,
            section_title=section_title,
            body_text=body_text,
            items=items,
            total=total,
        )

    if len(content) > max_bytes:
        raise DocumentExportError(
            "document_artifact_too_large",
            f"generated {normalized_format} artifact exceeds the in-memory bound",
        )

    display_title = _bounded_display_text(title)
    display_summary = _bounded_display_text(
        summary if summary is not None else _first_content_line(body_text)
    )
    return GeneratedDocumentArtifact(
        kind=DOCUMENT_ARTIFACT_KIND,
        document_type=document_type.strip(),
        filename=safe_document_filename(title, normalized_format),
        format=normalized_format,
        media_type=DOCUMENT_ARTIFACT_MEDIA_TYPES[normalized_format],
        byte_length=len(content),
        title=display_title,
        summary=display_summary,
        content=content,
    )


def _first_content_line(body_text: str) -> str:
    if not isinstance(body_text, str):
        return ""
    for line in body_text.splitlines():
        if line.strip():
            return line
    return ""


__all__ = [
    "SUPPORTED_DOCUMENT_FORMATS",
    "HWPX_EXPORT_DECISION",
    "LEGACY_HWP_EXPORT_DECISION",
    "DOCUMENT_ARTIFACT_KIND",
    "DOCX_MEDIA_TYPE",
    "MD_MEDIA_TYPE",
    "DOCUMENT_ARTIFACT_MEDIA_TYPES",
    "MAX_DOCUMENT_ARTIFACT_BYTES",
    "DocumentExportError",
    "GeneratedDocumentArtifact",
    "build_document_artifact",
    "safe_document_filename",
    "escape_xml",
    "generate_docx_bytes",
    "export_outcome_to_file",
]
