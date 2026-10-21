"""Canonical item-master contracts for the ERP item data pilot (#5447).

The canonical record is ERP-neutral on purpose. A concrete ERP's import schema
is described separately by :mod:`app.erp_profile`, so a new ERP never changes
this contract and never becomes a second source of truth for a field.

Every value keeps its provenance: where it came from, how much the pipeline
trusts it, and where in the source it was read from. A value the pipeline could
not derive is ``MISSING`` with a reason, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping

#: The canonical item-master fields, in the order an ERP import file lists them.
CANONICAL_FIELDS: tuple[str, ...] = (
    "item_code",
    "item_name",
    "model_name",
    "manufacturer",
    "supplier",
    "specification",
    "unit",
    "category",
    "purchase_price",
    "sales_price",
)

#: Fields an ERP cannot accept an item without.
REQUIRED_FIELDS: tuple[str, ...] = ("item_code", "item_name")

#: Fields parsed as a decimal amount rather than as free text.
PRICE_FIELDS: tuple[str, ...] = ("purchase_price", "sales_price")

#: Fields that describe the item itself rather than the pipeline's bookkeeping.
BUSINESS_FIELDS: tuple[str, ...] = CANONICAL_FIELDS

#: Fields carried through from the source without becoming part of the
#: canonical record. A supplier's free-text note is kept so an ERP that wants
#: a remark column can have one.
PASSTHROUGH_FIELDS: tuple[str, ...] = ("memo",)

#: Every field the pipeline can carry.
KNOWN_FIELDS: tuple[str, ...] = CANONICAL_FIELDS + PASSTHROUGH_FIELDS


class FieldOrigin(str, Enum):
    """Where one field value came from."""

    SOURCE = "SOURCE_ROW"
    AI_EXTRACTION = "AI_EXTRACTION"
    RULE = "RULE_NORMALIZATION"
    MISSING = "MISSING"


class ReviewStatus(str, Enum):
    """Whether a record can go to an ERP as it is."""

    AUTO_OK = "AUTO_OK"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class DuplicateKind(str, Enum):
    """How two records were judged to describe the same item."""

    EXACT_CODE = "EXACT_CODE"
    SAME_NAME_SPEC = "SAME_NAME_SPEC"
    FUZZY_NAME = "FUZZY_NAME"


class ConfirmationStatus(str, Enum):
    """How well one import-schema claim is backed by evidence.

    ``CONFIRMED_OFFICIAL`` means an official vendor page states it.
    ``THIRD_PARTY_UNVERIFIED`` means a non-vendor source reports it, so it is
    usable as a working hypothesis and never as a promise.
    ``PENDING_CUSTOMER_TEMPLATE`` means the only authority is the template the
    customer downloads from their own ERP account.
    ``NOT_FOUND`` means no source established it.
    """

    CONFIRMED_OFFICIAL = "CONFIRMED_OFFICIAL"
    THIRD_PARTY_UNVERIFIED = "THIRD_PARTY_UNVERIFIED"
    PENDING_CUSTOMER_TEMPLATE = "PENDING_CUSTOMER_TEMPLATE"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class FieldValue:
    """One canonical field value with its provenance.

    ``confidence`` is a plain decimal in ``[0, 1]``. A rule that only trimmed
    whitespace keeps the source value's confidence; a value an AI extraction
    proposed carries the extraction's own confidence so a human can see which
    numbers deserve a second look.
    """

    value: str
    origin: FieldOrigin
    confidence: Decimal
    source_locator: str
    note: str = ""

    @property
    def present(self) -> bool:
        return self.origin is not FieldOrigin.MISSING and bool(self.value)

    def as_decimal(self) -> Decimal | None:
        """Parse the value as an amount, or return ``None`` when it is not one."""

        if not self.present:
            return None
        try:
            return Decimal(self.value)
        except InvalidOperation:
            return None


@dataclass(frozen=True, slots=True)
class ItemRecord:
    """One normalized item-master record.

    ``fields`` holds the canonical values the pipeline will import.
    ``raw`` holds the source cells exactly as they were read, so a reviewer can
    compare the before and after of one row without reopening the source file.
    """

    source_row: int
    fields: Mapping[str, FieldValue]
    raw: Mapping[str, str] = field(default_factory=dict)
    duplicate_group: str | None = None
    duplicate_kind: DuplicateKind | None = None
    duplicate_of: str | None = None
    review_status: ReviewStatus = ReviewStatus.AUTO_OK
    review_reasons: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default=())

    def text(self, key: str) -> str:
        value = self.fields.get(key)
        return value.value if value is not None and value.present else ""

    def amount(self, key: str) -> Decimal | None:
        value = self.fields.get(key)
        return value.as_decimal() if value is not None else None

    def origin(self, key: str) -> FieldOrigin:
        value = self.fields.get(key)
        return value.origin if value is not None else FieldOrigin.MISSING

    @property
    def item_code(self) -> str:
        return self.text("item_code")

    @property
    def item_name(self) -> str:
        return self.text("item_name")

    @property
    def needs_review(self) -> bool:
        return self.review_status is ReviewStatus.REVIEW_REQUIRED


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One raw source row with the physical position it came from."""

    source_row: int
    cells: Mapping[str, str]
    locator: str


@dataclass(frozen=True, slots=True)
class SourceTable:
    """A bounded source table with its canonical column mapping."""

    headers: tuple[str, ...]
    rows: tuple[SourceRow, ...]
    column_by_field: Mapping[str, int]
    unmapped_headers: tuple[str, ...]
    origin_kind: str
    sheet_title: str | None = None
    truncated: bool = False


class ItemMasterError(Exception):
    """A source or extraction the pipeline refuses to interpret."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
