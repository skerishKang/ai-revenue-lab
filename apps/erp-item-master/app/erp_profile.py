"""Import profiles: how canonical item fields reach a concrete ERP.

A profile is a mapping from canonical fields to one ERP's import schema. It
carries the evidence status of every target column, because an ERP that has
not published its import schema must not be presented as if it had.

Three confirmation levels exist and they are not interchangeable:

``CONFIRMED_OFFICIAL``
    The vendor's own public documentation states the field and its meaning.

``THIRD_PARTY_UNVERIFIED``
    A non-vendor source reports the field. It is good enough to build and to
    review against, and never good enough to promise.

``PENDING_CUSTOMER_TEMPLATE``
    The only authority is the template the customer downloads from their own
    ERP account, so the mapping stays unbound until that file arrives.

``NOT_FOUND``
    No source established a target field, so the canonical field is reported
    as unmapped instead of being pushed into a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import ConfirmationStatus

#: The vendor pages this profile was built from.
ECOUNT_OFFICIAL_SOURCES: tuple[str, ...] = (
    "https://www.ecount.com/kr/ecount/product/erp_open-api",
    "https://www.ecount.com/kr/ecount/product/erp_migration",
    "https://www.ecount.com/kr/ecount/product/inventory_item-management",
)


@dataclass(frozen=True, slots=True)
class ImportColumn:
    """One target column of an import file."""

    canonical_field: str
    target_header: str
    required: bool
    confirmation: ConfirmationStatus
    evidence: str
    note: str = ""
    constant_value: str | None = None


@dataclass(frozen=True, slots=True)
class ErpImportProfile:
    """One ERP's import schema and the evidence behind it."""

    profile_id: str
    display_name: str
    transport: str
    template_confirmed: bool
    confirmation_source: str
    columns: tuple[ImportColumn, ...]
    unmapped_fields: tuple[str, ...] = ()
    row_limit: int | None = None
    rate_limit_note: str = ""
    notes: str = ""
    upload_ready: bool = False

    def columns_for(self, canonical_field: str) -> tuple[ImportColumn, ...]:
        return tuple(
            column for column in self.columns if column.canonical_field == canonical_field
        )

    @property
    def header_row(self) -> tuple[str, ...]:
        return tuple(column.target_header for column in self.columns)

    def column_header_is_unbound(self) -> bool:
        """Whether the target columns are still waiting for the real template.

        A profile in this state must not be presented as an import format:
        the column names come from the customer's own ERP account, not from a
        published specification.
        """

        return any(
            column.confirmation is ConfirmationStatus.PENDING_CUSTOMER_TEMPLATE
            for column in self.columns
        )


