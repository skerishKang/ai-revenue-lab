from __future__ import annotations

import inspect
from io import BytesIO
from zipfile import ZipFile

import pytest

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.hwpx_package_serializer import (
    MAX_HWPX_CELL_TEXT_CHARS,
    MAX_HWPX_PACKAGE_TABLE_CELLS,
    MAX_HWPX_TABLE_CELLS,
    MAX_HWPX_TABLE_COLUMNS,
    MAX_HWPX_TABLE_ROWS,
    HwpxPackageContent,
    HwpxPackageSection,
    HwpxSectionBlock,
    HwpxTable,
    HwpxTableCell,
    deserialize_hwpx_package,
    serialize_hwpx_package,
)


def _table(*rows: tuple[str, ...]) -> HwpxTable:
    return HwpxTable(tuple(tuple(HwpxTableCell(text) for text in row) for row in rows))


def _content(*blocks: HwpxSectionBlock) -> HwpxPackageContent:
    paragraphs = tuple(block.text for block in blocks if block.kind == "paragraph")
    return HwpxPackageContent((HwpxPackageSection(paragraphs=paragraphs, blocks=blocks),))


def _roundtrip(*blocks: HwpxSectionBlock) -> HwpxPackageContent:
    content = _content(*blocks)
    decoded = deserialize_hwpx_package(serialize_hwpx_package(content))
    assert decoded == content
    assert serialize_hwpx_package(decoded) == serialize_hwpx_package(content)
    return decoded


@pytest.mark.parametrize(
    "rows",
    [
        (("한글",),),
        (("한글", "Latin", "123", ""),),
        (("한",), ("둘",), ("셋",)),
        (("한", "둘"), ("셋", "넷"), ("다섯", "여섯")),
    ],
)
def test_bounded_table_shapes_roundtrip(rows: tuple[tuple[str, ...], ...]) -> None:
    decoded = _roundtrip(HwpxSectionBlock("table", table=_table(*rows)))
    assert decoded.sections[0].blocks[0].table == _table(*rows)


def test_table_text_is_not_flattened_into_paragraph_projection() -> None:
    decoded = _roundtrip(HwpxSectionBlock("table", table=_table(("한글", "Latin"))))
    assert decoded.sections[0].paragraphs == ()
    assert decoded.sections[0].blocks[0].kind == "table"


def test_ordered_block_placements_roundtrip() -> None:
    table = HwpxSectionBlock("table", table=_table(("cell",)))
    _roundtrip(HwpxSectionBlock("paragraph", text="before"), table, HwpxSectionBlock("paragraph", text="after"))
    _roundtrip(table, HwpxSectionBlock("paragraph", text="after"))
    _roundtrip(HwpxSectionBlock("paragraph", text="before"), table)


@pytest.mark.parametrize(
    "rows,code",
    [
        (((),), "hwpx_serialize_table_shape"),
        ((("a",), ("b", "c")), "hwpx_serialize_table_shape"),
        ((tuple("x" for _ in range(MAX_HWPX_TABLE_COLUMNS + 1)),), "hwpx_serialize_table_shape"),
        (tuple(("x",) for _ in range(MAX_HWPX_TABLE_ROWS + 1)), "hwpx_serialize_table_row_limit"),
    ],
)
def test_invalid_shapes_and_overflow_fail_closed(rows: tuple[tuple[str, ...], ...], code: str) -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        serialize_hwpx_package(_content(HwpxSectionBlock("table", table=_table(*rows))))
    assert exc.value.code == code


def test_cell_text_overflow_and_cell_count_are_bounded() -> None:
    with pytest.raises(DocumentNormalizationError) as text:
        serialize_hwpx_package(_content(HwpxSectionBlock("table", table=_table(("x" * (MAX_HWPX_CELL_TEXT_CHARS + 1),)))))
    assert text.value.code == "hwpx_serialize_cell_text_limit"

    maximum_table = HwpxSectionBlock(
        "table",
        table=HwpxTable(
            tuple(
                tuple(HwpxTableCell("x") for _ in range(MAX_HWPX_TABLE_COLUMNS))
                for _ in range(MAX_HWPX_TABLE_ROWS)
            )
        ),
    )
    with pytest.raises(DocumentNormalizationError) as package_count:
        serialize_hwpx_package(_content(maximum_table, maximum_table, maximum_table))
    assert package_count.value.code == "hwpx_serialize_table_cell_limit"
    assert MAX_HWPX_TABLE_CELLS <= MAX_HWPX_TABLE_ROWS * MAX_HWPX_TABLE_COLUMNS
    assert MAX_HWPX_PACKAGE_TABLE_CELLS == MAX_HWPX_TABLE_CELLS


def test_raw_xml_authority_is_not_exposed() -> None:
    for cls in (HwpxSectionBlock, HwpxTable, HwpxTableCell):
        fields = set(inspect.signature(cls).parameters)
        assert not fields & {"xml", "namespace", "member", "relationship_id", "style_id", "attributes"}


def test_legacy_table_remainder_still_fails_closed() -> None:
    payload = (
        b'<?xml version="1.0"?><hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        b'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"><hp:tbl><hp:tr><hp:tc>'
        b'<hp:p><hp:runs><hp:t>cell</hp:t></hp:runs></hp:p></hp:tc></hp:tr></hp:tbl></hp:sec>'
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("Contents/section1.xml", payload)
    with pytest.raises(DocumentNormalizationError):
        deserialize_hwpx_package(buffer.getvalue())
