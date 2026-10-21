"""Normalization rules never invent a value and never lose a real one."""

from __future__ import annotations

from decimal import Decimal

from app.normalization import (
    MAX_TEXT_CHARS,
    looks_like_formula,
    normalize_code,
    normalize_form_name,
    normalize_text,
    parse_price,
    rule_field,
    source_field,
)


def test_text_trims_collapses_and_drops_invisible_characters() -> None:
    assert normalize_text("  볼  베어링\u200b 6205-2RS \n") == "볼 베어링 6205-2RS"
    assert normalize_text(None) == ""
    assert normalize_text(42) == "42"


def test_text_folds_full_width_ascii_but_keeps_korean_and_symbols() -> None:
    assert normalize_text("알루미늄 ４０x４０") == "알루미늄 40x40"
    assert normalize_text("%（주）") == "%(주)"


def test_text_is_bounded() -> None:
    assert len(normalize_text("가" * (MAX_TEXT_CHARS + 100))) == MAX_TEXT_CHARS


def test_code_uppercases_removes_spaces_and_folds_full_width() -> None:
    assert normalize_code(" brg-6205-01 ") == "BRG-6205-01"
    assert normalize_code("ＢＲＧ－６２０５") == "BRG-6205"
    assert normalize_code("") == ""


def test_price_parsing_reads_common_shapes_and_never_invents_one() -> None:
    assert parse_price("8,500원") == ("8500", None)
    assert parse_price(" 12,000 ") == ("12000", None)
    assert parse_price("₩32000") == ("32000", None)
    assert parse_price("") == (None, None)
    assert parse_price("   ") == (None, None)


def test_price_that_is_not_a_number_is_refused_with_a_reason() -> None:
    assert parse_price("문의") == (None, "price_not_numeric")
    assert parse_price("약 1만원") == (None, "price_not_numeric")
    assert parse_price("abc" * 30) == (None, "price_too_long")


def test_formula_lookalikes_are_detected() -> None:
    assert looks_like_formula("=1+1")
    assert looks_like_formula("@SUM(A1)")
    assert not looks_like_formula("6205-2RS")


def test_form_name_key_drops_spacing_and_case_but_keeps_the_product() -> None:
    assert normalize_form_name("볼  베어링 6205-2RS") == normalize_form_name(
        "볼베어링 6205-2RS"
    )
    assert normalize_form_name("디지털 캘리퍼스 150mm") != normalize_form_name(
        "디지털 캘리퍼스 150mm 정밀"
    )


def test_empty_source_value_is_reported_missing_rather_than_defaulted() -> None:
    value = source_field("   ", locator="csv:row2:unit")
    assert value.present is False
    assert value.origin.value == "MISSING"
    assert value.note == "empty_in_source"


def test_rule_field_records_that_a_rule_produced_the_value() -> None:
    value = rule_field("BRG-6205-01", locator="csv:row2:item_code")
    assert value.present is True
    assert value.origin.value == "RULE_NORMALIZATION"
    assert value.as_decimal() is None


def test_amount_parsing_of_a_rule_field_is_exact() -> None:
    value = rule_field("8500", locator="csv:row2:purchase_price")
    assert value.as_decimal() == Decimal("8500")
