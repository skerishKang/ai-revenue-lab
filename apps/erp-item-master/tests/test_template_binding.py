"""A real template file binds the canonical fields without anybody guessing."""

from __future__ import annotations

import pytest
from openpyxl import Workbook

from app.contracts import ConfirmationStatus
from app.erp_profile import ErpImportProfile
from app.exporter import profile_rows, write_rows
from app.pipeline import build_record
from app.template_binding import (
    TemplateBindingError,
    bind_template,
    binding_profile,
    binding_report_rows,
)

#: A synthetic stand-in for a vendor template. The wording is deliberately
#: different from any real vendor file: this proves the binder works from the
#: file's own text, not from a remembered name.
TEMPLATE_ROWS: tuple[tuple[str, ...], ...] = (
    ("품목 등록 양식", "", "", "", "", ""),
    ("아래 노란색 칸을 반드시 입력하십시오.", "", "", "", "", ""),
    ("품목코드", "품목명", "규격", "단위", "입고단가", "출고단가"),
    ("", "", "", "", "", ""),
    ("BRG-1", "볼 베어링", "6205", "EA", "8500", "12000"),
)


def _write_template(path, rows=TEMPLATE_ROWS):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "품목"
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    workbook.close()
    return path


def test_the_header_row_is_found_below_the_title_rows(tmp_path) -> None:
    binding = bind_template(_write_template(tmp_path / "양식.xlsx"))

    assert binding.header_row_index == 2
    assert binding.headers == ("품목코드", "품목명", "규격", "단위", "입고단가", "출고단가")
    assert binding.fully_bound is True


def test_the_written_header_always_comes_from_the_template_file(tmp_path) -> None:
    binding = bind_template(_write_template(tmp_path / "양식.xlsx"))
    profile = binding_profile(binding, profile_id="template_bound")

    assert profile.header_row == binding.headers
    assert profile.header_row == ("품목코드", "품목명", "규격", "단위", "입고단가", "출고단가")


def test_a_bound_profile_keeps_the_template_column_order(tmp_path) -> None:
    binding = bind_template(_write_template(tmp_path / "양식.xlsx"))
    profile = binding_profile(binding, profile_id="template_bound")

    fields = [column.canonical_field for column in profile.columns]
    assert fields == ["item_code", "item_name", "specification", "unit", "purchase_price", "sales_price"]
    assert profile.upload_ready is True
    assert profile.template_confirmed is True


def test_a_canonical_field_the_template_lacks_is_reported_and_left_empty(tmp_path) -> None:
    rows = (
        ("품목코드", "품목명", "단위", "메모"),
        ("BRG-1", "볼 베어링", "EA", "비고"),
    )
    binding = bind_template(_write_template(tmp_path / "양식.xlsx", rows))

    assert "specification" in binding.unmapped_fields
    assert "purchase_price" in binding.unmapped_fields
    assert "sales_price" in binding.unmapped_fields
    assert binding.fully_bound is True


def test_a_template_without_the_item_code_is_not_upload_ready(tmp_path) -> None:
    rows = (("품목명", "단위"), ("볼 베어링", "EA"))
    binding = bind_template(_write_template(tmp_path / "양식.xlsx", rows))

    assert binding.fully_bound is False
    assert "item_code" in binding.unbound_required_fields

    profile = binding_profile(binding, profile_id="template_bound")
    assert profile.upload_ready is False


def test_a_template_with_no_recognizable_header_is_refused(tmp_path) -> None:
    rows = (("가", "나"), ("다", "라"))
    with pytest.raises(TemplateBindingError) as error:
        bind_template(_write_template(tmp_path / "양식.xlsx", rows))

    assert error.value.code == "template_header_not_found"


def test_a_missing_template_file_is_refused(tmp_path) -> None:
    with pytest.raises(TemplateBindingError) as error:
        bind_template(tmp_path / "없음.xlsx")

    assert error.value.code == "template_missing"


def test_the_bound_profile_writes_the_template_shape_with_its_own_headers(tmp_path) -> None:
    binding = bind_template(_write_template(tmp_path / "양식.xlsx"))
    profile = binding_profile(binding, profile_id="template_bound")
    record = build_record(
        2,
        {
            "item_code": "BRG-1",
            "item_name": "볼 베어링",
            "specification": "6205",
            "unit": "EA",
            "purchase_price": "8500",
            "sales_price": "12000",
        },
        locator="csv:row2",
    )

    target = write_rows(
        tmp_path / "bound.csv",
        profile.header_row,
        profile_rows(profile, [record]),
    )

    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [line.rstrip("\r\n") for line in handle]
    assert rows[0] == "품목코드,품목명,규격,단위,입고단가,출고단가"
    assert rows[1] == "BRG-1,볼 베어링,6205,EA,8500,12000"


def test_the_binding_report_names_the_template_and_its_unmapped_fields(tmp_path) -> None:
    rows = (("품목코드", "품목명", "단위"), ("BRG-1", "볼 베어링", "EA"))
    binding = bind_template(_write_template(tmp_path / "양식.xlsx", rows))

    report = binding_report_rows(binding)
    mapped = {row[0]: row for row in report}

    assert mapped["item_code"][1] == "품목코드"
    assert mapped["item_code"][4] == ConfirmationStatus.CONFIRMED_OFFICIAL.value
    assert "specification" in mapped
    assert mapped["specification"][1] == "(템플릿에 해당 열 없음)"
    assert binding.template_sha256


def test_the_bound_profile_records_the_template_file_as_its_evidence(tmp_path) -> None:
    binding = bind_template(_write_template(tmp_path / "양식.xlsx"))
    profile = binding_profile(binding, profile_id="template_bound")

    assert all(
        column.confirmation is ConfirmationStatus.CONFIRMED_OFFICIAL
        for column in profile.columns
    )
    assert all(
        "ecount_template_file" in column.evidence for column in profile.columns
    )
