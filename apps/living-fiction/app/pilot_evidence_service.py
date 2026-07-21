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
- raw generated prose;
- nested payment claims;
- nested KRW amounts;
- nested consent fields;
- nested sensitive fields;
- list values;
- deeply nested raw prose/comments.

The persisted record, not merely the returned view, must be privacy-safe.
Does not accept a caller-controlled privacy_safe flag as proof.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.domain.enums import EvidenceCategory
from app.pipeline.errors import PrivacyViolationError
from app.pipeline.privacy import reject_sensitive_data, redact_sensitive_data, scan_for_sensitive_data
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

# Canon delivery evidence should reference only canon episodes
_CANON_REFERENCE_CATEGORIES = {EvidenceCategory.EPISODE_DELIVERY.value}

# Branch/choice evidence must reference personal branch + matching reader
_BRANCH_REFERENCE_CATEGORIES = {
    EvidenceCategory.EXPLICIT_CHOICE.value,
    EvidenceCategory.EPISODE_DELIVERY.value,
}

# Revenue hypotheses must not claim actual payment
_REVENUE_HYPOTHESIS_CATEGORIES = {EvidenceCategory.REVENUE_HYPOTHESIS.value}

# AI/infrastructure cost must NOT include payer/card/account identity
_AI_COST_CATEGORIES = {EvidenceCategory.AI_INFRA_COST.value}

# Sensitive field names that must be recursively detected
_SENSITIVE_FIELD_NAMES_RECURSIVE = frozenset({
    "payer", "payer_name", "payer_id", "card", "card_number", "card_cvv",
    "account_number", "bank_account", "iban", "routing_number",
    "ssn", "social_security",
    "api_key", "api_secret", "token", "bearer", "credential",
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
            "SELECT id, episode_type FROM episodes WHERE id = ?",
            (canon_episode_id,),
        ).fetchone()
        if row is None:
            raise PilotEvidenceValidationError(
                f"canon episode not found: {canon_episode_id}"
            )
        # Canon delivery evidence must reference actual canon episodes
        if evidence_category in _CANON_REFERENCE_CATEGORIES:
            if row["episode_type"] != "canon":
                raise PilotEvidenceValidationError(
                    f"canon delivery evidence must reference a canon episode, "
                    f"got {row['episode_type']}"
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
        # Branch/choice evidence must reference matching reader
        if evidence_category in _BRANCH_REFERENCE_CATEGORIES:
            if reader_id is None or row["reader_id"] is None:
                raise PilotEvidenceValidationError(
                    f"{evidence_category} evidence requires both reader_id "
                    f"and a branch episode owned by that reader"
                )


def _recursive_scan_strings(
    data: Any,
    path: str,
    callback,
) -> None:
    """Recursively walk all string values in a nested structure."""
    if isinstance(data, str):
        callback(data, path)
    elif isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)
            _recursive_scan_strings(value, child_path, callback)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            child_path = f"{path}[{idx}]"
            _recursive_scan_strings(item, child_path, callback)


def _recursive_scan_numeric(
    data: Any,
    path: str,
    callback,
) -> None:
    """Recursively walk all numeric values in a nested structure."""
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        callback(data, path)
    elif isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)
            _recursive_scan_numeric(value, child_path, callback)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            child_path = f"{path}[{idx}]"
            _recursive_scan_numeric(item, child_path, callback)


def _validate_numeric_bounds(data: dict) -> None:
    """Validate that numeric values are nonnegative and bounded (recursive)."""
    def _check_numeric(value: int | float, path: str) -> None:
        if value < 0:
            raise PilotEvidenceValidationError(
                f"negative value not allowed at '{path}': {value}"
            )
        if value > _MAX_NUMERIC_VALUE:
            raise PilotEvidenceValidationError(
                f"value {value} exceeds maximum {_MAX_NUMERIC_VALUE} at '{path}'"
            )

    _recursive_scan_numeric(data, "root", _check_numeric)


def _validate_text_bounds(data: dict) -> None:
    """Validate that text values are bounded (recursive)."""
    def _check_text_length(value: str, path: str) -> None:
        if len(value) > _MAX_TEXT_LENGTH:
            raise PilotEvidenceValidationError(
                f"text value too long at '{path}': {len(value)} > {_MAX_TEXT_LENGTH}"
            )

    _recursive_scan_strings(data, "root", _check_text_length)


