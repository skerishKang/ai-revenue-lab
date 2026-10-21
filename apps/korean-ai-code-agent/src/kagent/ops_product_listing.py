"""#5446: online product listing pilot — one product, end to end, on existing PADIEM contracts.

What this module is
-------------------
A business-pilot vertical slice for "온라인 상품 등록·판매채널 운영". It takes one
supplier product file, merges researched product facts, and produces the
artifacts a seller console needs: a canonical product record, one registration
draft per sales channel, a detail-page description, an image manifest, a
browser fill plan, and a measured work log.

It is a **preparation** slice, not a publishing slice. It never opens a seller
account, never calls a channel API, never uploads an image and never submits a
form. Every draft carries an explicit readiness verdict so the human owner
knows exactly what is prepared and what is not.

Reuse disposition (no new engine, no new model router)
------------------------------------------------------
This module adds no AI engine, no provider call, no model route and no new
authority. It reuses:

* :mod:`kagent.ops_intake` — ``ExtractedField`` / ``ExtractionOrigin`` /
  ``FieldReviewStatus`` for per-field provenance and review state. Parsing
  certainty never becomes business truth: an unreviewed field stays
  unreviewed.
* :mod:`kagent.ops_pilot` — ``PilotKpiEngine`` / ``PilotObservation`` /
  ``MetricDefinition`` / ``EvidenceQuality`` for measured pilot KPIs.
* :mod:`kagent.ops_pilot_telemetry` — ``WorkflowTelemetryEvent`` /
  ``PilotTelemetryKind`` / ``PilotMeasurementBridge`` for the milestone and
  duration derivation.
* :mod:`kagent.browser_control_actions` — ``classify_browser_control_action``
  for the bounded browser action vocabulary. The fill plan never invents an
  action the product does not already classify.
* :mod:`padiem_ai_core.document_normalization` — the reviewed Core binary
  parser for a supplier XLSX file, instead of a second spreadsheet reader.

The only genuinely new code is the product-listing domain model and the
channel-agnostic projection engine. The supplier CSV intake follows the
bounded-contract pattern already established by
:mod:`kagent.ops_csv_intake` (exact header set, cell bounds, spreadsheet
formula guard) but carries a different schema, because a purchase-request row
and a product-attribute row are different contracts.

Honest measurement rule
-----------------------
A baseline the team has not measured stays an **estimate**. ``EvidenceQuality``
keeps the two apart, and the KPI engine refuses to compute a percent change
from an estimated baseline. This module never reports a productivity delta it
did not measure.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from .browser_control_actions import classify_browser_control_action
from .contracts import ContractError
from .ops_intake import (
    ExtractedField,
    ExtractionOrigin,
    FieldReviewStatus,
    IntakeSource,
    IntakeSourceKind,
)
from .ops_pilot import (
    EvidenceQuality,
    MetricDefinition,
    MetricDirection,
    MetricUnit,
    PilotKpiEngine,
    PilotObservation,
    PilotPhase,
)
from .ops_pilot_telemetry import (
    PilotMeasurementBridge,
    PilotTelemetryKind,
    WorkflowTelemetryEvent,
)

MAX_SUPPLIER_ROWS = 500
MAX_SUPPLIER_CELL_CHARS = 2000
MAX_SUPPLIER_FILE_BYTES = 4 * 1024 * 1024
MAX_RESEARCH_NOTES = 200
MAX_IMAGE_ALT_CHARS = 200
MAX_KEYWORDS = 50

_FORMULA_PREFIXES = ("=", "+", "-", "@")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_XLSX_CELL_RE = re.compile(r"^\[(?P<sheet>[^\]]+)!(?P<coord>[A-Z]+(?P<row>\d+))\]\s(?P<value>.*)$")


class ProductAttribute(str, Enum):
    """The canonical product attribute vocabulary shared by every channel."""

    PRODUCT_NAME = "product_name"
    MODEL_NAME = "model_name"
    BRAND = "brand"
    MANUFACTURER = "manufacturer"
    CATEGORY_PATH = "category_path"
    CATEGORY_CODE = "category_code"
    COLOR = "color"
    SIZE = "size"
    MATERIAL = "material"
    WEIGHT_KG = "weight_kg"
    WIDTH_MM = "width_mm"
    HEIGHT_MM = "height_mm"
    DEPTH_MM = "depth_mm"
    UNIT = "unit"
    SALE_PRICE = "sale_price"
    LIST_PRICE = "list_price"
    STOCK_QUANTITY = "stock_quantity"
    MIN_ORDER_QUANTITY = "min_order_quantity"
    PRODUCT_IDENTIFIER = "product_identifier"
    ORIGIN = "origin"
    WARRANTY = "warranty"
    TAX_TYPE = "tax_type"
    MINOR_PURCHASE_ALLOWED = "minor_purchase_allowed"
    SHIPPING_FEE_TYPE = "shipping_fee_type"
    SHIPPING_FEE = "shipping_fee"
    DELIVERY_DAYS = "delivery_days"
    RETURN_POLICY = "return_policy"
    PRODUCT_SUMMARY = "product_summary"
    DETAIL_HTML = "detail_html"
    OPTION_SUMMARY = "option_summary"
    SEARCH_KEYWORDS = "search_keywords"
    TAGS = "tags"
    MAIN_IMAGE = "main_image"
    EXTRA_IMAGES = "extra_images"
    SUPPLIER_NAME = "supplier_name"
    SUPPLY_COST = "supply_cost"


#: Attributes that never reach a channel draft. Supply cost and supplier name
#: are internal commercial facts, not published listing data.
INTERNAL_ONLY_ATTRIBUTES = frozenset(
    {ProductAttribute.SUPPLIER_NAME, ProductAttribute.SUPPLY_COST}
)

#: Supplier file column names, one per canonical attribute. The pilot intake
#: accepts exactly this header set so a malformed supplier file fails fast.
SUPPLIER_COLUMNS: tuple[str, ...] = (
    "상품명",
    "모델명",
    "브랜드",
    "제조사",
    "카테고리",
    "카테고리코드",
    "색상",
    "사이즈",
    "소재",
    "무게kg",
    "가로mm",
    "세로mm",
    "높이mm",
    "단위",
    "판매가",
    "정가",
    "재고수량",
    "최소주문수량",
    "품번",
    "원산지",
    "보증기간",
    "부가세구분",
    "미성년자구매",
    "배송비유형",
    "배송비",
    "발송예정일",
    "반품교환정책",
    "요약설명",
    "상세설명",
    "검색어",
    "태그",
    "대표이미지",
    "추가이미지",
    "공급사",
    "공급가",
)

COLUMN_TO_ATTRIBUTE: Mapping[str, ProductAttribute] = {
    "상품명": ProductAttribute.PRODUCT_NAME,
    "모델명": ProductAttribute.MODEL_NAME,
    "브랜드": ProductAttribute.BRAND,
    "제조사": ProductAttribute.MANUFACTURER,
    "카테고리": ProductAttribute.CATEGORY_PATH,
    "카테고리코드": ProductAttribute.CATEGORY_CODE,
    "색상": ProductAttribute.COLOR,
    "사이즈": ProductAttribute.SIZE,
    "소재": ProductAttribute.MATERIAL,
    "무게kg": ProductAttribute.WEIGHT_KG,
    "가로mm": ProductAttribute.WIDTH_MM,
    "세로mm": ProductAttribute.HEIGHT_MM,
    "높이mm": ProductAttribute.DEPTH_MM,
    "단위": ProductAttribute.UNIT,
    "판매가": ProductAttribute.SALE_PRICE,
    "정가": ProductAttribute.LIST_PRICE,
    "재고수량": ProductAttribute.STOCK_QUANTITY,
    "최소주문수량": ProductAttribute.MIN_ORDER_QUANTITY,
    "품번": ProductAttribute.PRODUCT_IDENTIFIER,
    "원산지": ProductAttribute.ORIGIN,
    "보증기간": ProductAttribute.WARRANTY,
    "부가세구분": ProductAttribute.TAX_TYPE,
    "미성년자구매": ProductAttribute.MINOR_PURCHASE_ALLOWED,
    "배송비유형": ProductAttribute.SHIPPING_FEE_TYPE,
    "배송비": ProductAttribute.SHIPPING_FEE,
    "발송예정일": ProductAttribute.DELIVERY_DAYS,
    "반품교환정책": ProductAttribute.RETURN_POLICY,
    "요약설명": ProductAttribute.PRODUCT_SUMMARY,
    "상세설명": ProductAttribute.DETAIL_HTML,
    "검색어": ProductAttribute.SEARCH_KEYWORDS,
    "태그": ProductAttribute.TAGS,
    "대표이미지": ProductAttribute.MAIN_IMAGE,
    "추가이미지": ProductAttribute.EXTRA_IMAGES,
    "공급사": ProductAttribute.SUPPLIER_NAME,
    "공급가": ProductAttribute.SUPPLY_COST,
}


class ChannelFieldKind(str, Enum):
    TEXT = "text"
    INT = "int"
    DECIMAL = "decimal"
    ENUM = "enum"
    HTML = "html"
    KEYWORD_LIST = "keyword_list"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class ChannelFieldSpec:
    """One registration-form field of one sales channel."""

    key: str
    label: str
    source: ProductAttribute | None
    required: bool = False
    max_chars: int | None = None
    kind: ChannelFieldKind = ChannelFieldKind.TEXT
    allowed_values: tuple[str, ...] = ()
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ChannelImagePolicy:
    min_pixels: int
    recommended_pixels: int
    max_images: int
    max_bytes: int
    allowed_extensions: tuple[str, ...]
    square_required: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class ChannelOptionPolicy:
    max_option_axes: int
    max_option_values_per_axis: int
    max_combinations: int
    option_name_max_chars: int
    option_value_max_chars: int
    note: str = ""


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    """A sales channel's registration form, as data."""

    channel_id: str
    display_name: str
    admin_surface: str
    fields: tuple[ChannelFieldSpec, ...]
    image_policy: ChannelImagePolicy
    option_policy: ChannelOptionPolicy
    source_urls: tuple[str, ...]
    source_checked_on: str

    def field(self, key: str) -> ChannelFieldSpec | None:
        for spec in self.fields:
            if spec.key == key:
                return spec
        return None


class ListingSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ListingIssue:
    """One concrete defect found while preparing a listing artifact."""

    channel_id: str
    target: str
    severity: ListingSeverity
    code: str
    message: str

    def safe_dict(self) -> dict[str, str]:
        return {
            "channel_id": self.channel_id,
            "target": self.target,
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ChannelDraft:
    """One channel's registration draft, ready to be typed into the console."""

    channel_id: str
    display_name: str
    admin_surface: str
    values: Mapping[str, str]
    issues: tuple[ListingIssue, ...]
    unresolved_field_count: int
    manual_field_count: int
    source_urls: tuple[str, ...]
    source_checked_on: str

    @property
    def error_issues(self) -> tuple[ListingIssue, ...]:
        return tuple(item for item in self.issues if item.severity is ListingSeverity.ERROR)

    @property
    def warning_issues(self) -> tuple[ListingIssue, ...]:
        return tuple(item for item in self.issues if item.severity is ListingSeverity.WARNING)

    @property
    def ready_for_entry(self) -> bool:
        """True when no blocking defect remains. It never means "publishable"."""

        return (
            not self.error_issues
            and self.unresolved_field_count == 0
            and self.manual_field_count == 0
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "display_name": self.display_name,
            "admin_surface": self.admin_surface,
            "values": dict(self.values),
            "issues": [item.safe_dict() for item in self.issues],
            "unresolved_field_count": self.unresolved_field_count,
            "manual_field_count": self.manual_field_count,
            "ready_for_entry": self.ready_for_entry,
            "source_urls": list(self.source_urls),
            "source_checked_on": self.source_checked_on,
        }


@dataclass(frozen=True, slots=True)
class ImageManifestEntry:
    role: str
    file_name: str
    width_px: int
    height_px: int
    byte_size: int
    alt_text: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "file_name": self.file_name,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "byte_size": self.byte_size,
            "alt_text": self.alt_text,
        }


@dataclass(frozen=True, slots=True)
class BrowserFillStep:
    """One bounded browser action in the channel console form."""

    order: int
    action: str
    target_label: str
    value_preview: str
    classification: str
    requires_human: bool
    rationale: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "action": self.action,
            "target_label": self.target_label,
            "value_preview": self.value_preview,
            "classification": self.classification,
            "requires_human": self.requires_human,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class BrowserFillPlan:
    """The bounded action plan for one channel console form."""

    channel_id: str
    display_name: str
    steps: tuple[BrowserFillStep, ...]
    human_steps: tuple[str, ...]

    @property
    def automatable_steps(self) -> tuple[BrowserFillStep, ...]:
        return tuple(step for step in self.steps if not step.requires_human)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "display_name": self.display_name,
            "steps": [step.safe_dict() for step in self.steps],
            "human_steps": list(self.human_steps),
            "automatable_step_count": len(self.automatable_steps),
            "human_step_count": len(self.human_steps),
        }


@dataclass(frozen=True, slots=True)
class ProductListingRecord:
    """One product's canonical attributes with per-field provenance."""

    product_id: str
    source_ref: str
    fields: Mapping[ProductAttribute, ExtractedField]

    def raw_value(self, attribute: ProductAttribute) -> str | None:
        field_value = self.fields.get(attribute)
        if field_value is None:
            return None
        return field_value.resolved_value

    def value(self, attribute: ProductAttribute) -> str | None:
        field_value = self.fields.get(attribute)
        if field_value is None:
            return None
        if field_value.review_status is FieldReviewStatus.UNREVIEWED:
            return field_value.raw_value
        return field_value.resolved_value

    @property
    def unresolved_field_count(self) -> int:
        """Fields a human still has to settle before a channel draft is usable.

        Internal commercial attributes are excluded: they never reach a channel
        form, so they are not an unresolved registration input.
        """

        return sum(
            1
            for attribute, item in self.fields.items()
            if attribute not in INTERNAL_ONLY_ATTRIBUTES
            and not item.trusted_business_value
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "source_ref": self.source_ref,
            "fields": {
                attribute.value: field_value.safe_dict()
                for attribute, field_value in sorted(
                    self.fields.items(), key=lambda item: item[0].value
                )
            },
            "unresolved_field_count": self.unresolved_field_count,
        }


