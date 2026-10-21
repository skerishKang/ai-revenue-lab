"""The ECOUNT profile reports its own evidence and never overstates it."""

from __future__ import annotations

from app.contracts import ConfirmationStatus
from app.erp_profile import (
    ECOUNT_OFFICIAL_SOURCES,
    all_profiles,
    ecount_api_candidate_profile,
    ecount_excel_profile,
    generic_profile,
    profile_by_id,
)


def test_the_generic_profile_is_fully_specified_and_upload_ready() -> None:
    profile = generic_profile()

    assert profile.template_confirmed is True
    assert profile.upload_ready is True
    assert profile.header_row == (
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
    )


def test_the_ecount_api_candidate_is_not_upload_ready_and_says_so() -> None:
    profile = ecount_api_candidate_profile()

    assert profile.template_confirmed is False
    assert profile.upload_ready is False
    assert profile.transport == "API"
    assert all(
        column.confirmation is ConfirmationStatus.THIRD_PARTY_UNVERIFIED
        for column in profile.columns
    )


def test_the_ecount_api_candidate_names_the_fields_it_cannot_map() -> None:
    profile = ecount_api_candidate_profile()

    assert "manufacturer" in profile.unmapped_fields
    assert "model_name" in profile.unmapped_fields
    assert "category" in profile.unmapped_fields
    assert "supplier" in profile.unmapped_fields


def test_the_ecount_excel_template_stays_unbound() -> None:
    profile = ecount_excel_profile()

    assert profile.template_confirmed is False
    assert profile.upload_ready is False
    assert all(
        column.confirmation is ConfirmationStatus.PENDING_CUSTOMER_TEMPLATE
        for column in profile.columns
    )
    assert profile.column_header_is_unbound()


def test_the_official_sources_are_the_vendor_pages() -> None:
    assert all(source.startswith("https://www.ecount.com/") for source in ECOUNT_OFFICIAL_SOURCES)


def test_profiles_are_reachable_by_id() -> None:
    assert set(all_profiles()) == {
        "generic",
        "ecount_api_candidate",
        "ecount_excel_template",
    }
    assert profile_by_id("generic").profile_id == "generic"
