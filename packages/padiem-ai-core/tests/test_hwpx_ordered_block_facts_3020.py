from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from padiem_ai_core.document_normalization import (
    _local_name,
    _ordered_section_block_facts,
    _parse_xml,
    extract_hwpx_text,
    parse_hwpx_sections,
)

_NS = 'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
_DECL = '<?xml version="1.0" encoding="UTF-8"?>'


def _section(body: str) -> bytes:
    return f"{_DECL}<hs:sec {_NS}>{body}</hs:sec>".encode()


def _para(text: str | None = None, *, runs: int = 1, empty: bool = False) -> str:
    value = "" if empty or text is None else text
    tags = "".join(f"<hp:runs><hp:t>{value}</hp:t></hp:runs>" for _ in range(runs))
    return f"<hp:p>{tags}</hp:p>"


def _table(*rows: str) -> str:
    return f"<hp:tbl>{''.join(f'<hp:tr>{row}</hp:tr>' for row in rows)}</hp:tbl>"


def _cell(body: str = "", *, attrs: str = "") -> str:
    return f"<hp:tc{attrs}>{body}</hp:tc>"


def _archive(body: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("Contents/section1.xml", _section(body))
    return buffer.getvalue()


def _facts(body: str):
    root = _parse_xml(_section(body))
    return _ordered_section_block_facts(index=1, root=root, part=_section(body))


def test_legacy_flat_projection_is_frozen_for_paragraph_table_paragraph() -> None:
    body = _para("before") + _table(_cell(_para("cell-a")) + _cell(_para("cell-b"))) + _para("after")
    payload = _archive(body)
    assert extract_hwpx_text(payload) == "before\ncell-a\ncell-b\nafter"
    assert [p.text for p in parse_hwpx_sections(payload)[0].paragraphs] == [
        "before", "cell-a", "cell-b", "after"
    ]


def test_ordered_section_facts_preserve_direct_block_order() -> None:
    facts = _facts(_para("before") + _table(_cell(_para("cell"))) + _para("after"))
    assert [block.kind for block in facts.blocks] == ["paragraph", "table", "paragraph"]
    assert [block.paragraph.text for block in facts.blocks if block.paragraph] == ["before", "after"]


def test_table_facts_preserve_row_and_cell_order() -> None:
    body = _table(_cell(_para("a")) + _cell(_para("b")), _cell(_para("c")) + _cell(_para("d")))
    table = _facts(body).blocks[0].table
    assert table is not None
    assert [[cell.paragraphs[0].text for cell in row] for row in table.rows] == [["a", "b"], ["c", "d"]]


def test_cell_forms_are_not_lossy_empty_collapse() -> None:
    body = _table(
        _cell(_para(runs=0)) + _cell(_para(empty=True)) + _cell(_para("value")) + _cell(_para("a", runs=2))
    )
    cells = _facts(body).blocks[0].table.rows[0]
    assert [cell.paragraphs[0].text_form for cell in cells] == [
        "no_text", "empty_text", "non_empty_text", "multiple_text_nodes"
    ]
    assert [cell.paragraphs[0].text_nodes for cell in cells] == [0, 1, 1, 2]
    assert [cell.paragraphs[0].runs for cell in cells] == [0, 1, 1, 2]


def test_complex_tables_are_marked_unsupported_without_guessing() -> None:
    nested = _table(_cell(_table(_cell(_para("inner")))))
    merged = _table(_cell(_para("merged"), attrs=' colSpan="2"'))
    drawing = _table(_cell("<hp:p><hp:runs><hp:drawing/></hp:runs></hp:p>"))
    assert _facts(nested).blocks[0].table.unsupported == ("nested_table",)
    assert _facts(merged).blocks[0].table.rows[0][0].unsupported == ("merged_or_spanned",)
    assert "drawing" in _facts(drawing).blocks[0].table.rows[0][0].unsupported


def test_cell_paragraph_with_no_t_is_distinct_from_empty_t() -> None:
    payload = _archive(_table(_cell("<hp:p><hp:runs/></hp:p>")))
    parsed = parse_hwpx_sections(payload)[0]
    assert parsed.paragraphs[0].text_nodes == 0
    with pytest.raises(Exception) as exc:
        extract_hwpx_text(payload)
    assert getattr(exc.value, "code", None) == "hwpx_empty"


def test_parse_uses_ordered_fact_projection_without_second_xml_reader() -> None:
    body = _para("one") + _table(_cell(_para("two")))
    facts = _facts(body)
    parsed = parse_hwpx_sections(_archive(body))[0]
    assert facts.paragraphs == parsed.paragraphs
    assert [block.kind for block in facts.blocks] == ["paragraph", "table"]
    assert _local_name(_parse_xml(_section(body))) == "sec"
