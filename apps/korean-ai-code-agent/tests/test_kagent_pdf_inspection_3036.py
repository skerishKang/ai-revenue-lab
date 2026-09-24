"""#3036 KAgent PDF inspection composition tests."""

from __future__ import annotations

from io import BytesIO
from unittest import mock

import pytest

try:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except ModuleNotFoundError:  # pragma: no cover
    PdfWriter = None
    DecodedStreamObject = DictionaryObject = NameObject = None

from kagent.file_intake_safety import DetectedFormat
from kagent.pdf_inspection import inspect_pdf_document


def _pdf(text: str = "native page text") -> bytes:
    if PdfWriter is None:
        pytest.skip("pypdf is provided by the documents extra")
    writer = PdfWriter()
    page = writer.add_blank_page(width=320, height=180)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
    })
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 14 Tf 36 90 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_inspection_reuses_gate_before_core_reader() -> None:
    calls: list[str] = []
    import kagent.pdf_inspection as module
    real_gate = module.inspect_file
    real_core = module.inspect_pdf

    def gate(name, data):
        calls.append("gate")
        return real_gate(name, data)

    def core(**kwargs):
        calls.append("core")
        return real_core(**kwargs)

    with mock.patch.object(module, "inspect_file", gate), mock.patch.object(module, "inspect_pdf", core):
        result = inspect_pdf_document("report.pdf", _pdf())
    assert calls == ["gate", "core"]
    assert result.safe_to_read
    assert result.inspection.pages[0].page_number == 1
    assert result.gate.detected_format is DetectedFormat.PDF


def test_denied_pdf_never_reaches_core_reader() -> None:
    import kagent.pdf_inspection as module
    with mock.patch.object(module, "inspect_pdf") as reader:
        result = inspect_pdf_document("spoofed.pdf", b"\x89PNG\r\n\x1a\n")
    assert not result.safe_to_read
    assert result.inspection is None
    reader.assert_not_called()
