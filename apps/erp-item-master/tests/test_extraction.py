"""An extraction may fill a gap and may never overwrite or fabricate."""

from __future__ import annotations

import json
from decimal import Decimal

from app.extraction import (
    AI_PROVIDER_CALLS_IN_THIS_APP,
    AI_REFUSED_FIELDS,
    load_extraction_file,
    normalize_extracted_fields,
)
from app.pipeline import build_record


def test_a_missing_field_is_filled_from_an_extraction() -> None:
    values, errors = normalize_extracted_fields(
        {"fields": {"supplier": {"value": "정밀계측", "confidence": 0.72}}}, row_number=9
    )

    assert errors == ()
    assert values["supplier"].value == "정밀계측"
    assert values["supplier"].confidence == Decimal("0.72")
    assert values["supplier"].origin.value == "AI_EXTRACTION"


def test_a_generated_price_is_refused_by_name() -> None:
    values, errors = normalize_extracted_fields(
        {"fields": {"purchase_price": {"value": "12000", "confidence": 0.95}}}, row_number=7
    )

    assert values == {}
    assert len(errors) == 1
    assert "purchase_price" in errors[0]
    assert AI_REFUSED_FIELDS["purchase_price"] in errors[0]


def test_a_generated_specification_or_item_code_is_refused() -> None:
    values, errors = normalize_extracted_fields(
        {
            "fields": {
                "specification": {"value": "M8 x 30mm", "confidence": 0.9},
                "item_code": {"value": "BLT-1", "confidence": 0.9},
            }
        },
        row_number=4,
    )

    assert values == {}
    assert len(errors) == 2


def test_an_unknown_field_is_refused_rather_than_silently_dropped() -> None:
    values, errors = normalize_extracted_fields(
        {"fields": {"lead_time": {"value": "3일", "confidence": 0.9}}}, row_number=4
    )

    assert values == {}
    assert errors == ("lead_time: not a canonical item-master field",)


def test_a_confidence_outside_the_range_is_refused() -> None:
    values, errors = normalize_extracted_fields(
        {"fields": {"supplier": {"value": "정밀계측", "confidence": 1.4}}}, row_number=9
    )

    assert values == {}
    assert "confidence" in errors[0]


def test_a_confidence_below_the_usable_bound_is_refused() -> None:
    values, errors = normalize_extracted_fields(
        {"fields": {"supplier": {"value": "정밀계측", "confidence": 0.2}}}, row_number=9
    )

    assert values == {}
    assert "usable bound" in errors[0]


def test_a_source_value_wins_over_an_extraction() -> None:
    extracted, _ = normalize_extracted_fields(
        {"fields": {"supplier": {"value": "다른공급사", "confidence": 0.99}}}, row_number=3
    )
    record = build_record(
        3,
        {"item_code": "A-1", "item_name": "품목", "supplier": "원래공급사"},
        locator="csv:row3",
        extracted=extracted,
    )

    assert record.text("supplier") == "원래공급사"
    assert record.origin("supplier").value == "SOURCE_ROW"


def test_an_extraction_file_is_read_by_item_code(tmp_path) -> None:
    path = tmp_path / "extraction.json"
    path.write_text(
        json.dumps(
            {"CAL-0150-00": {"fields": {"supplier": {"value": "정밀계측", "confidence": 0.72}}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    by_row, by_code = load_extraction_file(path)

    assert by_row == {}
    assert by_code["CAL-0150-00"][0]["supplier"].value == "정밀계측"


def test_the_app_makes_no_model_call() -> None:
    assert AI_PROVIDER_CALLS_IN_THIS_APP == 0
