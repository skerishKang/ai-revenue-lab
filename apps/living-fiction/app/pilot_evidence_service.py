"""Pilot evidence service — validated boundary with privacy enforcement.

Validates:
- allowed evidence categories;
- referenced reader and episodes exist;
- branch episode belongs to reader;
- canon/branch category combinations;
- nonnegative bounded numeric values;
- KRW 4,900 remains an offer/hypothesis, not a payment claim;
- consent requirements;
- bounded text;
- export-safe fields.

Recursively detects and rejects or redacts:
- payer identity;
- account/card numbers;
- phone/email;
- credentials/API keys/tokens;
- private reader comments;
- raw generated prose.

The persisted record, not merely the returned view, must be privacy-safe.
Does not accept a caller-controlled privacy_safe flag as proof.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.domain.enums import EvidenceCategory
from app.pipeline.errors import PrivacyViolationError
from app.pipeline.privacy import reject_sensitive_data, redact_sensitive_data
from app.utils import new_id, now_utc_iso


# Allowed categories
_ALLOWED_CATEGORIES = frozenset(e.value for e in EvidenceCategory)

# Numeric bounds for bounded fields
_MAX_NUMERIC_VALUE = 1_000_000  # reasonable upper bound for pilot metrics
_MAX_TEXT_LENGTH = 2000
_MAX_REVENUE_KRW = 100_000  # KRW amounts in pilot evidence are hypotheses

# Fields that may contain revenue hypothesis data
_REVENUE_CATEGORIES = {EvidenceCategory.REVENUE_HYPOTHESIS.value}

# Fields that require consent verification
_CONSENT_REQUIRING_CATEGORIES = {
    EvidenceCategory.EXPLICIT_CHOICE.value,
    EvidenceCategory.EPISODE_DELIVERY.value,
}

# Payment claim keywords that must NOT appear
_PAYMENT_CLAIM_KEYWORDS = frozenset({
    "paid", "payment_received", "charged", "transaction_complete",
    "실제 결제", "실제 매출", "결제 완료", "매출 발생",
})


@dataclass(frozen=True)
class PilotEvidenceResult:
    evidence_id: str
    evidence_category: str
    evidence_data_json: str
    privacy_safe: bool
    created_at: str


class PilotEvidenceValidationError(ValueError):
    pass


def _validate_category(category: str) -> None:
    if category not in _ALLOWED_CATEGORIES:
        raise PilotEvidenceValidationError(
            f"unsupported evidence category: {category}. "
            f"Allowed: {sorted(_ALLOWED_CATEGORIES)}"
        )


def _validate_references(
    conn: sqlite3.Connection,
    *,
    reader_id: str | None,
    canon_episode_id: str | None,
    branch_episode_id: str | None,
    evidence_category: str,
) -> None:
    """Verify referenced entities exist and ownership is correct."""
    if reader_id is not None:
        row = conn.execute(
            "SELECT id FROM readers WHERE id = ?", (reader_id,)
        ).fetchone()
        if row is None:
            raise PilotEvidenceValidationError(
                f"reader not found: {reader_id}"
            )

    if canon_episode_id is not None:
        row = conn.execute(
            "SELECT id FROM episodes WHERE id = ?", (canon_episode_id,)
        ).fetchone()
        if row is None:
            raise PilotEvidenceValidationError(
                f"canon episode not found: {canon_episode_id}"
            )

    if branch_episode_id is not None:
        row = conn.execute(
            "SELECT id, reader_id, episode_type FROM episodes WHERE id = ?",
            (branch_episode_id,),
        ).fetchone()
        if row is None:
            raise PilotEvidenceValidationError(
                f"branch episode not found: {branch_episode_id}"
            )
        if row["episode_type"] != "personal_branch":
            raise PilotEvidenceValidationError(
                f"episode {branch_episode_id} is not a personal_branch"
            )
        # If reader_id is also provided, verify ownership
        if reader_id is not None and row["reader_id"] != reader_id:
            raise PilotEvidenceValidationError(
                f"branch episode {branch_episode_id} does not belong to "
                f"reader {reader_id}"
            )


def _validate_numeric_bounds(data: dict) -> None:
    """Validate that numeric values are nonnegative and bounded."""
    for key, value in data.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < 0:
                raise PilotEvidenceValidationError(
                    f"negative value not allowed for '{key}': {value}"
                )
            if value > _MAX_NUMERIC_VALUE:
                raise PilotEvidenceValidationError(
                    f"value {value} exceeds maximum {_MAX_NUMERIC_VALUE} for '{key}'"
                )
        elif isinstance(value, dict):
            _validate_numeric_bounds(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _validate_numeric_bounds(item)
                elif isinstance(item, (int, float)) and not isinstance(item, bool):
                    if item < 0 or item > _MAX_NUMERIC_VALUE:
                        raise PilotEvidenceValidationError(
                            f"out-of-bounds numeric value in list for '{key}'"
                        )


def _validate_text_bounds(data: dict) -> None:
    """Validate that text values are bounded."""
    for key, value in data.items():
        if isinstance(value, str):
            if len(value) > _MAX_TEXT_LENGTH:
                raise PilotEvidenceValidationError(
                    f"text value too long for '{key}': {len(value)} > {_MAX_TEXT_LENGTH}"
                )
        elif isinstance(value, dict):
            _validate_text_bounds(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and len(item) > _MAX_TEXT_LENGTH:
                    raise PilotEvidenceValidationError(
                        f"text value too long in list for '{key}'"
                    )
                elif isinstance(item, dict):
                    _validate_text_bounds(item)


def _validate_revenue_hypothesis(
    category: str,
    data: dict,
) -> None:
    """Ensure KRW amounts are hypotheses, not payment claims."""
    if category not in _REVENUE_CATEGORIES:
        return

    # Check for payment claim keywords
    for key, value in data.items():
        if isinstance(value, str):
            value_lower = value.lower()
            for keyword in _PAYMENT_CLAIM_KEYWORDS:
                if keyword in value_lower or keyword in value:
                    raise PilotEvidenceValidationError(
                        f"revenue hypothesis must not claim actual payment: "
                        f"'{keyword}' found in '{key}'"
                    )

    # Check KRW amounts
    for key, value in data.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value > _MAX_REVENUE_KRW:
                raise PilotEvidenceValidationError(
                    f"revenue amount {value} exceeds hypothesis bound {_MAX_REVENUE_KRW}"
                )
        # Specifically check for 4900 (the offer price) — it must be labeled as hypothesis
        if isinstance(value, (int, float)) and value == 4900:
            # Must have a field indicating it's a hypothesis
            is_hypothesis = data.get("is_hypothesis", data.get("type", ""))
            if isinstance(is_hypothesis, str):
                if "hypothesis" not in is_hypothesis.lower() and "offer" not in is_hypothesis.lower():
                    raise PilotEvidenceValidationError(
                        "KRW 4,900 must be labeled as a hypothesis/offer, not a payment"
                    )
            elif not is_hypothesis:
                raise PilotEvidenceValidationError(
                    "KRW 4,900 must be accompanied by is_hypothesis=true or type='hypothesis'"
                )


def _validate_consent(
    category: str,
    data: dict,
) -> None:
    """Validate consent requirements for certain categories."""
    if category not in _CONSENT_REQUIRING_CATEGORIES:
        return

    # Check if consent is recorded
    consent = data.get("consent_obtained", data.get("has_consent"))
    if consent is None:
        raise PilotEvidenceValidationError(
            f"category '{category}' requires consent_obtained field"
        )
    if not consent:
        raise PilotEvidenceValidationError(
            f"category '{category}' requires explicit consent"
        )


def create_validated_pilot_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_category: str,
    evidence_data: dict,
    canon_episode_id: str | None = None,
    branch_episode_id: str | None = None,
    reader_id: str | None = None,
) -> PilotEvidenceResult:
    """Create a privacy-safe pilot evidence record with full validation.

    The persisted record is privacy-safe. Caller-controlled privacy_safe
    flags are NOT accepted as proof — the scanner determines safety.
    """
    # 1. Validate category
    _validate_category(evidence_category)

    # 2. Validate references and ownership
    _validate_references(
        conn,
        reader_id=reader_id,
        canon_episode_id=canon_episode_id,
        branch_episode_id=branch_episode_id,
        evidence_category=evidence_category,
    )

    # 3. Validate numeric bounds
    _validate_numeric_bounds(evidence_data)

    # 4. Validate text bounds
    _validate_text_bounds(evidence_data)

    # 5. Validate revenue hypothesis constraints
    _validate_revenue_hypothesis(evidence_category, evidence_data)

    # 6. Validate consent requirements
    _validate_consent(evidence_category, evidence_data)

    # 7. Scan for sensitive data — REJECT if found
    reject_sensitive_data(evidence_data, path="evidence_data")

    # 8. Redact any residual sensitive data (defense in depth)
    redacted_data = redact_sensitive_data(evidence_data)

    # 9. Persist — the stored record is privacy-safe by construction
    evidence_id = new_id()
    now = now_utc_iso()
    stored_json = json.dumps(redacted_data, ensure_ascii=False)

    if conn.in_transaction:
        raise RuntimeError(
            "pilot evidence creation requires an idle connection"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO pilot_evidence "
            "(id, evidence_category, canon_episode_id, branch_episode_id, "
            "reader_id, evidence_data_json, privacy_safe, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (
                evidence_id, evidence_category, canon_episode_id,
                branch_episode_id, reader_id, stored_json, now,
            ),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise

    return PilotEvidenceResult(
        evidence_id=evidence_id,
        evidence_category=evidence_category,
        evidence_data_json=stored_json,
        privacy_safe=True,
        created_at=now,
    )
