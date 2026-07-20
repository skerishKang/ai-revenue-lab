"""Deterministic grounding checks for prohibited personal-fact invention.

Contract (PERSONAL_EDITION_MVP_CONTRACT.md section 8.3): a draft is rejected
when it invents a place, date, amount, relationship, diagnosis, intention, or
event that is not supported by the supplied input segments.

This module provides a deterministic, allow-list grounding mechanism. It does
NOT claim broader semantic guarantees. It can only prove that a draft never
mentions a configured prohibited token. A draft that passes grounding may
still contain a subtle semantic invention that deterministic checks cannot
detect; that risk is deferred to human review (Phase 5) and optional model
review (Stage 4).

Grounding is intentionally conservative:
- only configured prohibited tokens are rejected;
- allowed facts are recorded for traceability and never cause rejection;
- matching is boundary-aware so a short token does not match inside a longer
  alphanumeric word (for example 'date' does not match 'update').
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.pipeline.errors import GroundingError


@dataclass(frozen=True)
class GroundingPolicy:
    """Configuration for a single grounding pass.

    prohibited_tokens are case-insensitive tokens that, if found in any
    visible draft field, cause rejection. They are typically drawn from the
    fixture's prohibited_inventions list so that an invented spouse, place,
    date, amount, relationship, diagnosis, intention, or event is caught.

    allowed_facts are recorded for traceability and never cause rejection.
    """

    prohibited_tokens: frozenset[str] = field(default_factory=frozenset)
    allowed_facts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        lowered = set()
        for tok in self.prohibited_tokens:
            if not isinstance(tok, str) or not tok.strip():
                raise GroundingError(
                    "prohibited_tokens must contain non-empty strings"
                )
            lowered.add(_normalize_token(tok))
        object.__setattr__(self, "prohibited_tokens", frozenset(lowered))


def _normalize_token(token: str) -> str:
    return unicodedata.normalize("NFKC", token).strip().casefold()


def _build_pattern(token: str) -> re.Pattern[str]:
    # Boundary-aware match: reject an ASCII alphanumeric neighbor on either
    # side so a short token cannot match inside a longer word. CJK characters
    # are not alphanumeric in this sense, so a Korean token still matches as a
    # contiguous substring.
    escaped = re.escape(token)
    return re.compile(
        r"(?<![A-Za-z0-9_])" + escaped + r"(?![A-Za-z0-9_])",
        re.UNICODE,
    )


@dataclass(frozen=True)
class GroundingViolation:
    """A single prohibited token found in a visible draft field."""

    token: str
    field: str

    def __str__(self) -> str:
        return "prohibited invention in " + self.field


def check_grounding(
    *,
    policy: GroundingPolicy,
    visible_fields: dict[str, str],
) -> None:
    """Reject the draft if any visible field contains a prohibited token.

    visible_fields maps field names to their visible string values (for example
    opening, deck, each section's joined paragraphs). Only the field name is
    reported in the error message; the surrounding draft text is never echoed.
    """
    if not isinstance(visible_fields, dict):
        raise GroundingError("visible_fields must be a dict")

    patterns = {
        tok: _build_pattern(tok) for tok in policy.prohibited_tokens
    }

    for field_name, value in visible_fields.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise GroundingError(
                "visible field " + str(field_name) + " must be a string"
            )
        normalized_value = _normalize_token(value)
        for tok, pattern in patterns.items():
            if pattern.search(normalized_value):
                raise GroundingError(
                    "prohibited invention detected in field '"
                    + field_name
                    + "': matched a prohibited token"
                )


def find_violations(
    *,
    policy: GroundingPolicy,
    visible_fields: dict[str, str],
) -> list[GroundingViolation]:
    """Return all grounding violations without raising.

    Used by tests and reviewers to enumerate every prohibited token hit in a
    single pass rather than stopping at the first one.
    """
    if not isinstance(visible_fields, dict):
        raise GroundingError("visible_fields must be a dict")

    patterns = {
        tok: _build_pattern(tok) for tok in policy.prohibited_tokens
    }
    violations: list[GroundingViolation] = []
    for field_name, value in visible_fields.items():
        if value is None or not isinstance(value, str):
            continue
        normalized_value = _normalize_token(value)
        for tok, pattern in patterns.items():
            if pattern.search(normalized_value):
                violations.append(
                    GroundingViolation(token=tok, field=field_name)
                )
    return violations
