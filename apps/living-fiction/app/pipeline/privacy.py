"""Privacy scanner — recursive detection of sensitive data.

Recursively detects and rejects or redacts:
- payer identity;
- account/card numbers;
- phone/email;
- credentials/API keys/tokens;
- private reader comments;
- raw generated prose.
"""

from __future__ import annotations

import re
from typing import Any

from app.pipeline.errors import PrivacyViolationError


# Sensitive data patterns
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Credit card numbers (13-19 digits, possibly grouped)
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "account/card number"),
    # Phone numbers (Korean and international)
    (re.compile(r"\b01[0-9][-\s]?[0-9]{3,4}[-\s]?[0-9]{4}\b"), "phone number"),
    (re.compile(r"\b\+\d{1,3}[-\s]?\d{1,4}[-\s]?\d{3,4}[-\s]?\d{4}\b"), "phone number"),
    # Email addresses
    (re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"), "email address"),
    # API keys / tokens (common patterns)
    (re.compile(r"\b(?:api[_-]?key|token|secret|bearer|authorization)\s*[:=]\s*['\"]?[a-zA-Z0-9+/=_-]{16,}['\"]?", re.IGNORECASE), "credential/API key"),
    (re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"), "API key (sk- pattern)"),
    (re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b"), "AWS access key"),
]

# Sensitive field names that must never appear in export-safe data
_SENSITIVE_FIELD_NAMES = frozenset({
    "payer", "payer_name", "payer_id", "card", "card_number", "card_cvv",
    "account_number", "bank_account", "iban", "routing_number",
    "ssn", "social_security", "phone", "phone_number", "mobile",
    "email", "email_address", "password", "passwd", "credential",
    "api_key", "token", "secret", "private_key", "access_key",
    "reader_comment", "raw_comment", "private_comment",
    "raw_prose", "raw_generated_text", "raw_content",
})


def _check_string(value: str, path: str) -> str | None:
    """Return violation reason if string contains sensitive data, else None."""
    for pattern, reason in _PATTERNS:
        if pattern.search(value):
            return f"{reason} detected in '{path}'"
    return None


def _check_field_name(key: str, path: str) -> str | None:
    """Check if a field name is sensitive."""
    key_lower = key.lower()
    for sensitive in _SENSITIVE_FIELD_NAMES:
        if sensitive in key_lower:
            return f"sensitive field name '{key}' in '{path}'"
    return None


def scan_for_sensitive_data(payload: Any, *, path: str = "") -> list[str]:
    """Recursively scan payload for sensitive data. Returns list of violations."""
    violations: list[str] = []

    if isinstance(payload, str):
        reason = _check_string(payload, path or "value")
        if reason:
            violations.append(reason)
        return violations

    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}" if path else str(key)
            # Check field name
            field_violation = _check_field_name(str(key), path or "root")
            if field_violation:
                violations.append(field_violation)
            # Recurse into value
            violations.extend(scan_for_sensitive_data(value, path=child_path))
        return violations

    if isinstance(payload, (list, tuple)):
        for idx, item in enumerate(payload):
            child_path = f"{path}[{idx}]" if path else f"[{idx}]"
            violations.extend(scan_for_sensitive_data(item, path=child_path))
        return violations

    return violations


def reject_sensitive_data(payload: Any, *, path: str = "") -> None:
    """Raise PrivacyViolationError if payload contains sensitive data."""
    violations = scan_for_sensitive_data(payload, path=path)
    if violations:
        raise PrivacyViolationError(
            f"privacy violation: {'; '.join(violations)}"
        )


def redact_sensitive_data(payload: Any) -> Any:
    """Return a copy of payload with sensitive data redacted.

    Replaces detected sensitive values with '[REDACTED]'.
    Sensitive field names are replaced with '[REDACTED_FIELD]'.
    """
    if isinstance(payload, str):
        result = payload
        for pattern, _ in _PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result

    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            key_lower = str(key).lower()
            is_sensitive = any(s in key_lower for s in _SENSITIVE_FIELD_NAMES)
            if is_sensitive:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive_data(value)
        return redacted

    if isinstance(payload, (list, tuple)):
        return [redact_sensitive_data(item) for item in payload]

    return payload