def _clean_cell(value: str | None, column: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ContractError(f"supplier column {column} must be text")
    text = value.strip()
    if len(text) > MAX_SUPPLIER_CELL_CHARS:
        raise ContractError(
            f"supplier column {column} exceeds {MAX_SUPPLIER_CELL_CHARS} characters"
        )
    if _CONTROL_RE.search(text):
        raise ContractError(f"supplier column {column} contains control characters")
    if text.startswith(_FORMULA_PREFIXES):
        raise ContractError(f"supplier column {column} looks like a spreadsheet formula")
    return text


def parse_supplier_csv(text: str) -> tuple[dict[str, str], ...]:
    """Parse one supplier CSV into canonical rows.

    The header set must match :data:`SUPPLIER_COLUMNS` exactly. A supplier file
    that drifts from the agreed sheet is a real data defect, so the parse fails
    instead of silently dropping a column.
    """

    if not isinstance(text, str) or not text:
        raise ContractError("supplier CSV is empty")
    if len(text.encode("utf-8")) > MAX_SUPPLIER_FILE_BYTES:
        raise ContractError("supplier CSV exceeds the supported byte bound")
    if "\x00" in text:
        raise ContractError("supplier CSV contains a NUL byte")

    normalized = text[1:] if text.startswith("\ufeff") else text
    try:
        reader = csv.DictReader(io.StringIO(normalized), strict=True)
        headers = reader.fieldnames
        if headers is None:
            raise ContractError("supplier CSV header is missing")
        cleaned = tuple(item.strip() if isinstance(item, str) else "" for item in headers)
        if len(cleaned) != len(set(cleaned)):
            raise ContractError("supplier CSV headers must be unique")
        if set(cleaned) != set(SUPPLIER_COLUMNS) or len(cleaned) != len(SUPPLIER_COLUMNS):
            raise ContractError(
                "supplier CSV headers must exactly match the agreed supplier sheet"
            )
        reader.fieldnames = list(cleaned)

        rows: list[dict[str, str]] = []
        for row in reader:
            if None in row:
                raise ContractError("supplier CSV row has more columns than the header")
            if len(rows) >= MAX_SUPPLIER_ROWS:
                raise ContractError("supplier CSV row count exceeds the supported bound")
            rows.append(
                {column: _clean_cell(row.get(column), column) for column in cleaned}
            )
    except csv.Error as exc:
        raise ContractError("malformed supplier CSV input") from exc

    if not rows:
        raise ContractError("supplier CSV must contain at least one data row")
    return tuple(rows)


def _column_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index


def parse_supplier_xlsx(payload: bytes, *, name: str) -> tuple[dict[str, str], ...]:
    """Parse one supplier XLSX through the reviewed Core binary parser.

    The Core parser is the single binary-document authority, so this module
    does not add a second spreadsheet reader. Its bounded text projection
    (``[Sheet!A1] value``) is mapped back into a header row plus data rows.
    """

    from padiem_ai_core.document_normalization import (
        extract_binary_document,
    )

    document = extract_binary_document(
        name=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        payload=payload,
    )

    cells: dict[tuple[str, int], dict[int, str]] = {}
    sheet_order: list[str] = []
    for line in document.text.splitlines():
        match = _XLSX_CELL_RE.match(line.strip())
        if match is None:
            continue
        sheet = match.group("sheet")
        row_number = int(match.group("row"))
        column_index = _column_index(match.group("coord").rstrip(str(row_number)))
        value = match.group("value").strip()
        if not value:
            continue
        if sheet not in cells:
            cells[sheet] = {}
            sheet_order.append(sheet)
        cells[sheet].setdefault(row_number, {})[column_index] = value

    if not sheet_order:
        raise ContractError("supplier XLSX contains no readable cell values")

    sheet = sheet_order[0]
    rows_of_sheet = cells[sheet]
    header_row_number = min(rows_of_sheet)
    header_map = rows_of_sheet[header_row_number]
    header_by_index = dict(header_map)
    headers = [header_by_index.get(index, "") for index in sorted(header_by_index)]
    if set(headers) != set(SUPPLIER_COLUMNS) or len(headers) != len(SUPPLIER_COLUMNS):
        raise ContractError(
            "supplier XLSX headers must exactly match the agreed supplier sheet"
        )

    rows: list[dict[str, str]] = []
    for row_number in sorted(key for key in rows_of_sheet if key > header_row_number):
        values = rows_of_sheet[row_number]
        if not values:
            continue
        if len(rows) >= MAX_SUPPLIER_ROWS:
            raise ContractError("supplier XLSX row count exceeds the supported bound")
        record: dict[str, str] = {}
        for position, column_index in enumerate(sorted(header_by_index)):
            column = headers[position]
            record[column] = _clean_cell(values.get(column_index, ""), column)
        rows.append(record)
    if not rows:
        raise ContractError("supplier XLSX must contain at least one data row")
    return tuple(rows)


def _attribute_field(
    attribute: ProductAttribute,
    value: str,
    *,
    origin: ExtractionOrigin,
    locator: str,
    confidence: Decimal = Decimal("1"),
) -> ExtractedField:
    return ExtractedField(
        field_id=attribute.value,
        raw_value=value,
        confidence=confidence,
        origin=origin,
        source_locator=locator,
        review_status=FieldReviewStatus.UNREVIEWED,
    )


def build_candidate_record(
    row: Mapping[str, str],
    *,
    product_id: str,
    source_ref: str,
    locator_prefix: str,
) -> ProductListingRecord:
    """Turn one supplier row into a canonical record of unreviewed fields."""

    fields: dict[ProductAttribute, ExtractedField] = {}
    for column, attribute in COLUMN_TO_ATTRIBUTE.items():
        value = row.get(column, "")
        if not value:
            continue
        fields[attribute] = _attribute_field(
            attribute,
            value,
            origin=ExtractionOrigin.RULE,
            locator=f"{locator_prefix}:{column}",
        )
    option_summary = _option_summary(row, locator_prefix=locator_prefix)
    if option_summary:
        fields[ProductAttribute.OPTION_SUMMARY] = _attribute_field(
            ProductAttribute.OPTION_SUMMARY,
            option_summary,
            origin=ExtractionOrigin.RULE,
            locator=f"{locator_prefix}:option_summary",
        )
    return ProductListingRecord(
        product_id=product_id,
        source_ref=source_ref,
        fields=fields,
    )


def _option_summary(row: Mapping[str, str], *, locator_prefix: str) -> str:
    """Build the option-axis summary a channel option field needs."""

    parts: list[str] = []
    for column, axis in (("색상", "색상"), ("사이즈", "사이즈")):
        value = (row.get(column) or "").strip()
        if value:
            parts.append(f"{axis}={value}")
    return " / ".join(parts)


def merge_research_notes(
    record: ProductListingRecord,
    notes: Mapping[str, Any],
    *,
    locator_prefix: str = "research",
    confidence: Decimal = Decimal("0.7"),
) -> ProductListingRecord:
    """Merge researched product facts into a record as model-origin fields.

    A researched value never overwrites a supplier value for the same
    attribute: the supplier file stays the authority for commercial facts and
    the research result is recorded as a separate, reviewable origin.

    A note value is either the researched text, or a mapping carrying the text
    and the public source it was read from. The source is kept in the field
    locator so a reviewer can re-check the claim.
    """

    if len(notes) > MAX_RESEARCH_NOTES:
        raise ContractError("research note count exceeds the supported bound")
    merged = dict(record.fields)
    for raw_key, raw_value in notes.items():
        try:
            attribute = ProductAttribute(raw_key)
        except ValueError as exc:
            raise ContractError(f"unknown research attribute {raw_key!r}") from exc
        if attribute in INTERNAL_ONLY_ATTRIBUTES:
            raise ContractError(
                "research notes must not carry internal-only commercial attributes"
            )
        source = ""
        if isinstance(raw_value, Mapping):
            value_text = raw_value.get("value")
            source = str(raw_value.get("source", "") or "")
            if not isinstance(value_text, str):
                raise ContractError(
                    f"research note {raw_key} must carry a text value"
                )
        elif isinstance(raw_value, str):
            value_text = raw_value
        else:
            raise ContractError(f"research note {raw_key} must be text or a mapping")
        value = _clean_cell(value_text, f"research:{raw_key}")
        if not value:
            continue
        if attribute in merged:
            continue
        locator = f"{locator_prefix}:{raw_key}"
        if source:
            locator = f"{locator}#source={source}"
        merged[attribute] = _attribute_field(
            attribute,
            value,
            origin=ExtractionOrigin.MODEL,
            locator=locator,
            confidence=confidence,
        )
    return ProductListingRecord(
        product_id=record.product_id,
        source_ref=record.source_ref,
        fields=merged,
    )


def apply_review(
    record: ProductListingRecord,
    review: Mapping[str, Mapping[str, str]],
) -> tuple[ProductListingRecord, tuple[WorkflowTelemetryEvent, ...]]:
    """Apply a human review to a record and return the review telemetry.

    ``review`` maps a field id to ``{"status": "confirmed"|"corrected",
    "value": "<corrected text>"}``. A correction without a value is refused,
    because a silent correction is worse than an unresolved field.
    """

    if not isinstance(review, Mapping):
        raise ContractError("review must be a mapping")
    updated = dict(record.fields)
    attribute_by_field_id = {
        attribute.value: attribute for attribute in updated
    }
    events: list[WorkflowTelemetryEvent] = []
    for field_id, decision in review.items():
        attribute = attribute_by_field_id.get(field_id)
        if attribute is None:
            raise ContractError(f"review refers to an unknown field {field_id!r}")
        if not isinstance(decision, Mapping):
            raise ContractError("review decision must be a mapping")
        status = str(decision.get("status", "")).strip().lower()
        value = decision.get("value")
        current = updated[attribute]
        if status == "confirmed":
            if current.raw_value is None:
                raise ContractError(f"cannot confirm field {field_id} without a value")
            updated[attribute] = ExtractedField(
                field_id=field_id,
                raw_value=current.raw_value,
                confidence=current.confidence,
                origin=current.origin,
                source_locator=current.source_locator,
                review_status=FieldReviewStatus.CONFIRMED,
            )
            events.append(
                WorkflowTelemetryEvent(
                    event_id=f"review_confirmed_{field_id}",
                    workspace_id="pilot",
                    workflow_ref=record.product_id,
                    phase=PilotPhase.SHADOW,
                    kind=PilotTelemetryKind.EXTRACTION_FIELD_CONFIRMED,
                    occurred_at=datetime.now(timezone.utc),
                    evidence_ref=f"review:{record.product_id}:{field_id}",
                    subject_ref=field_id,
                )
            )
        elif status == "corrected":
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"corrected field {field_id} requires a value")
            updated[attribute] = ExtractedField(
                field_id=field_id,
                raw_value=current.raw_value,
                confidence=current.confidence,
                origin=current.origin,
                source_locator=current.source_locator,
                review_status=FieldReviewStatus.CORRECTED,
                corrected_value=_clean_cell(value, f"review:{field_id}"),
            )
            events.append(
                WorkflowTelemetryEvent(
                    event_id=f"review_corrected_{field_id}",
                    workspace_id="pilot",
                    workflow_ref=record.product_id,
                    phase=PilotPhase.SHADOW,
                    kind=PilotTelemetryKind.EXTRACTION_FIELD_CORRECTED,
                    occurred_at=datetime.now(timezone.utc),
                    evidence_ref=f"review:{record.product_id}:{field_id}",
                    subject_ref=field_id,
                )
            )
        else:
            raise ContractError(
                f"review status for {field_id} must be confirmed or corrected"
            )
    reviewed = ProductListingRecord(
        product_id=record.product_id,
        source_ref=record.source_ref,
        fields=updated,
    )
    return reviewed, tuple(events)


