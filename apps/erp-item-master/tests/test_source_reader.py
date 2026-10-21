"""The source reader maps a supplier catalog onto canonical fields."""

from __future__ import annotations

import pytest
from openpyxl import Workbook

from app.contracts import ItemMasterError
from app.source_reader import map_headers, read_source


def test_header_aliases_map_a_mixed_vocabulary_onto_canonical_fields() -> None:
    columns, unmapped, memo_index = map_headers(
        ["품목 코드", "상품명", "Model", "매입단가", "메모", "담당자"]
    )

    assert columns["item_code"] == 0
    assert columns["item_name"] == 1
    assert columns["model_name"] == 2
    assert columns["purchase_price"] == 3
    assert memo_index == 4
    assert unmapped == ("담당자",)


def test_one_column_cannot_feed_two_fields() -> None:
    columns, unmapped, _ = map_headers(["품목코드", "상품명", "코드"])

    assert columns["item_code"] == 0
    assert unmapped == ("코드",)


def test_a_csv_source_is_read_with_its_columns_and_rows(tmp_path) -> None:
    source = tmp_path / "items.csv"
    source.write_text(
        "품목코드,상품명,매입가\n"
        "BRG-1,볼 베어링,8500\n"
        ",알루미늄 프로파일,6800\n",
        encoding="utf-8-sig",
    )

    table = read_source(source)

    assert table.origin_kind == "csv"
    assert len(table.rows) == 2
    assert table.rows[0].cells["item_code"] == "BRG-1"
    assert table.rows[1].cells["item_code"] == ""
    assert table.rows[1].source_row == 3


def test_an_excel_source_is_read_through_the_shared_core_reader(tmp_path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "품목"
    sheet.append(["품목코드", "상품명", "매입가"])
    sheet.append(["BRG-1", "볼 베어링", 8500])
    path = tmp_path / "items.xlsx"
    workbook.save(path)
    workbook.close()

    table = read_source(path)

    assert table.origin_kind == "xlsx"
    assert table.sheet_title == "품목"
    assert table.rows[0].cells["item_code"] == "BRG-1"
    assert table.rows[0].cells["purchase_price"] == "8500"


def test_a_source_with_no_usable_column_is_refused(tmp_path) -> None:
    source = tmp_path / "items.csv"
    source.write_text("알수없음,또알수없음\n1,2\n", encoding="utf-8-sig")

    with pytest.raises(ItemMasterError) as error:
        read_source(source)

    assert error.value.code == "no_mappable_columns"


def test_an_unsupported_source_type_is_refused(tmp_path) -> None:
    source = tmp_path / "items.txt"
    source.write_text("품목코드\nBRG-1\n", encoding="utf-8")

    with pytest.raises(ItemMasterError) as error:
        read_source(source)

    assert error.value.code == "unsupported_source_type"


def test_a_missing_source_is_refused(tmp_path) -> None:
    with pytest.raises(ItemMasterError) as error:
        read_source(tmp_path / "absent.csv")

    assert error.value.code == "source_missing"
