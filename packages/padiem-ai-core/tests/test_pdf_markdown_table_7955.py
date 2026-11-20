"""#7955 ② 글자 PDF의 표가 행·열을 giữ하는지 계산 값으로 확인한다.

현장 증상(2026-11-18): 글자 PDF 1쪽의 표가 행·열로 묶이지 않고 한 줄로 흩어져
나왔다. 재현 결과 두 가지 원인이 있었다.

1. 오른쪽 정렬 셀은 글자 수가 늘수록 시작 x가 왼쪽으로 밀린다. 시작 x만 모아
   열을 세던 방식은 값마다 다른 시작을 각각 다른 열로 읽어 3열 가격표를
   8열(대부분 빈 칸)로 쪼갰다.
2. 헤더 + 한 줄, 곧 2행 표는 최소 행 수 3에 걸려 표로 인정되지 않았다.

여기 PDF는 전부 합성이다(고객 파일 없음). 판정은 원문 문구가 아니라 행 수·
열 수·셀 값으로 한다.
"""

from __future__ import annotations

from io import BytesIO

import pytest

pypdf = pytest.importorskip("pypdf")
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from padiem_ai_core.pdf_markdown import CONVERT_MODE_FAST, convert_pdf_to_markdown

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0
GLYPH_EM = 0.5


def _literal(value: str) -> bytes:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252")


def _pdf(runs: list[tuple[str, float, float, float]]) -> bytes:
    """runs: (text, x, y, size). 크기는 Tm에 실어 실제 글자 높이가 되게 한다."""

    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page = writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    chunks: list[bytes] = []
    for text, x, y, size in runs:
        chunks.append(
            b"BT\n"
            + f"/F1 1 Tf {size:.5f} 0 0 {size:.5f} {x:.5f} {y:.5f} Tm\n".encode("ascii")
            + b"("
            + _literal(text)
            + b") Tj\nET\n"
        )
    content = DecodedStreamObject()
    content.set_data(b"".join(chunks))
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _table_runs(
    rows: list[tuple[str, ...]],
    edges: list[float],
    *,
    align: str = "left",
    size: float = 12.0,
    top: float = 760.0,
    step: float = 18.0,
) -> list[tuple[str, float, float, float]]:
    """열 오른쪽 끝(edges)에 맞춰 셀을 놓는다. 정렬은 셀 시작 x로 표현된다."""

    runs: list[tuple[str, float, float, float]] = []
    for index, cells in enumerate(rows):
        y = top - index * step
        for cell, edge in zip(cells, edges):
            width = len(cell) * size * GLYPH_EM
            if align == "right":
                x = edge - width
            elif align == "center":
                x = edge - width / 2
            else:
                x = edge
            runs.append((cell, x, y, size))
    return runs


def _markdown_table(markdown: str) -> list[list[str]]:
    """변환본에서 Markdown 표를 행렬로 읽는다(구분선은 행으로 세지 않는다)."""

    rows: list[list[str]] = []
    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue
        rows.append(cells)
    return rows


def _convert(runs: list[tuple[str, float, float, float]]) -> str:
    result = convert_pdf_to_markdown(
        name="table.pdf",
        media_type="application/pdf",
        payload=_pdf(runs),
        mode=CONVERT_MODE_FAST,
    )
    return result.markdown


PRICE_ROWS = [
    ("Item", "Qty", "Price"),
    ("Server", "2", "1200"),
    ("License", "10", "350"),
    ("Support", "3", "90"),
]
PRICE_EDGES = [72.0, 260.0, 430.0]


@pytest.mark.parametrize("align", ["left", "right", "center"])
def test_a_price_table_keeps_its_rows_columns_and_cell_values(align: str) -> None:
    rows = _markdown_table(_convert(_table_runs(PRICE_ROWS, PRICE_EDGES, align=align)))

    assert len(rows) == len(PRICE_ROWS)
    assert [len(row) for row in rows] == [len(PRICE_EDGES)] * len(PRICE_ROWS)
    assert rows == [list(row) for row in PRICE_ROWS]


def test_a_header_and_one_entry_is_still_a_table() -> None:
    two = PRICE_ROWS[:2]
    rows = _markdown_table(_convert(_table_runs(two, PRICE_EDGES)))

    assert len(rows) == 2
    assert rows == [list(row) for row in two]


def test_a_four_column_table_with_an_empty_cell_keeps_its_shape() -> None:
    source = [
        ("Item", "Qty", "Price", "Sum"),
        ("Server", "2", "1200", "2400"),
        ("License", "10", "350", ""),
        ("Support", "3", "90", "270"),
    ]
    runs: list[tuple[str, float, float, float]] = []
    for index, cells in enumerate(source):
        y = 760 - index * 18
        for cell, edge in zip(cells, [72.0, 200.0, 300.0, 420.0]):
            if cell:
                runs.append((cell, edge, y, 12.0))
    rows = _markdown_table(_convert(runs))

    assert len(rows) == len(source)
    assert [len(row) for row in rows] == [4] * len(source)
    assert rows[2] == ["License", "10", "350", ""]


def test_a_table_under_a_paragraph_is_still_read_as_a_table() -> None:
    runs: list[tuple[str, float, float, float]] = [
        ("Contract Summary", 72.0, 780.0, 20.0),
        ("Scope", 72.0, 748.0, 14.0),
        ("The vendor delivers the platform in three phases", 72.0, 716.0, 12.0),
        ("with monthly acceptance reviews and a report", 72.0, 702.0, 12.0),
    ]
    runs += _table_runs(PRICE_ROWS, PRICE_EDGES, top=660.0)
    rows = _markdown_table(_convert(runs))

    assert rows == [list(row) for row in PRICE_ROWS]


def test_running_prose_is_not_promoted_to_a_table() -> None:
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
    runs: list[tuple[str, float, float, float]] = []
    for row in range(4):
        x = 72.0
        for word in words:
            runs.append((word + " ", x, 740 - row * 14, 12.0))
            x += (len(word) + 1) * 12.0 * GLYPH_EM

    assert _markdown_table(_convert(runs)) == []


def test_two_lines_of_words_are_not_a_grid() -> None:
    """Each line carrying a different word count is prose, not a table.

    The proposal document this repair was measured on had its paragraphs
    emitted as tables of 38..53 mostly empty columns. Two lines of evenly
    spaced words are the smallest reproduction of that.
    """

    runs: list[tuple[str, float, float, float]] = []
    for row, words in enumerate(
        [
            ["alpha", "bravo", "charlie", "delta", "echo"],
            ["foxtrot", "golf", "hotel", "india", "juliet", "kilo"],
        ]
    ):
        for index, word in enumerate(words):
            runs.append((word, 72.0 + index * 90.0 + row * 30.0, 740 - row * 20, 12.0))

    assert _markdown_table(_convert(runs)) == []


def test_a_single_indented_line_does_not_become_a_column_of_its_own() -> None:
    rows = list(PRICE_ROWS)
    runs = _table_runs(rows, PRICE_EDGES)
    runs.append(("Note", 150.0, 640.0, 12.0))
    table = _markdown_table(_convert(runs))

    assert table == [list(row) for row in rows]