def _with_detail_html(
    record: ProductListingRecord,
    generated_html: str,
) -> ProductListingRecord:
    """Return the record with its channel detail description resolved.

    A supplier-supplied description keeps its own text and stays the operator's
    to review. When the supplier file carries none, the generated description
    becomes the draft's detail value, so no channel draft ships an empty
    description field.

    A generated description that changes after a human already reviewed it
    loses that review, because the reviewed text is no longer the text that
    would be published.
    """

    fields = dict(record.fields)
    current_field = fields.get(ProductAttribute.DETAIL_HTML)
    current = current_field.raw_value if current_field is not None else None
    if current is None or not current.strip():
        fields[ProductAttribute.DETAIL_HTML] = _attribute_field(
            ProductAttribute.DETAIL_HTML,
            generated_html,
            origin=ExtractionOrigin.RULE,
            locator="generated:detail_html",
        )
        return ProductListingRecord(
            product_id=record.product_id,
            source_ref=record.source_ref,
            fields=fields,
        )
    if current_field is not None and current_field.source_locator.startswith(
        "generated:detail_html"
    ):
        if current != generated_html:
            fields[ProductAttribute.DETAIL_HTML] = _attribute_field(
                ProductAttribute.DETAIL_HTML,
                generated_html,
                origin=ExtractionOrigin.RULE,
                locator="generated:detail_html",
            )
    return ProductListingRecord(
        product_id=record.product_id,
        source_ref=record.source_ref,
        fields=fields,
    )


