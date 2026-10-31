"""Decide which normalized records still need a person.

The pipeline's job is to remove the mechanical work and to hand a person the
judgement calls. A record is marked for review when a value is missing, when a
value could not be read, when two records describe the same item, or when an
AI extraction proposed something a person should see.

Every reason is a stable, machine-readable token, so a reviewer can sort the
queue and a test can assert on it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .contracts import (
    PRICE_FIELDS,
    REQUIRED_FIELDS,
    FieldOrigin,
    ItemRecord,
    ReviewStatus,
)

#: An AI-extracted optional field below this confidence is not settled.
AI_FIELD_CONFIDENCE_THRESHOLD = Decimal("0.85")

#: An AI-extracted required field always reaches a person, whatever its
#: confidence: the ERP key and the item name decide what the row becomes.
AI_FILLED_REQUIRED_FIELDS = REQUIRED_FIELDS


def _price_reason(record: ItemRecord, field_name: str) -> str | None:
    """Distinguish an absent price from a price that could not be read."""

    value = record.fields.get(field_name)
    if value is None:
        return None
    if value.present:
        return None
    raw = record.raw.get(field_name, "")
    if not raw.strip():
        return f"missing_{field_name}"
    return f"unreadable_{field_name}"


def review_reasons_for(record: ItemRecord) -> tuple[str, ...]:
    """Every reason this record needs a person, in a stable order."""

    reasons: list[str] = []

    for field_name in REQUIRED_FIELDS:
        value = record.fields.get(field_name)
        if value is None or not value.present:
            reasons.append(f"missing_{field_name}")

    for field_name in PRICE_FIELDS:
        reason = _price_reason(record, field_name)
        if reason is not None:
            reasons.append(reason)

    unit = record.fields.get("unit")
    if unit is None or not unit.present:
        reasons.append("missing_unit")

    for field_name, value in record.fields.items():
        if value.origin is not FieldOrigin.AI_EXTRACTION:
            continue
        if field_name in AI_FILLED_REQUIRED_FIELDS:
            reasons.append(f"ai_filled_required_field:{field_name}")
        elif value.confidence < AI_FIELD_CONFIDENCE_THRESHOLD:
            reasons.append(
                f"low_confidence_ai_field:{field_name}({value.confidence})"
            )

    if record.duplicate_group is not None:
        reasons.append(f"duplicate_candidate:{record.duplicate_group}")

    for reason in record.review_reasons:
        if reason not in reasons:
            reasons.append(reason)

    return tuple(reasons)


def apply_review_rules(records: Sequence[ItemRecord]) -> list[ItemRecord]:
    """Mark every record that still needs a person."""

    from dataclasses import replace

    updated: list[ItemRecord] = []
    for record in records:
        reasons = review_reasons_for(record)
        updated.append(
            replace(
                record,
                review_status=(
                    ReviewStatus.REVIEW_REQUIRED if reasons else ReviewStatus.AUTO_OK
                ),
                review_reasons=reasons,
            )
        )
    return updated