def generic_profile() -> ErpImportProfile:
    """The ERP-neutral import schema.

    This profile is fully specified by this repository, so it is confirmed by
    construction. It is the format every other profile is compared against.
    """

    columns = (
        ImportColumn("item_code", "품목코드", True, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("item_name", "상품명", True, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("model_name", "모델명", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("manufacturer", "제조사", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("supplier", "공급사", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("specification", "규격", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("unit", "단위", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("category", "상품분류", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("purchase_price", "매입가", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
        ImportColumn("sales_price", "판매가", False, ConfirmationStatus.CONFIRMED_OFFICIAL, "self_defined"),
    )
    return ErpImportProfile(
        profile_id="generic",
        display_name="범용 ERP 품목 임포트 (본 저장소 정의)",
        transport="FILE",
        template_confirmed=True,
        confirmation_source="self_defined",
        columns=columns,
        upload_ready=True,
        notes=(
            "ERP 제품이 특정되지 않은 상태에서 사용하는 범용 구조다. "
            "실제 ERP가 정해지면 아래 ecount_* 프로파일로 변환한다."
        ),
    )


def ecount_api_candidate_profile() -> ErpImportProfile:
    """ECOUNT Open API 품목등록 후보 스키마.

    ECOUNT's public Open API page confirms that a 품목등록 (item registration)
    input API and a 품목 (item) query API exist, that using the API carries no
    extra cost, and that the detailed manual is only visible after signing in.
    The public manual URL answers an anonymous request with HTTP 410, so the
    exact request field names are not publicly documented.

    The field names below come from non-vendor sources reporting an
    ECOUNT-provided example file, so every column is
    ``THIRD_PARTY_UNVERIFIED``. The file this profile produces is a candidate
    for review, not an upload file.
    """

    unverified = "third_party_report_of_ecount_example_file"
    columns = (
        ImportColumn(
            "item_code",
            "PROD_CD",
            True,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="품목코드. 제3자 보고 기준 최대 20자.",
        ),
        ImportColumn(
            "item_name",
            "PROD_DES",
            True,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="품목명.",
        ),
        ImportColumn(
            "specification",
            "SIZE_DES",
            False,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="규격. SIZE_FLAG 값에 따라 필수 여부가 달라진다는 보고가 있다.",
        ),
        ImportColumn(
            "unit",
            "UNIT",
            False,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="단위.",
        ),
        ImportColumn(
            "purchase_price",
            "IN_PRICE",
            False,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="입고단가.",
        ),
        ImportColumn(
            "sales_price",
            "OUT_PRICE",
            False,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="출고단가.",
        ),
        ImportColumn(
            "memo",
            "REMARKS",
            False,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="비고.",
        ),
        ImportColumn(
            "",
            "SIZE_FLAG",
            True,
            ConfirmationStatus.THIRD_PARTY_UNVERIFIED,
            unverified,
            note="규격 필수 여부 플래그. 제3자 보고는 '1'=필수규격이라 한다.",
            constant_value="1",
        ),
    )
    return ErpImportProfile(
        profile_id="ecount_api_candidate",
        display_name="이카운트 오픈 API 품목등록 후보 (미검증)",
        transport="API",
        template_confirmed=False,
        confirmation_source="https://www.ecount.com/kr/ecount/product/erp_open-api",
        columns=columns,
        unmapped_fields=("manufacturer", "model_name", "category", "supplier"),
        row_limit=300,
        rate_limit_note="제3자 보고 기준 10초당 1회 호출 제한.",
        notes=(
            "이 파일은 업로드 파일이 아니다. 공식 매뉴얼이 로그인 뒤에만 제공되어 "
            "필드명이 확정되지 않았다. 제조사·모델명은 대응 필드를 찾지 못했고, "
            "공급사와 상품분류는 이카운트가 코드(CUST/CLASS_CD)를 요구하므로 "
            "이름 값을 그대로 옮길 수 없다."
        ),
        upload_ready=False,
    )


def ecount_excel_profile() -> ErpImportProfile:
    """ECOUNT Excel 업로드 양식 프로파일.

    ECOUNT's public page confirms that the Excel upload carries 품목정보, that
    a failed upload reports its reason, and that already registered data can be
    updated the same way. It does not publish the item sheet's column set: the
    sheet is generated from the customer's own 기본 탭 configuration, so the
    column set is a property of that customer's account.

    The columns therefore stay unbound, and the pipeline emits a binding
    checklist instead of a file that pretends to be the vendor format.
    """

    columns = (
        ImportColumn(
            "item_code",
            "",
            True,
            ConfirmationStatus.PENDING_CUSTOMER_TEMPLATE,
            "https://www.ecount.com/kr/ecount/product/erp_migration",
            note="고객 계정에서 다운로드한 품목등록 양식의 열 이름 확인 필요.",
        ),
    )
    return ErpImportProfile(
        profile_id="ecount_excel_template",
        display_name="이카운트 엑셀 품목등록 양식 (고객 계정에서 확정 필요)",
        transport="FILE",
        template_confirmed=False,
        confirmation_source="https://www.ecount.com/kr/ecount/product/erp_migration",
        columns=columns,
        unmapped_fields=(
            "item_name",
            "model_name",
            "manufacturer",
            "supplier",
            "specification",
            "unit",
            "category",
            "purchase_price",
            "sales_price",
        ),
        row_limit=None,
        rate_limit_note="",
        notes=(
            "공개 자료에 품목 시트 열 구성이 없다. 재고Ⅰ-기초등록-품목등록 화면의 "
            "웹자료올리기에서 서식을 내려받아 열 이름과 필수 표시(노란색)를 확인한 뒤 "
            "이 프로파일을 확정한다. 서식의 열 순서와 이름을 임의로 바꾸면 오류가 "
            "난다는 운영 사례가 있다."
        ),
        upload_ready=False,
    )


def profile_by_id(profile_id: str) -> ErpImportProfile:
    """Look up a profile by its identifier."""

    profiles = {
        "generic": generic_profile(),
        "ecount_api_candidate": ecount_api_candidate_profile(),
        "ecount_excel_template": ecount_excel_profile(),
    }
    try:
        return profiles[profile_id]
    except KeyError as exc:
        raise KeyError(f"unknown import profile: {profile_id}") from exc


def all_profiles() -> Mapping[str, ErpImportProfile]:
    """Every profile this repository ships."""

    return {
        "generic": generic_profile(),
        "ecount_api_candidate": ecount_api_candidate_profile(),
        "ecount_excel_template": ecount_excel_profile(),
    }