def _decimal_value(raw: str) -> Decimal | None:
    try:
        parsed = Decimal(raw.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _format_decimal(raw: str) -> str:
    parsed = _decimal_value(raw)
    if parsed is None:
        return raw
    if parsed == parsed.to_integral_value():
        return str(int(parsed))
    return format(parsed.normalize(), "f")


def _format_field(spec: ChannelFieldSpec, raw: str) -> str:
    if spec.kind in (ChannelFieldKind.INT, ChannelFieldKind.DECIMAL):
        return _format_decimal(raw)
    if spec.kind is ChannelFieldKind.KEYWORD_LIST:
        parts = [item.strip() for item in raw.split(",") if item.strip()]
        return ", ".join(parts[:MAX_KEYWORDS])
    if spec.kind is ChannelFieldKind.IMAGE:
        return _image_file_list(raw)
    return raw


def _image_file_list(raw: str) -> str:
    """Render a manifest string as the file names a console file picker needs."""

    names: list[str] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        names.append(item.split("|", 1)[0].strip())
    return ", ".join(names)


def project_channel_draft(
    record: ProductListingRecord,
    profile: ChannelProfile,
    *,
    images: Sequence[ImageManifestEntry] | None = None,
) -> ChannelDraft:
    """Project one canonical record onto one channel's registration form.

    ``images`` is the evaluated image manifest. ``None`` means the image check
    was not run; an empty sequence means it ran and found no image.
    """

    values: dict[str, str] = {}
    issues: list[ListingIssue] = []
    unresolved = 0
    manual_fields = 0
    unreviewed_targets: list[str] = []

    for spec in profile.fields:
        if spec.source is None:
            values[spec.key] = ""
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=spec.key,
                    severity=ListingSeverity.WARNING,
                    code="manual_channel_field",
                    message=(
                        f"{spec.label} 항목은 채널별 필수 확인이 필요합니다. {spec.note}"
                    ).strip(),
                )
            )
            manual_fields += 1
            continue

        field_value = record.fields.get(spec.source)
        raw = record.value(spec.source)
        if raw is None or not raw.strip():
            if spec.required:
                issues.append(
                    ListingIssue(
                        channel_id=profile.channel_id,
                        target=spec.key,
                        severity=ListingSeverity.ERROR,
                        code="missing_required_field",
                        message=f"{spec.label} 값이 없어 등록할 수 없습니다.",
                    )
                )
                unresolved += 1
            values[spec.key] = ""
            continue

        if field_value is not None and not field_value.trusted_business_value:
            unresolved += 1
            unreviewed_targets.append(spec.label)

        formatted = _format_field(spec, raw)
        if spec.max_chars is not None and len(formatted) > spec.max_chars:
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=spec.key,
                    severity=ListingSeverity.ERROR,
                    code="value_too_long",
                    message=(
                        f"{spec.label} 값이 {len(formatted)}자로 채널 제한 "
                        f"{spec.max_chars}자를 초과합니다."
                    ),
                )
            )
        if spec.kind is ChannelFieldKind.ENUM and spec.allowed_values:
            if formatted not in spec.allowed_values:
                issues.append(
                    ListingIssue(
                        channel_id=profile.channel_id,
                        target=spec.key,
                        severity=ListingSeverity.ERROR,
                        code="value_not_allowed",
                        message=(
                            f"{spec.label} 값 '{formatted}' 는 허용 목록에 없습니다: "
                            f"{'/'.join(spec.allowed_values)}"
                        ),
                    )
                )
        if spec.kind in (ChannelFieldKind.INT, ChannelFieldKind.DECIMAL):
            parsed = _decimal_value(raw)
            if parsed is None:
                issues.append(
                    ListingIssue(
                        channel_id=profile.channel_id,
                        target=spec.key,
                        severity=ListingSeverity.ERROR,
                        code="value_not_numeric",
                        message=f"{spec.label} 값이 숫자가 아닙니다.",
                    )
                )
            else:
                if spec.minimum is not None and parsed < spec.minimum:
                    issues.append(
                        ListingIssue(
                            channel_id=profile.channel_id,
                            target=spec.key,
                            severity=ListingSeverity.ERROR,
                            code="value_below_minimum",
                            message=(
                                f"{spec.label} 값이 최소 {spec.minimum} 미만입니다."
                            ),
                        )
                    )
                if spec.maximum is not None and parsed > spec.maximum:
                    issues.append(
                        ListingIssue(
                            channel_id=profile.channel_id,
                            target=spec.key,
                            severity=ListingSeverity.ERROR,
                            code="value_above_maximum",
                            message=(
                                f"{spec.label} 값이 최대 {spec.maximum}을 초과합니다."
                            ),
                        )
                    )
        values[spec.key] = formatted

    if unreviewed_targets:
        issues.append(
            ListingIssue(
                channel_id=profile.channel_id,
                target="*",
                severity=ListingSeverity.WARNING,
                code="unreviewed_fields",
                message=(
                    f"검수 전 필드 {len(unreviewed_targets)}건: "
                    f"{', '.join(unreviewed_targets)}. 확인 후 등록하세요."
                ),
            )
        )

    if images is not None:
        issues.extend(check_image_policy(images, profile))

    return ChannelDraft(
        channel_id=profile.channel_id,
        display_name=profile.display_name,
        admin_surface=profile.admin_surface,
        values=values,
        issues=tuple(issues),
        unresolved_field_count=unresolved,
        manual_field_count=manual_fields,
        source_urls=profile.source_urls,
        source_checked_on=profile.source_checked_on,
    )


_DETAIL_SPEC_ROWS: tuple[tuple[ProductAttribute, str], ...] = (
    (ProductAttribute.MODEL_NAME, "모델명"),
    (ProductAttribute.BRAND, "브랜드"),
    (ProductAttribute.MANUFACTURER, "제조사"),
    (ProductAttribute.CATEGORY_PATH, "카테고리"),
    (ProductAttribute.PRODUCT_IDENTIFIER, "품번"),
    (ProductAttribute.COLOR, "색상"),
    (ProductAttribute.SIZE, "사이즈"),
    (ProductAttribute.MATERIAL, "소재"),
    (ProductAttribute.WEIGHT_KG, "무게(kg)"),
    (ProductAttribute.WIDTH_MM, "가로(mm)"),
    (ProductAttribute.HEIGHT_MM, "세로(mm)"),
    (ProductAttribute.DEPTH_MM, "높이(mm)"),
    (ProductAttribute.UNIT, "단위"),
    (ProductAttribute.ORIGIN, "원산지"),
    (ProductAttribute.WARRANTY, "보증기간"),
    (ProductAttribute.SALE_PRICE, "판매가"),
    (ProductAttribute.SHIPPING_FEE_TYPE, "배송비"),
    (ProductAttribute.SHIPPING_FEE, "배송비 금액"),
    (ProductAttribute.DELIVERY_DAYS, "발송예정일"),
    (ProductAttribute.RETURN_POLICY, "반품/교환 정책"),
)


