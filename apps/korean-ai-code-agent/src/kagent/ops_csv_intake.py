from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO
import re

from .contracts import ContractError
from .ops_intake import (
    CommercialRequestIntakeCandidate,
    ExtractedField,
    ExtractionOrigin,
    FieldReviewStatus,
    IntakeLineCandidate,
    IntakeSource,
    IntakeSourceKind,
)


CSV_HEADERS = (
    "title",
    "requested_delivery_date",
    "line_id",
    "description",
    "quantity",
    "unit",
)
MAX_CSV_CHARS = 2_000_000
MAX_CSV_ROWS = 200
MAX_CELL_CHARS = 4000
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _cell(value: str | None, field_name: str, *, allow_empty: bool = False) -> str:
    if value is None or not isinstance(value, str):
        raise ContractError(f"CSV {field_name} is missing")
    value = value.strip()
    if not value and not allow_empty:
        raise ContractError(f"CSV {field_name} is required")
    if len(value) > MAX_CELL_CHARS:
        raise ContractError(f"CSV {field_name} exceeds {MAX_CELL_CHARS} characters")
    if _CONTROL_RE.search(value):
        raise ContractError(f"CSV {field_name} contains control characters")
    return value


def _text_cell(value: str | None, field_name: str, *, allow_empty: bool = False) -> str:
    result = _cell(value, field_name, allow_empty=allow_empty)
    if result and result.startswith(_FORMULA_PREFIXES):
        raise ContractError(f"CSV {field_name} looks like a spreadsheet formula")
    return result


def _quantity_cell(value: str | None) -> str:
    result = _cell(value, "quantity")
    if result.startswith(("=", "+", "@")):
        raise ContractError("CSV quantity looks like a spreadsheet formula")
    try:
        parsed = Decimal(result)
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("CSV quantity must be decimal-compatible") from exc
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("1000000000"):
        raise ContractError("CSV quantity must be finite, positive and bounded")
    if -parsed.as_tuple().exponent > 6:
        raise ContractError("CSV quantity supports at most 6 decimal places")
    return result


def _field(field_id: str, raw_value: str, *, locator: str) -> ExtractedField:
    return ExtractedField(
        field_id=field_id,
        raw_value=raw_value,
        confidence=Decimal("1"),
        origin=ExtractionOrigin.RULE,
        source_locator=locator,
        review_status=FieldReviewStatus.UNREVIEWED,
    )


@dataclass(frozen=True, slots=True)
class StrictCsvIntakeResult:
    candidate: CommercialRequestIntakeCandidate
    physical_line_count: int
    data_row_count: int

    @property
    def trusted_business_data_created(self) -> bool:
        return False


class StrictCsvCommercialRequestAdapter:
    """Parse one bounded CSV into an unreviewed intake candidate.

    Parsing certainty is not business trust. Every parsed field remains
    UNREVIEWED and the adapter never binds a customer identity.
    """

    def parse(
        self,
        *,
        source: IntakeSource,
        text: str,
        candidate_id: str,
        version: int = 1,
    ) -> StrictCsvIntakeResult:
        if not isinstance(source, IntakeSource):
            raise ContractError("source must be IntakeSource")
        if source.kind is not IntakeSourceKind.CSV:
            raise ContractError("strict CSV adapter requires IntakeSourceKind.CSV")
        if source.attachment is None or source.attachment.mime_type != "text/csv":
            raise ContractError("CSV intake source must use text/csv attachment metadata")
        if not isinstance(text, str):
            raise ContractError("CSV input must be decoded UTF-8 text")
        if len(text) == 0 or len(text) > MAX_CSV_CHARS:
            raise ContractError("CSV input is empty or exceeds the supported bound")
        if "\x00" in text:
            raise ContractError("CSV input contains NUL byte")

        normalized = text[1:] if text.startswith("\ufeff") else text
        try:
            reader = csv.DictReader(StringIO(normalized), strict=True)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise ContractError("CSV header is missing")
            headers = tuple(name.strip() if isinstance(name, str) else "" for name in fieldnames)
            if len(headers) != len(set(headers)):
                raise ContractError("CSV headers must be unique")
            if set(headers) != set(CSV_HEADERS) or len(headers) != len(CSV_HEADERS):
                raise ContractError("CSV headers must exactly match the supported schema")
            reader.fieldnames = list(headers)

            rows: list[tuple[int, dict[str, str | None]]] = []
            for row in reader:
                if None in row:
                    raise ContractError("CSV row contains more columns than the header")
                if len(rows) >= MAX_CSV_ROWS:
                    raise ContractError(f"CSV row count exceeds {MAX_CSV_ROWS}")
                rows.append((reader.line_num, row))
        except csv.Error as exc:
            raise ContractError("malformed CSV input") from exc

        if not rows:
            raise ContractError("CSV must contain at least one data row")

        first_line, first = rows[0]
        title = _text_cell(first.get("title"), "title")
        delivery = _text_cell(
            first.get("requested_delivery_date"),
            "requested_delivery_date",
            allow_empty=True,
        )

        line_candidates: list[IntakeLineCandidate] = []
        line_ids: set[str] = set()
        for physical_line, row in rows:
            row_title = _text_cell(row.get("title"), "title")
            row_delivery = _text_cell(
                row.get("requested_delivery_date"),
                "requested_delivery_date",
                allow_empty=True,
            )
            if row_title != title:
                raise ContractError("CSV request title must be identical across all rows")
            if row_delivery != delivery:
                raise ContractError("CSV requested_delivery_date must be identical across all rows")

            line_id = _text_cell(row.get("line_id"), "line_id")
            if line_id in line_ids:
                raise ContractError("CSV line_id values must be unique")
            line_ids.add(line_id)
            description = _text_cell(row.get("description"), "description")
            quantity = _quantity_cell(row.get("quantity"))
            unit = _text_cell(row.get("unit"), "unit")
            locator_prefix = f"csv:line:{physical_line}"
            line_candidates.append(
                IntakeLineCandidate(
                    line_candidate_id=line_id,
                    description=_field(
                        f"{line_id}.description",
                        description,
                        locator=f"{locator_prefix}:description",
                    ),
                    quantity=_field(
                        f"{line_id}.quantity",
                        quantity,
                        locator=f"{locator_prefix}:quantity",
                    ),
                    unit=_field(
                        f"{line_id}.unit",
                        unit,
                        locator=f"{locator_prefix}:unit",
                    ),
                )
            )

        title_field = _field(
            "request.title",
            title,
            locator=f"csv:line:{first_line}:title",
        )
        delivery_field = None
        if delivery:
            delivery_field = _field(
                "request.requested_delivery_date",
                delivery,
                locator=f"csv:line:{first_line}:requested_delivery_date",
            )

        candidate = CommercialRequestIntakeCandidate(
            candidate_id=candidate_id,
            workspace_id=source.workspace_id,
            source=source,
            version=version,
            title=title_field,
            requested_delivery_date=delivery_field,
            line_candidates=tuple(line_candidates),
            trusted_customer_id=None,
        )
        return StrictCsvIntakeResult(
            candidate=candidate,
            physical_line_count=reader.line_num,
            data_row_count=len(rows),
        )


CSV_FORMULA_EXECUTION_SUPPORTED = False
CSV_AUTO_PROMOTION_SUPPORTED = False
CSV_TRUSTED_CUSTOMER_BINDING_SUPPORTED = False