def _validate_revenue_hypothesis(
    category: str,
    data: dict,
) -> None:
    """Ensure KRW amounts are hypotheses, not payment claims (recursive)."""
    if category not in _REVENUE_HYPOTHESIS_CATEGORIES:
        return

    # Recursive payment claim keyword check
    def _check_payment_claim(value: str, path: str) -> None:
        value_lower = value.lower()
        for keyword in _PAYMENT_CLAIM_KEYWORDS:
            if keyword in value_lower or keyword in value:
                raise PilotEvidenceValidationError(
                    f"revenue hypothesis must not claim actual payment: "
                    f"'{keyword}' found at '{path}'"
                )

    _recursive_scan_strings(data, "root", _check_payment_claim)

    # Recursive KRW amount check — 4900 must be labeled as hypothesis
    # Also check for high amounts that exceed hypothesis bound
    def _check_krw_amount(value: int | float, path: str) -> None:
        if value > _MAX_REVENUE_KRW:
            raise PilotEvidenceValidationError(
                f"revenue amount {value} exceeds hypothesis bound "
                f"{_MAX_REVENUE_KRW} at '{path}'"
            )
        if value == 4900:
            # Must have a field indicating it's a hypothesis somewhere in the data
            # We scan the entire data structure for this
            is_hypothesis = _find_field_value(data, "is_hypothesis")
            evidence_type = _find_field_value(data, "type")
            if not is_hypothesis and not evidence_type:
                raise PilotEvidenceValidationError(
                    "KRW 4,900 must be accompanied by is_hypothesis=true "
                    f"or type='hypothesis' at '{path}'"
                )
            if evidence_type and isinstance(evidence_type, str):
                if "hypothesis" not in evidence_type.lower() and "offer" not in evidence_type.lower():
                    raise PilotEvidenceValidationError(
                        "KRW 4,900 must be labeled as a hypothesis/offer, "
                        f"not a payment at '{path}'"
                    )
            elif is_hypothesis is not None and not bool(is_hypothesis):
                raise PilotEvidenceValidationError(
                    "KRW 4,900 must be accompanied by is_hypothesis=true "
                    f"at '{path}'"
                )

    _recursive_scan_numeric(data, "root", _check_krw_amount)


def _find_field_value(data: Any, field_name: str) -> Any:
    """Recursively search nested data for a field name and return its value."""
    if isinstance(data, dict):
        if field_name in data:
            return data[field_name]
        for value in data.values():
            result = _find_field_value(value, field_name)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_field_value(item, field_name)
            if result is not None:
                return result
    return None


def _validate_consent(
    category: str,
    data: dict,
) -> None:
    """Validate consent requirements for certain categories (recursive)."""
    if category not in _CONSENT_REQUIRING_CATEGORIES:
        return

    # Recursively check for consent field at any nesting level
    consent = _find_field_value(data, "consent_obtained")
    if consent is None:
        consent = _find_field_value(data, "has_consent")
    if consent is None:
        # Check nested keys more thoroughly
        consent = _deep_find_consent(data)
    if consent is None:
        raise PilotEvidenceValidationError(
            f"category '{category}' requires consent_obtained field"
        )
    if not consent:
        raise PilotEvidenceValidationError(
            f"category '{category}' requires explicit consent"
        )


_CONSENT_FIELD_NAMES = frozenset({
    "consent_obtained", "has_consent", "consent", "user_consent",
})


def _deep_find_consent(data: Any) -> Any:
    """Deep search for any consent-related field."""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in _CONSENT_FIELD_NAMES:
                return value
            result = _deep_find_consent(value)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _deep_find_consent(item)
            if result is not None:
                return result
    return None


def _validate_recursive_sensitive_fields(data: dict) -> None:
    """Recursively detect sensitive field names at any nesting depth."""

    def _check_field_names(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key in value:
                if isinstance(key, str) and key.lower() in _SENSITIVE_FIELD_NAMES_RECURSIVE:
                    raise PilotEvidenceValidationError(
                        f"sensitive field '{key}' at '{path}' not allowed "
                        f"in pilot evidence"
                    )

    _recursive_scan_strings(data, "root", lambda *args: None)
    # Check first with field name scanning
    data_copy = data
    _recursive_field_name_check(data_copy, "evidence_data")


def _recursive_field_name_check(data: Any, path: str) -> None:
    """Recursively check dict keys for sensitive field names."""
    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}"
            if isinstance(key, str) and key.lower() in _SENSITIVE_FIELD_NAMES_RECURSIVE:
                raise PilotEvidenceValidationError(
                    f"sensitive field name '{key}' not allowed at '{child_path}'"
                )
            _recursive_field_name_check(value, child_path)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            _recursive_field_name_check(item, f"{path}[{idx}]")


def _validate_ai_cost_fields(category: str, data: dict) -> None:
    """AI/infrastructure cost must not include payer/card/account identity."""
    if category not in _AI_COST_CATEGORIES:
        return

    _recursive_field_name_check(data, "evidence_data")


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

    # 3. Validate numeric bounds (recursive)
    _validate_numeric_bounds(evidence_data)

    # 4. Validate text bounds (recursive)
    _validate_text_bounds(evidence_data)

    # 5. Validate revenue hypothesis constraints (recursive)
    _validate_revenue_hypothesis(evidence_category, evidence_data)

    # 6. Validate consent requirements (recursive)
    _validate_consent(evidence_category, evidence_data)

    # 7. Recursive sensitive field name check
    _validate_recursive_sensitive_fields(evidence_data)

    # 8. AI cost field validation
    _validate_ai_cost_fields(evidence_category, evidence_data)

    # 9. Scan for sensitive data — REJECT if found (recursive)
    reject_sensitive_data(evidence_data, path="evidence_data")

    # 10. Redact any residual sensitive data (defense in depth)
    redacted_data = redact_sensitive_data(evidence_data)

    # 11. Persist — the stored record is privacy-safe by construction
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