def build_detail_html(record: ProductListingRecord) -> str:
    """Build the detail-page description HTML from the canonical record.

    The generated markup is a plain table plus a summary paragraph. It carries
    no tracking markup, no external script and no script tag, because channel
    consoles reject those and because a listing page must not execute code.
    """

    summary = record.value(ProductAttribute.PRODUCT_SUMMARY) or ""
    name = record.value(ProductAttribute.PRODUCT_NAME) or ""
    rows: list[str] = []
    for attribute, label in _DETAIL_SPEC_ROWS:
        value = record.value(attribute)
        if value is None or not str(value).strip():
            continue
        rows.append(
            "<tr><th scope=\"row\">"
            f"{label}</th><td>{_escape_html(str(value))}</td></tr>"
        )
    spec_table = (
        '<table border="1" cellspacing="0" cellpadding="6">'
        "<caption>상품 주요 정보</caption>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )
    intro = (
        f"<p>{_escape_html(str(summary))}</p>" if summary else ""
    )
    heading = f"<h2>{_escape_html(str(name))}</h2>" if name else ""
    return f'<div class="product-detail">{heading}{intro}{spec_table}</div>'


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def parse_image_manifest(raw: str) -> tuple[ImageManifestEntry, ...]:
    """Parse a supplier image manifest written as ``name|widthxheight|bytes|alt``."""

    entries: list[ImageManifestEntry] = []
    for index, part in enumerate(raw.split(",")):
        item = part.strip()
        if not item:
            continue
        pieces = item.split("|")
        if len(pieces) < 4:
            raise ContractError(
                "image manifest entry must be name|widthxheight|bytes|alt"
            )
        name, size, byte_size, alt = pieces[0], pieces[1], pieces[2], pieces[3]
        dimensions = size.lower().split("x")
        if len(dimensions) != 2:
            raise ContractError("image manifest size must be WIDTHxHEIGHT")
        try:
            width = int(dimensions[0])
            height = int(dimensions[1])
            size_bytes = int(byte_size)
        except ValueError as exc:
            raise ContractError("image manifest size and byte count must be numeric") from exc
        entries.append(
            ImageManifestEntry(
                role="main" if index == 0 else "extra",
                file_name=name.strip(),
                width_px=width,
                height_px=height,
                byte_size=size_bytes,
                alt_text=alt.strip()[:MAX_IMAGE_ALT_CHARS],
            )
        )
    return tuple(entries)


def check_image_policy(
    entries: Sequence[ImageManifestEntry],
    profile: ChannelProfile,
) -> tuple[ListingIssue, ...]:
    """Check one image manifest against one channel's image policy."""

    issues: list[ListingIssue] = []
    policy = profile.image_policy
    if not entries:
        issues.append(
            ListingIssue(
                channel_id=profile.channel_id,
                target="images",
                severity=ListingSeverity.ERROR,
                code="missing_main_image",
                message="대표이미지가 없어 등록 준비가 완료되지 않았습니다.",
            )
        )
        return tuple(issues)
    if len(entries) > policy.max_images:
        issues.append(
            ListingIssue(
                channel_id=profile.channel_id,
                target="images",
                severity=ListingSeverity.ERROR,
                code="too_many_images",
                message=(
                    f"이미지 {len(entries)}개가 채널 제한 {policy.max_images}개를 "
                    "초과합니다."
                ),
            )
        )
    for entry in entries:
        target = entry.file_name
        extension = "." + entry.file_name.rsplit(".", 1)[-1].lower() if "." in entry.file_name else ""
        if extension not in policy.allowed_extensions:
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=target,
                    severity=ListingSeverity.ERROR,
                    code="image_format_not_allowed",
                    message=(
                        f"{target} 확장자 {extension or '(없음)'}는 채널 허용 형식"
                        f"({'/'.join(policy.allowed_extensions)})이 아닙니다."
                    ),
                )
            )
        if entry.byte_size > policy.max_bytes:
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=target,
                    severity=ListingSeverity.ERROR,
                    code="image_too_large",
                    message=(
                        f"{target} 용량 {entry.byte_size}바이트가 채널 제한 "
                        f"{policy.max_bytes}바이트를 초과합니다."
                    ),
                )
            )
        shortest = min(entry.width_px, entry.height_px)
        if shortest < policy.min_pixels:
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=target,
                    severity=ListingSeverity.ERROR,
                    code="image_too_small",
                    message=(
                        f"{target} 해상도 {entry.width_px}x{entry.height_px}가 채널 최소 "
                        f"{policy.min_pixels}px 미만입니다."
                    ),
                )
            )
        elif shortest < policy.recommended_pixels:
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=target,
                    severity=ListingSeverity.WARNING,
                    code="image_below_recommended",
                    message=(
                        f"{target} 해상도 {entry.width_px}x{entry.height_px}가 채널 권장 "
                        f"{policy.recommended_pixels}px 미만입니다."
                    ),
                )
            )
        if policy.square_required and entry.width_px != entry.height_px:
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=target,
                    severity=ListingSeverity.ERROR,
                    code="image_not_square",
                    message=f"{target} 정사각형 이미지가 필요합니다.",
                )
            )
        if not entry.alt_text:
            issues.append(
                ListingIssue(
                    channel_id=profile.channel_id,
                    target=target,
                    severity=ListingSeverity.WARNING,
                    code="image_alt_missing",
                    message=f"{target} 대체 텍스트를 입력하세요.",
                )
            )
    return tuple(issues)


def build_browser_fill_plan(
    draft: ChannelDraft,
    profile: ChannelProfile,
    *,
    max_steps: int = 40,
) -> BrowserFillPlan:
    """Build the bounded browser action plan for one channel console form.

    The plan uses only the actions the product already classifies. An action
    that the product classifies as step-up or prohibited stays a named human
    step, because the bounded lease cannot execute it.
    """

    steps: list[BrowserFillStep] = []
    human_steps: list[str] = []
    order = 0
    for spec in profile.fields:
        value = draft.values.get(spec.key, "")
        if spec.source is None:
            order += 1
            steps.append(
                BrowserFillStep(
                    order=order,
                    action="type",
                    target_label=spec.label,
                    value_preview="",
                    classification=classify_browser_control_action("type"),
                    requires_human=True,
                    rationale=(
                        "채널 전용 항목이라 표준 속성에서 채울 수 없습니다. "
                        "사람이 채널 규칙에 따라 직접 입력합니다."
                    ),
                )
            )
            human_steps.append(f"{spec.label} 직접 입력")
            continue
        if not value:
            continue
        if spec.kind is ChannelFieldKind.IMAGE:
            classification = classify_browser_control_action("upload")
            order += 1
            steps.append(
                BrowserFillStep(
                    order=order,
                    action="upload",
                    target_label=spec.label,
                    value_preview=f"{len(value.split(','))}개 파일",
                    classification=classification,
                    requires_human=True,
                    rationale="이미지 업로드는 단계승인 액션이므로 사람이 올립니다.",
                )
            )
            human_steps.append(f"{spec.label} 이미지 업로드")
            continue
        classification = classify_browser_control_action("type")
        order += 1
        steps.append(
            BrowserFillStep(
                order=order,
                action="type",
                target_label=spec.label,
                value_preview=value[:120],
                classification=classification,
                requires_human=False,
                rationale="lease 허용 입력 액션입니다.",
            )
        )
        if order >= max_steps:
            break

    order += 1
    submit_classification = classify_browser_control_action("submit")
    steps.append(
        BrowserFillStep(
            order=order,
            action="submit",
            target_label="상품 등록 저장/판매요청",
            value_preview="",
            classification=submit_classification,
            requires_human=True,
            rationale="저장·판매요청은 단계승인 액션이므로 사람이 실행합니다.",
        )
    )
    human_steps.append("상품 등록 저장 및 판매요청")

    return BrowserFillPlan(
        channel_id=profile.channel_id,
        display_name=profile.display_name,
        steps=tuple(steps),
        human_steps=tuple(human_steps),
    )


