"""Document export for quote and order drafts (#2016).

Generates Korean business format files (DOCX) from draft outcomes.
- DOCX: Standard-conforming ECMA-376 / ISO/IEC 29500 WordprocessingML zip package (stdlib only).
- HWPX: Documented decision; fails closed with explicit explanation.
- Legacy HWP: Explicit non-goal; fails closed.
- MD: Preserved default byte-identical behavior.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.sax.saxutils as saxutils
import zipfile

from .p01_adapter import P01AdapterError

SUPPORTED_DOCUMENT_FORMATS = ("md", "docx", "hwpx")
HWPX_EXPORT_DECISION = "DOCUMENTED_DECISION"
LEGACY_HWP_EXPORT_DECISION = "UNSUPPORTED_BINARY_HWP_NON_GOAL"


class DocumentExportError(P01AdapterError):
    """Fail-closed document export error."""


def escape_xml(text: str) -> str:
    """Escapes XML entities safely for OOXML."""
    return saxutils.escape(text, entities={'"': "&quot;", "'": "&apos;"})


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

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if normalized_format == "md":
        out_path.write_text(markdown_fallback_text, encoding="utf-8")
        return out_path

    # Format == docx
    table_headers = ("품명", "수량", "단가", "금액")
    table_rows = list(items)
    table_rows.append(("합계", "", "", total))

    docx_bytes = generate_docx_bytes(
        title=title,
        metadata_fields=metadata_fields,
        section_title=section_title,
        body_text=body_text,
        table_headers=table_headers,
        table_rows=table_rows,
        footer_text="Padiem Claw · Deterministic Flow Calculation Verified",
    )
    out_path.write_bytes(docx_bytes)
    return out_path


__all__ = [
    "SUPPORTED_DOCUMENT_FORMATS",
    "HWPX_EXPORT_DECISION",
    "LEGACY_HWP_EXPORT_DECISION",
    "DocumentExportError",
    "escape_xml",
    "generate_docx_bytes",
    "export_outcome_to_file",
]
