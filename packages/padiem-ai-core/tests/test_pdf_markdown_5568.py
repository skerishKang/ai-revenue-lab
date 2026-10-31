"""Focused regression for the #5568 PDF to Markdown conversion engine.

PDFs here are authored with the repository's own locked pypdf writer and a raw
content stream, the convention already used by
``apps/padiem-chat/tests/test_binary_document_attachments.py``; ReportLab is an
optional extra and stays out of this path. Each text run is placed at an exact
baseline and rotation, because that is the only way to prove the layout
reconstruction rather than describe it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf")
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

import padiem_ai_core.pdf_markdown as pdf_markdown
from padiem_ai_core.document_normalization import (
    MAX_PDF_PAGES as _CORE_MAX_PDF_PAGES,
    MAX_PDF_PAGE_TEXT_CHARS as _CORE_MAX_PDF_PAGE_TEXT_CHARS,
)
from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_markdown import (
    CONVERT_MODE_FAST,
    CONVERT_MODE_PRECISE,
    CONVERT_MODE_VERIFY,
    PRECISE_MODE_UNAVAILABLE,
    ConversionNotices,
    _digit_preservation,
    _layer_mismatches,
    convert_pdf_to_markdown,
)

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
ENGINE_SOURCE = Path(pdf_markdown.__file__).read_text(encoding="utf-8")


@dataclass(frozen=True)
class TextOp:
    """One text-showing operator at an exact baseline."""

    text: str
    x: float
    y: float
    size: float = 11.0
    rotate: float = 0.0


def _literal(value: str) -> bytes:
    cleaned = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return cleaned.encode("cp1252", errors="replace")


def _number(value: float) -> str:
    return f"{value + 0.0:.5f}"


def _stream(ops: list[TextOp]) -> bytes:
    chunks: list[bytes] = []
    for op in ops:
        radians = math.radians(op.rotate)
        cosine, sine = math.cos(radians), math.sin(radians)
        matrix = (
            op.size * cosine,
            op.size * sine,
            -op.size * sine,
            op.size * cosine,
            op.x,
            op.y,
        )
        chunks.append(
            b"BT\n"
            + (" ".join(_number(value) for value in matrix) + " Tm\n").encode("ascii")
            + b"/F1 1 Tf\n("
            + _literal(op.text)
            + b") Tj\nET\n"
        )
    return b"".join(chunks)


def build_pdf(pages: list[list[TextOp]], *, rotate_entry: int | None = None) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for ops in pages:
        page = writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        if ops:
            content = DecodedStreamObject()
            content.set_data(_stream(ops))
            page[NameObject("/Contents")] = writer._add_object(content)
        if rotate_entry is not None:
            page[NameObject("/Rotate")] = NumberObject(rotate_entry)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def blank_pdf(count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def convert(pdf: bytes, *, mode: str = CONVERT_MODE_FAST):
    return convert_pdf_to_markdown(
        name="document.pdf", media_type="application/pdf", payload=pdf, mode=mode
    )


_PROSE = [
    TextOp("Contract Summary", 72, 780, size=20),
    TextOp("Scope", 72, 748, size=14),
    TextOp("The vendor delivers the platform in three", 72, 716),
    TextOp("phases with monthly acceptance reviews", 72, 702),
    TextOp("and a final handover report", 72, 688),
    TextOp("Payment is due within thirty days", 72, 640),
    TextOp("of each acceptance notice", 72, 626),
]

_TABLE_ROWS = [
    ("Item", "Qty", "Price"),
    ("Server", "2", "1200"),
    ("License", "10", "350"),
    ("Support", "3", "90"),
]


def _table_ops() -> list[TextOp]:
    ops: list[TextOp] = [TextOp("Pricing", 72, 800, size=14)]
    for index, cells in enumerate(_TABLE_ROWS):
        y = 760 - index * 18
        ops.append(TextOp(cells[0], 72, y))
        ops.append(TextOp(cells[1], 260, y))
        ops.append(TextOp(cells[2], 430, y))
    return ops


def prose_pdf() -> bytes:
    return build_pdf([_PROSE, []])


# ---------------------------------------------------------------------------
# Layout reconstruction
# ---------------------------------------------------------------------------


def test_headings_and_paragraph_carryover_come_from_the_layout() -> None:
    result = convert(build_pdf([_PROSE]))
    lines = [line for line in result.markdown.splitlines() if line.strip()]

    assert lines[0] == "<!-- padiem:page 1 -->"
    assert lines[1] == "# Contract Summary"
    assert lines[2] == "## Scope"
    # Three short lines under one heading are one wrapped sentence, so they are
    # one paragraph; the wide gap above "Payment" is the page's own break signal.
    assert lines[3] == (
        "The vendor delivers the platform in three phases with monthly "
        "acceptance reviews and a final handover report"
    )
    assert lines[4] == "Payment is due within thirty days of each acceptance notice"
    assert result.page_count == 1
    assert result.mode == CONVERT_MODE_FAST
    assert result.warnings == ()


def test_column_aligned_rows_become_a_github_markdown_table() -> None:
    result = convert(build_pdf([_table_ops()]))

    assert "## Pricing" in result.markdown
    assert "| Item | Qty | Price |" in result.markdown
    assert "| --- | --- | --- |" in result.markdown
    assert "| Server | 2 | 1200 |" in result.markdown
    assert "| Support | 3 | 90 |" in result.markdown


def test_reflowed_prose_chunks_are_not_promoted_to_a_table() -> None:
    # One sentence emitted as adjacent text-showing operators: the classic way a
    # naive column detector turns a paragraph into a table.
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    ops: list[TextOp] = []
    for row in range(4):
        x = 72.0
        for word in words:
            ops.append(TextOp(f"{word} ", x, 740 - row * 14))
            x += (len(word) + 1) * 5.5
    result = convert(build_pdf([ops]))

    assert "|" not in result.markdown
    assert "alpha bravo charlie delta echo foxtrot" in result.markdown


def test_list_markers_become_markdown_lists() -> None:
    ops = [
        TextOp("Deliverables", 72, 780, size=14),
        TextOp("* Source documents", 72, 750),
        TextOp("* Handover report", 72, 736),
        TextOp("1. First phase", 72, 710),
        TextOp("2. Second phase", 72, 696),
    ]
    result = convert(build_pdf([ops]))

    assert "- Source documents" in result.markdown
    assert "- Handover report" in result.markdown
    assert "1. First phase" in result.markdown
    assert "2. Second phase" in result.markdown


# ---------------------------------------------------------------------------
# Page provenance
# ---------------------------------------------------------------------------


def test_page_anchors_and_line_ranges_address_the_same_page() -> None:
    result = convert(prose_pdf())
    lines = result.markdown.splitlines()

    assert len(result.pages) == 2
    first, second = result.pages
    assert (first.number, first.start_line) == (1, 1)
    assert lines[first.start_line - 1] == "<!-- padiem:page 1 -->"
    assert lines[first.end_line - 1] == "Payment is due within thirty days of each acceptance notice"
    assert lines[second.start_line - 1] == "<!-- padiem:page 2 -->"
    assert first.native_text_present is True
    assert first.character_count > 0
    assert second.native_text_present is False
    assert second.character_count == 0


def test_conversion_is_deterministic_for_the_same_input() -> None:
    pdf = build_pdf([_table_ops()])
    once = convert(pdf)
    twice = convert(pdf)

    assert once.markdown == twice.markdown
    assert hashlib.sha256(once.markdown.encode("utf-8")).digest() == hashlib.sha256(
        twice.markdown.encode("utf-8")
    ).digest()
    assert once.public_dict() == twice.public_dict()


# ---------------------------------------------------------------------------
# Honest refusal and failure states
# ---------------------------------------------------------------------------


def test_a_page_without_a_text_layer_is_marked_not_guessed() -> None:
    result = convert(prose_pdf())
    notice = ConversionNotices().unreadable_page

    assert f"> {notice}" in result.markdown
    assert result.warnings == ("unreadable_page:2",)
    assert result.pages[1].native_text_present is False
    after_anchor = result.markdown.split("<!-- padiem:page 2 -->")[1]
    assert "Contract Summary" not in after_anchor
    assert notice in after_anchor


def test_rotated_content_is_reported_without_trusting_the_rotate_entry() -> None:
    ops = [
        TextOp("Turned heading text", 120, 700, size=16, rotate=90),
        TextOp("Turned body line one", 120, 660, rotate=90),
        TextOp("Turned body line two", 120, 620, rotate=90),
    ]
    result = convert(build_pdf([ops], rotate_entry=0))

    assert result.pages[0].rotated_text is True
    assert "rotated_text_layer:1" in result.warnings


def test_upright_content_is_not_claimed_to_be_rotated() -> None:
    result = convert(build_pdf([_PROSE]))

    assert result.pages[0].rotated_text is False
    assert result.warnings == ()


def test_precise_mode_is_refused_with_a_bounded_reason() -> None:
    with pytest.raises(DocumentNormalizationError) as refused:
        convert(prose_pdf(), mode=CONVERT_MODE_PRECISE)

    assert refused.value.code == PRECISE_MODE_UNAVAILABLE
    assert "OCR" in refused.value.safe_message


def test_unsupported_input_fails_closed_with_a_specific_code() -> None:
    with pytest.raises(DocumentNormalizationError) as empty:
        convert(b"")
    assert empty.value.code == "invalid_binary_payload"

    with pytest.raises(DocumentNormalizationError) as wrong_bytes:
        convert(b"not a pdf at all")
    assert wrong_bytes.value.code == "pdf_magic_mismatch"

    encrypted = PdfWriter()
    encrypted.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    encrypted.encrypt("secret")
    buffer = BytesIO()
    encrypted.write(buffer)
    with pytest.raises(DocumentNormalizationError) as locked:
        convert(buffer.getvalue())
    assert locked.value.code == "pdf_encrypted"

    with pytest.raises(DocumentNormalizationError) as unknown_mode:
        convert_pdf_to_markdown(
            name="document.pdf",
            media_type="application/pdf",
            payload=prose_pdf(),
            mode="ultra",
        )
    assert unknown_mode.value.code == "invalid_convert_mode"

    with pytest.raises(DocumentNormalizationError) as not_pdf_media:
        convert_pdf_to_markdown(
            name="document.pdf", media_type="text/plain", payload=prose_pdf()
        )
    assert not_pdf_media.value.code == "unsupported_binary_media_type"

    with pytest.raises(DocumentNormalizationError) as mismatched:
        convert_pdf_to_markdown(
            name="document.txt", media_type="application/pdf", payload=prose_pdf()
        )
    assert mismatched.value.code == "media_extension_mismatch"


# ---------------------------------------------------------------------------
# Verification mode: agreement against the text layer, never accuracy
# ---------------------------------------------------------------------------


def test_verify_mode_reports_one_agreement_row_per_page() -> None:
    result = convert(prose_pdf(), mode=CONVERT_MODE_VERIFY)

    assert [row.page for row in result.agreement] == [1, 2]
    assert [row.rotated_text for row in result.agreement] == [False, False]
    assert result.agreement[0].character_coverage == 1.0
    assert result.agreement[0].digit_preservation is None
    assert result.agreement[0].reading_order == 1.0
    # The empty page says why its own numbers mean nothing.
    assert {(row.page, row.kind) for row in result.mismatches} == {
        (2, "no_source_layer")
    }


def test_fast_mode_carries_no_agreement_report() -> None:
    result = convert(prose_pdf())

    assert result.agreement == ()
    assert result.mismatches == ()


def test_digit_fragmentation_and_separator_ambiguity_are_flagged_on_their_page() -> None:
    ops = [
        TextOp("Invoice 1 234 for platform services", 72, 740),
        TextOp("Total 1.234 units shipped", 72, 716),
    ]
    result = convert(build_pdf([ops]), mode=CONVERT_MODE_VERIFY)
    kinds = {(row.page, row.kind) for row in result.mismatches}

    assert kinds == {
        (1, "digit_fragmentation"),
        (1, "separator_ambiguity"),
    }
    # Fragmented is not lost: the tokens survive verbatim into the result.
    assert result.agreement[0].digit_preservation == 1.0
    assert "Invoice 1 234 for platform services" in result.markdown


def test_a_table_row_of_two_digit_columns_is_not_called_a_split_number() -> None:
    # "Server 2 1200" reads as one broken number in the raw layer. It is two
    # cells, so the fragmentation detector must stay silent about it.
    result = convert(build_pdf([_table_ops()]), mode=CONVERT_MODE_VERIFY)

    assert result.mismatches == ()
    assert "| Server | 2 | 1200 |" in result.markdown


def test_agreement_drops_the_syntax_this_module_adds_and_keeps_the_text() -> None:
    ops = [
        TextOp("Summary", 72, 780, size=20),
        TextOp("Delivered on 2026-10-23 for 45 units", 72, 740),
    ]
    result = convert(build_pdf([ops]), mode=CONVERT_MODE_VERIFY)

    assert result.agreement[0].character_coverage == 1.0
    assert result.agreement[0].reading_order == 1.0
    assert result.agreement[0].digit_preservation == 1.0


def test_a_number_lost_between_layer_and_result_breaks_preservation() -> None:
    source = "Total 1200 units and 350 extras"

    assert _digit_preservation(source, source) == 1.0
    assert _digit_preservation(source, "Total units and extras") == 0.0
    assert _digit_preservation("no digits here", "none") is None


def test_syllable_spacing_loss_is_detected_on_the_page_that_carries_it() -> None:
    source = "계약 기간 12 개월 이며 대금 지급은 30 일 이내"
    glued = source.replace(" ", "")

    assert {row.kind for row in _layer_mismatches(1, glued, glued, False)} == set()
    flagged = _layer_mismatches(1, source, glued, False)
    assert "syllable_spacing_loss" in {row.kind for row in flagged}


def test_agreement_numbers_are_never_labelled_accuracy() -> None:
    public = convert(prose_pdf(), mode=CONVERT_MODE_VERIFY).public_dict()

    assert "accuracy" not in json.dumps(public)
    assert "never presented as accuracy" in ENGINE_SOURCE


# ---------------------------------------------------------------------------
# Reuse, never reinvent (owner: no invented token/page/file ceilings)
# ---------------------------------------------------------------------------


def test_conversion_reuses_core_bounds_and_invents_no_ceiling() -> None:
    assert re.findall(r"^MAX_[A-Z0-9_]+ = ", ENGINE_SOURCE, re.MULTILINE) == []
    assert pdf_markdown.MAX_PDF_PAGES is _CORE_MAX_PDF_PAGES
    assert (
        pdf_markdown.MAX_PDF_PAGE_TEXT_CHARS
        is _CORE_MAX_PDF_PAGE_TEXT_CHARS
    )
    # #5734 stage 2: the shared numbers remain shared, and neither one refuses
    # a document any more. Length past the old ceiling converts like any other.
    convert(blank_pdf(_CORE_MAX_PDF_PAGES + 1))


def test_conversion_opens_only_the_canonical_reader_and_calls_no_provider() -> None:
    code = re.sub(r'""".*?"""', "", ENGINE_SOURCE, flags=re.DOTALL)

    assert "PdfReader" not in code
    assert "pypdf" not in code
    assert "_open_pdf_reader(source)" in code
    for forbidden in ("httpx", "requests", "openai", "subprocess", "multiprocessing", "pdfplumber", "pdfium"):
        assert forbidden not in code.lower()