def listing_metric_definitions() -> tuple[MetricDefinition, ...]:
    """Listing-specific labels for the shared pilot metric keys.

    The metric keys come from the shared telemetry bridge, so the measurement
    contract stays single-sourced. The labels carry the listing meaning.
    """

    return (
        MetricDefinition(
            "request_to_rfq_minutes",
            1,
            "상품 자료 수신 → 조사·정규화 완료(분)",
            MetricUnit.MINUTES,
            MetricDirection.LOWER_IS_BETTER,
            "공급처 자료를 받은 시점부터 상품정보 조사와 정규화가 끝난 시점까지의 실측 시간",
        ),
        MetricDefinition(
            "request_to_po_minutes",
            1,
            "상품 자료 수신 → 판매채널 등록 초안 완료(분)",
            MetricUnit.MINUTES,
            MetricDirection.LOWER_IS_BETTER,
            "공급처 자료를 받은 시점부터 판매채널별 등록 초안과 검수표가 준비된 시점까지의 실측 시간",
        ),
        MetricDefinition(
            "manual_reentry_count",
            1,
            "수작업 재입력 횟수",
            MetricUnit.COUNT,
            MetricDirection.LOWER_IS_BETTER,
            "사람이 같은 값을 다시 입력한 횟수",
        ),
        MetricDefinition(
            "supplier_response_minutes",
            1,
            "공급처 응답 시간(분)",
            MetricUnit.MINUTES,
            MetricDirection.LOWER_IS_BETTER,
            "공급처에 자료 요청을 보낸 시점부터 자료를 받은 시점까지의 실측 시간",
        ),
        MetricDefinition(
            "extraction_correction_rate",
            1,
            "추출 오류 정정률(%)",
            MetricUnit.PERCENT,
            MetricDirection.LOWER_IS_BETTER,
            "검수 대상 필드 중 사람이 바로잡은 필드의 비율",
        ),
        MetricDefinition(
            "automation_retry_count",
            1,
            "자동화 재시도 횟수",
            MetricUnit.COUNT,
            MetricDirection.LOWER_IS_BETTER,
            "자동 처리에서 재시도한 횟수",
        ),
        MetricDefinition(
            "owner_intervention_count",
            1,
            "사람 개입 횟수",
            MetricUnit.COUNT,
            MetricDirection.LOWER_IS_BETTER,
            "사람이 중간에 결정하거나 개입한 횟수",
        ),
    )


@dataclass(frozen=True, slots=True)
class ListingMeasurement:
    """The measured work log of one product-listing pilot run."""

    product_id: str
    milestone_minutes: Mapping[str, str]
    counts: Mapping[str, str]
    correction_rate: str | None
    derived_metric_keys: tuple[str, ...]
    baseline_estimated_minutes: str | None
    baseline_is_estimated: bool
    measured_comparison_available: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "milestone_minutes": dict(self.milestone_minutes),
            "counts": dict(self.counts),
            "correction_rate": self.correction_rate,
            "derived_metric_keys": list(self.derived_metric_keys),
            "baseline_estimated_minutes": self.baseline_estimated_minutes,
            "baseline_is_estimated": self.baseline_is_estimated,
            "measured_comparison_available": self.measured_comparison_available,
            "note": (
                "기준선은 추정치일 수 있으며, 추정치는 측정된 절감률로 사용하지 않습니다."
            ),
        }


