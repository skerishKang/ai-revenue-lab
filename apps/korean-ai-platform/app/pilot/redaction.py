"""Secret redaction utilities for the BYOK Gateway Pilot.

Ensures that API keys and Authorization headers are never:
- Logged in plaintext
- Included in error messages
- Returned in API responses
- Stored in memory longer than necessary
"""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"

# Patterns that look like API keys or secrets
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Authorization:\s*\S+"),
    re.compile(r"Bearer\s+\S+"),
]


def redact_sensitive(value: str) -> str:
    """Replace sensitive patterns with [REDACTED]."""
    for pattern in _SENSITIVE_PATTERNS:
        value = pattern.sub(_REDACTED, value)
    return value


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with sensitive values redacted."""
    safe = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key in ("authorization", "x-business14-provider-key", "api-key"):
            safe[key] = _REDACTED
        else:
            safe[key] = redact_sensitive(value)
    return safe


def redact_response_body(body: dict) -> dict:
    """Recursively redact sensitive fields from a response dict."""
    if not isinstance(body, dict):
        return body
    redacted: dict = {}
    for key, value in body.items():
        lower_key = key.lower()
        if any(s in lower_key for s in ("key", "token", "secret", "password", "credential")):
            redacted[key] = _REDACTED
        elif isinstance(value, dict):
            redacted[key] = redact_response_body(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_response_body(item) if isinstance(item, dict) else item
                for item in value
            ]
        elif isinstance(value, str):
            redacted[key] = redact_sensitive(value)
        else:
            redacted[key] = value
    return redacted
