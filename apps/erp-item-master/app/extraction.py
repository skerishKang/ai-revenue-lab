"""Provider-neutral contract for AI-extracted item fields.

This module owns the *validation* of an extraction result, not the extraction
itself. It never calls a model, never selects a provider and never holds a
credential. Model choice and provider routing are owner-only decisions
(``docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md``), so a caller
produces the extraction elsewhere and hands the result here to be checked.

Two rules make the result safe to merge into a record:

* a source value always wins over an extracted value, so an extraction can
  fill a gap but can never overwrite what a supplier actually wrote;
* every extracted value keeps the confidence the extractor reported, so a
  person can see which fields deserve a second look.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .contracts import CANONICAL_FIELDS, FieldOrigin, FieldValue
from .normalization import normalize_text

#: This app makes no model call and selects no provider.
AI_PROVIDER_CALLS_IN_THIS_APP = 0
AI_MODEL_SELECTION_AUTHORITY = "NONE"

#: An extracted value below this confidence is never treated as settled.
MIN_USABLE_CONFIDENCE = Decimal("0.50")

#: Lowest confidence a caller may report.
MIN_REPORTABLE_CONFIDENCE = Decimal("0")

#: Fields an extraction may fill.
#:
#: An extraction reads a supplier's unstructured note, so it may propose a
#: name, a model, a maker, a supplier, a unit, a category or a remark. It may
#: not propose an item code, a specification or a price: those three decide
#: what the ERP row means and what it costs, and a generated value for them
#: would be a fabricated business fact.
AI_ASSIGNABLE_FIELDS: tuple[str, ...] = (
    "item_name",
    "model_name",
    "manufacturer",
    "supplier",
    "unit",
    "category",
    "memo",
)

#: Fields an extraction is refused for, with the reason it is refused.
AI_REFUSED_FIELDS: Mapping[str, str] = {
    "item_code": "an item code is an ERP key and must come from a source or a person",
    "specification": "a specification is a product fact and must not be generated",
    "purchase_price": "a purchase price is a business fact and must not be generated",
    "sales_price": "a sales price is a business fact and must not be generated",
}


def _extracted_field(
    field_name: str,
    payload: Mapping[str, Any],
    *,
    locator: str,
) -> tuple[FieldValue | None, str | None]:
    raw_value = payload.get("value")
    if not isinstance(raw_value, str):
        return None, f"{field_name}: value must be a string"
    value = normalize_text(raw_value)
    if not value:
        return None, f"{field_name}: value is empty"

    raw_confidence = payload.get("confidence")
    if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
        return None, f"{field_name}: confidence must be a number"
    try:
        confidence = Decimal(str(raw_confidence))
    except InvalidOperation:
        return None, f"{field_name}: confidence must be a number"
    if confidence < MIN_REPORTABLE_CONFIDENCE or confidence > Decimal("1"):
        return None, f"{field_name}: confidence must be within [0, 1]"

    if confidence < MIN_USABLE_CONFIDENCE:
        return None, f"{field_name}: confidence is below the usable bound"

    return (
        FieldValue(
            value=value,
            origin=FieldOrigin.AI_EXTRACTION,
            confidence=confidence,
            source_locator=locator,
            note="ai_extraction",
        ),
        None,
    )


def normalize_extracted_fields(
    payload: Mapping[str, Any],
    *,
    row_number: int,
) -> tuple[dict[str, FieldValue], tuple[str, ...]]:
    """Validate one extraction result into per-field values plus its errors.

    ``payload`` is ``{"fields": {<canonical field>: {"value": ..., "confidence": ...}}}``.
    A field outside the canonical set is refused by name, so a model cannot
    introduce a field the ERP import never carries.
    """

    raw_fields = payload.get("fields")
    if not isinstance(raw_fields, Mapping):
        return {}, ("extraction.fields must be an object",)

    values: dict[str, FieldValue] = {}
    errors: list[str] = []
    for field_name, field_payload in raw_fields.items():
        if field_name not in CANONICAL_FIELDS:
            errors.append(f"{field_name}: not a canonical item-master field")
            continue
        if field_name in AI_REFUSED_FIELDS:
            errors.append(f"{field_name}: {AI_REFUSED_FIELDS[field_name]}")
            continue
        if field_name not in AI_ASSIGNABLE_FIELDS:
            errors.append(f"{field_name}: not assignable from an extraction")
            continue
        if not isinstance(field_payload, Mapping):
            errors.append(f"{field_name}: field payload must be an object")
            continue
        value, error = _extracted_field(
            field_name,
            field_payload,
            locator=f"ai_extraction:row{row_number}:{field_name}",
        )
        if error is not None:
            errors.append(error)
            continue
        if value is not None:
            values[field_name] = value
    return values, tuple(errors)


def load_extraction_file(
    path: str | Path,
) -> tuple[dict[int, tuple[dict[str, FieldValue], tuple[str, ...]]], dict[str, tuple[dict[str, FieldValue], tuple[str, ...]]]]:
    """Load an extraction file into row-number and item-code lookups.

    The file is a JSON object whose keys are either a source row number or an
    item code. An item code is the readable key a person would use, so both
    are accepted. It is an *input* to the pipeline, so a malformed file is
    refused rather than half-applied.
    """

    extraction_path = Path(path)
    try:
        raw = json.loads(extraction_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"extraction file could not be read: {extraction_path.name}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("extraction file must hold a JSON object")

    by_row: dict[int, tuple[dict[str, FieldValue], tuple[str, ...]]] = {}
    by_code: dict[str, tuple[dict[str, FieldValue], tuple[str, ...]]] = {}
    for row_key, payload in raw.items():
        if not isinstance(payload, Mapping):
            raise ValueError(f"extraction key {row_key!r} must hold an object")
        if isinstance(row_key, int) and not isinstance(row_key, bool):
            by_row[row_key] = normalize_extracted_fields(payload, row_number=row_key)
            continue
        key_text = str(row_key).strip()
        if key_text.isdigit():
            by_row[int(key_text)] = normalize_extracted_fields(
                payload, row_number=int(key_text)
            )
            continue
        by_code[key_text.upper()] = normalize_extracted_fields(payload, row_number=0)
    return by_row, by_code
