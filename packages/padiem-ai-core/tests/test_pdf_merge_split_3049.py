"""#3049 bounded native PDF merge/split Core tests."""

from __future__ import annotations

import sys
from io import BytesIO

import pytest

pytest.importorskip("pypdf")

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_operations import (
    MAX_MERGE_INPUT_FILES,
    MAX_SPLIT_RANGES,
    merge_pdfs,
    split_pdf,
)

pdf_operations = sys.modules["padiem_ai_core.pdf_operations"]


def _pdf(*widths: int) -> bytes:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=200)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=200)
    writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _active_content_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=200)
    page[NameObject("/Annots")] = ArrayObject(
        [
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Annot"),
                    NameObject("/Subtype"): NameObject("/Link"),
                    NameObject("/A"): DictionaryObject(
                        {
                            NameObject("/S"): NameObject("/URI"),
                            NameObject("/URI"): TextStringObject(
                                "https://example.invalid"
                            ),
                        }
                    ),
                }
            )
        ]
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _widths(payload: bytes) -> tuple[float, ...]:
    return tuple(
        float(page.mediabox.width)
        for page in PdfReader(BytesIO(payload), strict=True).pages
    )


def test_merge_preserves_caller_order_and_provenance() -> None:
    result = merge_pdfs((_pdf(101, 102), _pdf(201), _pdf(301, 302)))
    assert result.page_count == 5
    assert _widths(result.payload) == (101, 102, 201, 301, 302)
    assert [item.safe_dict() for item in result.provenance] == [
        {"output_page_number": 1, "source_document_index": 0, "source_page_number": 1},
        {"output_page_number": 2, "source_document_index": 0, "source_page_number": 2},
        {"output_page_number": 3, "source_document_index": 1, "source_page_number": 1},
        {"output_page_number": 4, "source_document_index": 2, "source_page_number": 1},
        {"output_page_number": 5, "source_document_index": 2, "source_page_number": 2},
    ]


def test_split_preserves_requested_one_based_ranges_and_order() -> None:
    result = split_pdf(_pdf(101, 102, 103, 104), ((3, 3), (1, 1), (4, 4)))
    assert _widths(result.payload) == (103, 101, 104)
    assert [item.source_page_number for item in result.provenance] == [3, 1, 4]
    assert result.safe_dict()["user_page_numbering"] == "one_based"


def test_active_content_and_external_links_fail_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as error:
        merge_pdfs((_active_content_pdf(),))
    assert error.value.code == "pdf_active_content"


@pytest.mark.parametrize(
    "payloads,code",
    [
        ((), "pdf_merge_inputs_empty"),
        ((b"not a pdf",), "pdf_magic_mismatch"),
        ((b"%PDF-broken",), "pdf_invalid"),
        ((_encrypted_pdf(),), "pdf_encrypted"),
    ],
)
def test_merge_rejects_invalid_inputs(payloads, code: str) -> None:
    with pytest.raises(DocumentNormalizationError) as error:
        merge_pdfs(payloads)
    assert error.value.code == code


def test_split_rejects_invalid_ranges_and_overlap() -> None:
    payload = _pdf(101, 102, 103)
    for ranges, code in (
        ((), "pdf_split_ranges_empty"),
        (((0, 1),), "pdf_split_range_invalid"),
        (((-1, 1),), "pdf_split_range_invalid"),
        (((2, 1),), "pdf_split_range_invalid"),
        (((1, 4),), "pdf_split_range_page"),
        (((1, 2), (2, 3)), "pdf_split_range_overlap"),
    ):
        with pytest.raises(DocumentNormalizationError) as error:
            split_pdf(payload, ranges)
        assert error.value.code == code


def test_merge_and_split_bounds_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _pdf(101)
    second = _pdf(201)
    monkeypatch.setattr(pdf_operations, "MAX_MERGE_INPUT_FILES", 1)
    with pytest.raises(DocumentNormalizationError) as count:
        merge_pdfs((first, second))
    assert count.value.code == "pdf_merge_input_limit"

    monkeypatch.setattr(pdf_operations, "MAX_SPLIT_RANGES", 1)
    with pytest.raises(DocumentNormalizationError) as ranges:
        split_pdf(_pdf(101, 102, 103), ((1, 1), (2, 2)))
    assert ranges.value.code == "pdf_split_range_limit"

    monkeypatch.setattr(pdf_operations, "MAX_OUTPUT_PAGES", 1)
    with pytest.raises(DocumentNormalizationError) as pages:
        merge_pdfs((_pdf(101, 102),))
    assert pages.value.code == "pdf_output_page_limit"

    monkeypatch.setattr(pdf_operations, "MAX_OUTPUT_BYTES", 1)
    with pytest.raises(DocumentNormalizationError) as output:
        merge_pdfs((first,))
    assert output.value.code == "pdf_output_bytes_limit"


def test_semantic_determinism_does_not_claim_byte_identity() -> None:
    first = merge_pdfs((_pdf(101), _pdf(201)))
    second = merge_pdfs((_pdf(101), _pdf(201)))
    assert first.safe_dict() == second.safe_dict()
    assert first.provenance == second.provenance
    assert first.page_count == second.page_count


def test_input_aggregate_and_selected_page_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = _pdf(101)
    monkeypatch.setattr(pdf_operations, "MAX_INPUT_BYTES_PER_FILE", 1)
    with pytest.raises(DocumentNormalizationError) as per_file:
        merge_pdfs((valid,))
    assert per_file.value.code == "pdf_input_bytes_limit"

    monkeypatch.setattr(pdf_operations, "MAX_INPUT_BYTES_PER_FILE", 2 * 1024 * 1024)
    monkeypatch.setattr(pdf_operations, "MAX_AGGREGATE_INPUT_BYTES", 1)
    with pytest.raises(DocumentNormalizationError) as aggregate:
        merge_pdfs((valid,))
    assert aggregate.value.code == "pdf_merge_aggregate_bytes"

    monkeypatch.setattr(pdf_operations, "MAX_TOTAL_SELECTED_PAGES", 1)
    with pytest.raises(DocumentNormalizationError) as selected:
        split_pdf(_pdf(101, 102), ((1, 2),))
    assert selected.value.code == "pdf_split_selected_limit"


def test_operation_constants_are_bounded() -> None:
    assert MAX_MERGE_INPUT_FILES >= 1
    assert MAX_SPLIT_RANGES >= 1
    assert pdf_operations.MAX_INPUT_BYTES_PER_FILE > 0
    assert pdf_operations.MAX_OUTPUT_BYTES > 0
    assert pdf_operations.USER_PAGE_NUMBERING == "one_based"
