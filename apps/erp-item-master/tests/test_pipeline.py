"""The whole pipeline on the committed anonymous sample.

The assertions here are the pilot's own acceptance criteria: the sample is
read, normalized, deduplicated, reviewed and written to real import files, and
the written files agree with each other.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.pipeline import run_pipeline

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "samples"
SOURCE = SAMPLE_DIR / "source_items_raw.csv"
EXTRACTION = SAMPLE_DIR / "extraction_results.json"


def _read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [list(row) for row in csv.reader(handle)]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    output = tmp_path_factory.mktemp("erp-item-master")
    return run_pipeline(
        source=SOURCE,
        output_dir=output,
        extraction_file=EXTRACTION,
    ), output


def test_every_sample_row_is_read(run) -> None:
    report, _ = run
    assert report.row_count == 10
    assert report.source_kind == "csv"
    assert "담당자" in report.unmapped_headers


def test_the_run_splits_into_auto_ok_and_review_rows(run) -> None:
    report, _ = run
    assert report.auto_ok_count + report.review_required_count == report.row_count
    assert report.auto_ok_count == 3
    assert report.review_required_count == 7


def test_the_three_duplicate_kinds_are_reported_as_two_groups(run) -> None:
    report, _ = run
    assert report.duplicate_group_count == 2
    assert report.duplicate_record_count == 2
    kinds = sorted(finding.kind.value for finding in report.findings)
    assert kinds == ["EXACT_CODE", "FUZZY_NAME"]


def test_a_refused_extraction_is_counted_and_the_source_value_is_kept(run) -> None:
    report, _ = run
    assert report.extraction_error_count == 2
    assert report.ai_filled_field_count == 1


def test_no_price_is_invented(run) -> None:
    report, output = run
    rows = _read_csv(output / "item_master_normalized.csv")
    header = rows[0]
    price_index = header.index("매입가")
    code_index = header.index("품목코드")

    by_code = {row[code_index]: row for row in rows[1:]}

    # The oil row has no purchase price in the source. It stays empty, and the
    # extraction that proposed one was refused.
    assert by_code["OIL-VG220-18"][price_index] == ""
    # The belt row says "ask". It is not a number, so it is not a price.
    assert by_code["BLT-A45-000"][price_index] == ""


def test_prices_are_read_from_the_source_text(run) -> None:
    _, output = run
    rows = _read_csv(output / "item_master_normalized.csv")
    header = rows[0]
    code_index = header.index("품목코드")
    purchase_index = header.index("매입가")
    sales_index = header.index("판매가")
    by_code = {row[code_index]: row for row in rows[1:]}

    assert by_code["BRG-6205-01"][purchase_index] == "8500"
    assert by_code["BRG-6205-01"][sales_index] == "12000"
    assert by_code["BLT-M8-30-A"][purchase_index] == "1200"


def test_codes_and_names_are_normalized(run) -> None:
    _, output = run
    rows = _read_csv(output / "item_master_normalized.csv")
    header = rows[0]
    code_index = header.index("품목코드")
    name_index = header.index("상품명")
    by_code = {row[code_index]: row for row in rows[1:]}

    assert "BRG-6205-01" in by_code
    assert by_code["BRG-6205-01"][name_index] == "볼 베어링 6205-2RS"
    assert by_code[""][name_index] == "알루미늄 40x40 프로파일"


def test_the_generic_import_file_holds_only_the_auto_ok_rows(run) -> None:
    report, output = run
    rows = _read_csv(output / "erp_import_generic.csv")

    assert len(rows) - 1 == report.auto_ok_count
    assert rows[0] == [
        "품목코드",
        "상품명",
        "모델명",
        "제조사",
        "공급사",
        "규격",
        "단위",
        "상품분류",
        "매입가",
        "판매가",
    ]


def test_the_ecount_candidate_file_is_written_and_marked_as_unconfirmed(run) -> None:
    _, output = run
    candidate = output / "erp_import_ecount_api_candidate_CANDIDATE.csv"
    rows = _read_csv(candidate)

    assert rows[0] == [
        "PROD_CD",
        "PROD_DES",
        "SIZE_DES",
        "UNIT",
        "IN_PRICE",
        "OUT_PRICE",
        "REMARKS",
        "SIZE_FLAG",
    ]


def test_the_field_mapping_status_records_that_the_ecount_columns_are_unverified(run) -> None:
    _, output = run
    rows = _read_csv(output / "erp_field_mapping_status.csv")
    header = rows[0]
    profile_index = header.index("프로필")
    field_index = header.index("정규화필드")
    status_index = header.index("확인상태")

    ecount = {
        row[field_index]: row[status_index]
        for row in rows[1:]
        if row[profile_index] == "ecount_api_candidate"
    }
    assert ecount["item_code"] == "THIRD_PARTY_UNVERIFIED"
    assert ecount["manufacturer"] == "NOT_FOUND"
    assert ecount["model_name"] == "NOT_FOUND"


def test_the_workbook_and_the_csv_carry_the_same_master_rows(run) -> None:
    from openpyxl import load_workbook

    _, output = run
    workbook = load_workbook(output / "item_master_workbook.xlsx")
    sheet = workbook["품목마스터"]
    workbook_rows = [
        ["" if cell.value is None else str(cell.value) for cell in line]
        for line in sheet.iter_rows()
    ]
    workbook.close()

    assert workbook_rows == _read_csv(output / "item_master_normalized.csv")


def test_the_report_is_written_and_states_the_counts(run) -> None:
    report, output = run
    payload = json.loads((output / "pipeline_report.json").read_text(encoding="utf-8"))

    assert payload["row_count"] == report.row_count
    assert payload["auto_ok_count"] == report.auto_ok_count
    assert payload["review_required_count"] == report.review_required_count
    assert "timings_ms" in payload


def test_every_output_file_exists(run) -> None:
    _, output = run
    for name in (
        "item_master_normalized.csv",
        "item_master_before_after.csv",
        "review_required.csv",
        "duplicate_report.csv",
        "erp_import_generic.csv",
        "erp_import_ecount_api_candidate_CANDIDATE.csv",
        "erp_field_mapping_status.csv",
        "item_master_workbook.xlsx",
        "pipeline_report.json",
    ):
        assert (output / name).is_file(), name
