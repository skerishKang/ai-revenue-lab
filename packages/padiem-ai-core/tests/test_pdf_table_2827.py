"""#2827 bounded PDF table extraction tests."""

from __future__ import annotations

from importlib import import_module
from io import BytesIO

import pytest

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("pdfplumber")
pypdf_generic = import_module("pypdf.generic")
PdfWriter = pypdf.PdfWriter
DecodedStreamObject = pypdf_generic.DecodedStreamObject
DictionaryObject = pypdf_generic.DictionaryObject
NameObject = pypdf_generic.NameObject

pdf_table = import_module("padiem_ai_core.pdf_table")
from padiem_ai_core.document_normalization import DocumentNormalizationError


def _add_ruled_table(
    writer: object,
    values: tuple[tuple[str, str], tuple[str, str]],
    *,
    y_offset: int = 0,
) -> None:
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    left = 50
    middle = 150
    right = 250
    bottom = 50 + y_offset
    middle_y = 100 + y_offset
    top = 150 + y_offset
    commands = [
        "1 w",
        f"{left} {bottom} m {right} {bottom} l S",
        f"{left} {middle_y} m {right} {middle_y} l S",
        f"{left} {top} m {right} {top} l S",
        f"{left} {bottom} m {left} {top} l S",
        f"{middle} {bottom} m {middle} {top} l S",
        f"{right} {bottom} m {right} {top} l S",
        (
            f"BT /F1 12 Tf {left + 10} {middle_y + 15} Td ({values[0][0]}) Tj "
            f"{middle - left + 10} 0 Td ({values[0][1]}) Tj ET"
        ),
        (
            f"BT /F1 12 Tf {left + 10} {bottom + 15} Td ({values[1][0]}) Tj "
            f"{middle - left + 10} 0 Td ({values[1][1]}) Tj ET"
        ),
    ]
    content = DecodedStreamObject()
    content.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)


def _ruled_pdf(*tables: tuple[tuple[str, str], tuple[str, str]]) -> bytes:
    writer = PdfWriter()
    for values in tables:
        _add_ruled_table(writer, values)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _text_only_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 50 100 Td (No table) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_ruled_table_has_deterministic_rows_cells_and_page_provenance() -> None:
    payload = _ruled_pdf((("A1", "A2"), ("B1", "B2")))
    first = pdf_table.extract_pdf_tables(name="table.pdf", payload=payload)
    second = pdf_table.extract_pdf_tables(name="table.pdf", payload=payload)

    assert first.safe_dict() == second.safe_dict()
    assert first.status == pdf_table.PDF_TABLE_STATUS_FOUND
    assert first.page_count == 1
    assert first.table_count == 1
    assert first.unsupported_page_numbers == ()
    table = first.tables[0]
    assert table.page_number == 1
    assert table.table_index == 1
    assert table.rows == (("A1", "A2"), ("B1", "B2"))
    assert table.row_count == 2
    assert table.cell_count == 4
    assert len(table.bbox) == 4


def test_multi_page_tables_preserve_one_based_page_order() -> None:
    payload = _ruled_pdf(
        (("P1A", "P1B"), ("P1C", "P1D")),
        (("P2A", "P2B"), ("P2C", "P2D")),
    )
    result = pdf_table.extract_pdf_tables(name="tables.pdf", payload=payload)

    assert result.status == pdf_table.PDF_TABLE_STATUS_FOUND
    assert [table.page_number for table in result.tables] == [1, 2]
    assert result.tables[0].rows[0][0] == "P1A"
    assert result.tables[1].rows[0][0] == "P2A"


def test_borderless_or_ambiguous_layout_fails_closed() -> None:
    unsupported = pdf_table.extract_pdf_tables(
        name="text.pdf", payload=_text_only_pdf()
    )
    assert unsupported.status == pdf_table.PDF_TABLE_STATUS_UNSUPPORTED
    assert unsupported.tables == ()
    assert unsupported.unsupported_page_numbers == (1,)

    class FakeTable:
        bbox = (0, 0, 10, 10)

        def extract(self):
            return [("one",), ("one", "two")]

    class FakePage:
        def find_tables(self, *, table_settings):
            return [FakeTable()]

    with pytest.raises(DocumentNormalizationError) as error:
        pdf_table._extract_page_tables(
            FakePage(),
            1,
            table_count=0,
            parse_errors=(ValueError, TypeError, RuntimeError, KeyError, IndexError),
        )
    assert error.value.code == "pdf_table_ambiguous"


def test_table_bounds_and_invalid_reader_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _ruled_pdf((("A", "B"), ("C", "D")))
    with monkeypatch.context() as context:
        context.setattr(pdf_table, "MAX_PDF_TABLE_CELL_CHARS", 0)
        with pytest.raises(DocumentNormalizationError) as error:
            pdf_table.extract_pdf_tables(name="table.pdf", payload=payload)
        assert error.value.code == "pdf_table_cell_limit"

    with pytest.raises(DocumentNormalizationError) as invalid:
        pdf_table.extract_pdf_tables(name="bad.pdf", payload=b"not a pdf")
    assert invalid.value.code.startswith("pdf_table_")

    encrypted_writer = PdfWriter()
    encrypted_writer.add_blank_page(width=100, height=100)
    encrypted_writer.encrypt("secret")
    encrypted_output = BytesIO()
    encrypted_writer.write(encrypted_output)
    with pytest.raises(DocumentNormalizationError) as encrypted:
        pdf_table.extract_pdf_tables(
            name="locked.pdf", payload=encrypted_output.getvalue()
        )
    assert encrypted.value.code.startswith("pdf_table_")

    with pytest.raises(DocumentNormalizationError) as oversized:
        pdf_table.extract_pdf_tables(
            name="large.pdf",
            payload=b"%PDF-1.7\n" + b"0" * pdf_table.MAX_PDF_TABLE_SOURCE_BYTES,
        )
    assert oversized.value.code == "pdf_table_payload_limit"


def test_public_table_projection_has_no_pdf_bytes() -> None:
    result = pdf_table.extract_pdf_tables(
        name="table.pdf", payload=_ruled_pdf((("A", "B"), ("C", "D")))
    )
    public = result.safe_dict()

    assert "data" not in public
    assert "payload" not in public
    assert public["tables"][0]["rows"] == [["A", "B"], ["C", "D"]]
