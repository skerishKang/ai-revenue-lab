"""Duplicate detection separates the three kinds and stays explainable."""

from __future__ import annotations

from app.contracts import DuplicateKind, FieldOrigin, FieldValue, ItemRecord
from app.duplicate_detection import detect_duplicates
from app.normalization import rule_field, source_field

from decimal import Decimal


def _record(
    row: int,
    *,
    code: str = "",
    name: str = "",
    spec: str = "",
    unit: str = "",
) -> ItemRecord:
    fields = {
        "item_code": source_field(code, locator=f"csv:row{row}:item_code"),
        "item_name": source_field(name, locator=f"csv:row{row}:item_name"),
        "specification": source_field(spec, locator=f"csv:row{row}:specification"),
        "unit": source_field(unit, locator=f"csv:row{row}:unit"),
    }
    return ItemRecord(source_row=row, fields=fields)


def test_two_records_with_the_same_item_code_are_an_exact_code_duplicate() -> None:
    findings, records = detect_duplicates(
        [
            _record(2, code="SEN-018N-01", name="포토센서"),
            _record(3, code="SEN-018N-01", name="포토센서"),
        ]
    )

    assert len(findings) == 1
    assert findings[0].kind is DuplicateKind.EXACT_CODE
    assert findings[0].primary_row == 2
    assert findings[0].duplicate_rows == (3,)
    assert records[1].duplicate_of == "row2"
    assert records[1].duplicate_group == findings[0].group_id


def test_same_name_specification_and_unit_are_a_same_name_spec_duplicate() -> None:
    findings, records = detect_duplicates(
        [
            _record(2, code="BRG-6205-01", name="볼 베어링 6205-2RS", spec="6205-2RS 내경25mm", unit="EA"),
            _record(3, code="BRG-6205-02", name="볼베어링 6205-2RS", spec="6205-2RS 내경 25mm", unit="EA"),
        ]
    )

    assert len(findings) == 1
    assert findings[0].kind is DuplicateKind.SAME_NAME_SPEC
    assert records[1].duplicate_of == "row2"


def test_a_near_identical_name_is_a_fuzzy_candidate_not_a_verdict() -> None:
    findings, records = detect_duplicates(
        [
            _record(2, code="CAL-0150-00", name="디지털 캘리퍼스 150mm", spec="0-150mm", unit="EA"),
            _record(3, code="CAL-0150-01", name="디지털 캘리퍼스 150mm 정밀", spec="0-150mm", unit="EA"),
        ]
    )

    assert len(findings) == 1
    assert findings[0].kind is DuplicateKind.FUZZY_NAME
    assert findings[0].similarity >= Decimal("0.92")
    assert records[1].duplicate_of == "row2"


def test_different_items_are_not_duplicates() -> None:
    findings, records = detect_duplicates(
        [
            _record(2, code="BRG-6205-01", name="볼 베어링 6205-2RS", spec="6205-2RS", unit="EA"),
            _record(3, code="HOS-0150-01", name="유압호스 조립체", spec="1500mm", unit="본"),
        ]
    )

    assert findings == ()
    assert all(record.duplicate_group is None for record in records)


def test_a_record_without_a_code_cannot_be_an_exact_code_duplicate() -> None:
    findings, _ = detect_duplicates(
        [
            _record(2, name="알루미늄 프로파일"),
            _record(3, name="알루미늄 프로파일"),
        ]
    )

    assert all(finding.kind is not DuplicateKind.EXACT_CODE for finding in findings)
