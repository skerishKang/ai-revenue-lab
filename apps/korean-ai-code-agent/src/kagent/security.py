from __future__ import annotations

import re


_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9._-]{8,}\b"), "[REDACTED_KEY]"),
    (
        re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s]+"),
        r"\1[REDACTED]",
    ),
)


def redact_secrets(text: str) -> str:
    """Return a presentation-safe copy with common credential shapes removed."""
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