@dataclass(frozen=True, slots=True)
class ProductListingPilotResult:
    """Everything one pilot run produced."""

    record: ProductListingRecord
    drafts: tuple[ChannelDraft, ...]
    image_manifest: tuple[ImageManifestEntry, ...]
    image_issues: tuple[ListingIssue, ...]
    description_html: str
    fill_plans: tuple[BrowserFillPlan, ...]
    measurement: ListingMeasurement
    review_checklist: tuple[str, ...]
    follow_ups: tuple[str, ...]
    artifacts: Mapping[str, str]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.safe_dict(),
            "drafts": [draft.safe_dict() for draft in self.drafts],
            "image_manifest": [entry.safe_dict() for entry in self.image_manifest],
            "image_issues": [issue.safe_dict() for issue in self.image_issues],
            "description_html": self.description_html,
            "fill_plans": [plan.safe_dict() for plan in self.fill_plans],
            "measurement": self.measurement.safe_dict(),
            "review_checklist": list(self.review_checklist),
            "follow_ups": list(self.follow_ups),
            "artifacts": dict(self.artifacts),
        }


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def run_product_listing_pilot(
    *,
    supplier_rows: Sequence[Mapping[str, str]],
    research_notes: Mapping[str, str],
    profiles: Sequence[ChannelProfile],
    reviews: Sequence[Mapping[str, Mapping[str, str]]] = (),
    product_id: str = "pilot-product-001",
    source_ref: str = "supplier-file",
    baseline_manual_minutes: Decimal | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ProductListingPilotResult:
    """Run the whole pilot for one product and return every produced artifact.

    ``clock`` is injectable so a test can produce a deterministic work log. The
    default clock is the real UTC wall clock.
    """

    if not supplier_rows:
        raise ContractError("product listing pilot requires at least one supplier row")
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)  # noqa: E731

    started_at = clock()
    telemetry: list[WorkflowTelemetryEvent] = []

    candidate = build_candidate_record(
        supplier_rows[0],
        product_id=product_id,
        source_ref=source_ref,
        locator_prefix="supplier:row1",
    )
    telemetry.append(
        WorkflowTelemetryEvent(
            event_id="intake_received",
            workspace_id="pilot",
            workflow_ref=product_id,
            phase=PilotPhase.SHADOW,
            kind=PilotTelemetryKind.REQUEST_INGESTED,
            occurred_at=started_at,
            evidence_ref=f"supplier:{source_ref}",
        )
    )

    researched = merge_research_notes(candidate, research_notes)
    research_done_at = clock()
    telemetry.append(
        WorkflowTelemetryEvent(
            event_id="research_normalized",
            workspace_id="pilot",
            workflow_ref=product_id,
            phase=PilotPhase.SHADOW,
            kind=PilotTelemetryKind.RFQ_READY,
            occurred_at=research_done_at,
            evidence_ref=f"research:{product_id}",
        )
    )

    record = researched

    description_html = build_detail_html(record)
    record = _with_detail_html(record, description_html)

    for review_round in reviews:
        record, review_events = apply_review(record, review_round)
        telemetry.extend(review_events)
        regenerated = build_detail_html(record)
        if regenerated != description_html:
            description_html = regenerated
            record = _with_detail_html(record, description_html)

    manifest_raw = ",".join(
        part
        for part in (
            record.value(ProductAttribute.MAIN_IMAGE) or "",
            record.value(ProductAttribute.EXTRA_IMAGES) or "",
        )
        if part
    )
    image_manifest = parse_image_manifest(manifest_raw)

    drafts = tuple(
        project_channel_draft(record, profile, images=image_manifest)
        for profile in profiles
    )
    fill_plans = tuple(
        build_browser_fill_plan(draft, profile)
        for draft, profile in zip(drafts, profiles)
    )

    image_issues: list[ListingIssue] = []
    for profile in profiles:
        image_issues.extend(check_image_policy(image_manifest, profile))

    draft_done_at = clock()
    telemetry.append(
        WorkflowTelemetryEvent(
            event_id="listing_draft_ready",
            workspace_id="pilot",
            workflow_ref=product_id,
            phase=PilotPhase.SHADOW,
            kind=PilotTelemetryKind.PO_READY,
            occurred_at=draft_done_at,
            evidence_ref=f"draft:{product_id}",
        )
    )

    checklist = _review_checklist(record, drafts)
    follow_ups = _follow_ups(drafts, image_issues, record)

    completed_at = clock()
    telemetry.append(
        WorkflowTelemetryEvent(
            event_id="listing_workflow_completed",
            workspace_id="pilot",
            workflow_ref=product_id,
            phase=PilotPhase.SHADOW,
            kind=PilotTelemetryKind.WORKFLOW_COMPLETED,
            occurred_at=completed_at,
            evidence_ref=f"pilot:{product_id}",
        )
    )

    bridge = PilotMeasurementBridge()
    for event in telemetry:
        bridge.add(event)
    derived = bridge.derive(workspace_id="pilot", workflow_ref=product_id)

    engine = PilotKpiEngine(listing_metric_definitions())
    for item in derived:
        engine.add(item.observation)
    if baseline_manual_minutes is not None:
        engine.add(
            PilotObservation(
                observation_id=f"baseline_manual_{product_id}",
                workspace_id="pilot",
                phase=PilotPhase.BASELINE,
                metric_key="request_to_po_minutes",
                metric_definition_version=1,
                value=baseline_manual_minutes,
                observed_at=started_at,
                evidence_ref=f"baseline:{product_id}",
                quality=EvidenceQuality.ESTIMATED,
                workflow_ref=product_id,
            )
        )

    summary = engine.summarize(
        workspace_id="pilot",
        metric_key="request_to_po_minutes",
        current_phases=(PilotPhase.SHADOW,),
    )

    milestones = {
        "intake_to_research_minutes": _minutes_between(started_at, research_done_at),
        "intake_to_draft_minutes": _minutes_between(started_at, draft_done_at),
        "total_minutes": _minutes_between(started_at, completed_at),
    }
    derived_by_key = {item.observation.metric_key: item.observation for item in derived}
    counts = {
        key: format(derived_by_key[key].value, "f")
        for key in (
            "manual_reentry_count",
            "automation_retry_count",
            "owner_intervention_count",
        )
        if key in derived_by_key
    }
    correction_rate: str | None = None
    for item in derived:
        if item.observation.metric_key == "extraction_correction_rate":
            correction_rate = format(item.observation.value, "f")

    measurement = ListingMeasurement(
        product_id=product_id,
        milestone_minutes=milestones,
        counts=counts,
        correction_rate=correction_rate,
        derived_metric_keys=tuple(
            sorted({item.observation.metric_key for item in derived})
        ),
        baseline_estimated_minutes=(
            None
            if baseline_manual_minutes is None
            else format(baseline_manual_minutes, "f")
        ),
        baseline_is_estimated=baseline_manual_minutes is not None,
        measured_comparison_available=summary.measured_comparison_available,
    )

    artifacts = {
        "record_sha256": _digest(
            repr(sorted(record.safe_dict()["fields"].items())).encode("utf-8")
        ),
        "channel_draft_count": str(len(drafts)),
        "ready_for_entry_channels": ",".join(
            draft.channel_id for draft in drafts if draft.ready_for_entry
        )
        or "(없음)",
        "automatable_step_total": str(
            sum(len(plan.automatable_steps) for plan in fill_plans)
        ),
        "human_step_total": str(sum(len(plan.human_steps) for plan in fill_plans)),
    }

    return ProductListingPilotResult(
        record=record,
        drafts=drafts,
        image_manifest=image_manifest,
        image_issues=tuple(image_issues),
        description_html=description_html,
        fill_plans=fill_plans,
        measurement=measurement,
        review_checklist=checklist,
        follow_ups=follow_ups,
        artifacts=artifacts,
    )


def _minutes_between(start: datetime, end: datetime) -> str:
    delta = end - start
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    return format(Decimal(micros) / Decimal(60_000_000), "f")


def _review_checklist(
    record: ProductListingRecord,
    drafts: Sequence[ChannelDraft],
) -> tuple[str, ...]:
    items = [
        "공급처 자료의 상품명·모델명·품번이 실제 제품과 일치하는지 확인",
        "판매가와 정가가 가격 정책에 맞는지 확인",
        "카테고리가 실제 노출 카테고리와 일치하는지 확인",
        "상세설명에 표시 이미지와 대체 텍스트가 포함되었는지 확인",
        "배송비·발송예정일·반품 정책이 운영 정책과 일치하는지 확인",
        "이미지 규격(분해능·용량·형식)이 채널 기준을 충족하는지 확인",
        "검수 전 필드 목록을 모두 확인",
    ]
    unresolved = record.unresolved_field_count
    if unresolved:
        items.append(f"검수 전 필드 {unresolved}건을 확정하거나 수정")
    for draft in drafts:
        errors = len(draft.error_issues)
        if errors:
            items.append(
                f"{draft.display_name} 차단 항목 {errors}건을 해결"
            )
        if draft.manual_field_count:
            items.append(
                f"{draft.display_name} 채널 전용 항목 {draft.manual_field_count}건을 직접 입력"
            )
    return tuple(items)


def _follow_ups(
    drafts: Sequence[ChannelDraft],
    image_issues: Sequence[ListingIssue],
    record: ProductListingRecord,
) -> tuple[str, ...]:
    follow_ups: list[str] = []
    for draft in drafts:
        for issue in draft.error_issues:
            follow_ups.append(
                f"[{draft.display_name}] {issue.target}: {issue.message}"
            )
    if record.unresolved_field_count:
        follow_ups.append(
            f"검수 전 필드 {record.unresolved_field_count}건을 사람이 확정해야 합니다."
        )
    return tuple(dict.fromkeys(follow_ups))


__all__ = [
    "BrowserFillPlan",
    "BrowserFillStep",
    "ChannelDraft",
    "ChannelFieldKind",
    "ChannelFieldSpec",
    "ChannelImagePolicy",
    "ChannelOptionPolicy",
    "ChannelProfile",
    "COLUMN_TO_ATTRIBUTE",
    "ImageManifestEntry",
    "INTERNAL_ONLY_ATTRIBUTES",
    "ListingIssue",
    "ListingMeasurement",
    "ListingSeverity",
    "ProductAttribute",
    "ProductListingPilotResult",
    "ProductListingRecord",
    "SUPPLIER_COLUMNS",
    "apply_review",
    "build_candidate_record",
    "build_browser_fill_plan",
    "build_detail_html",
    "check_image_policy",
    "listing_metric_definitions",
    "merge_research_notes",
    "parse_image_manifest",
    "parse_supplier_csv",
    "parse_supplier_xlsx",
    "project_channel_draft",
    "run_product_listing_pilot",
]
