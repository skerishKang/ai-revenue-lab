"""Privacy-safe sanitization for pilot evidence and reader revocation."""

from __future__ import annotations

import hashlib
import re

from app.errors import EvidenceValidationError

# Synthetic Phase-1 pricing hypothesis only — never claim real payment/revenue.
ECONOMIC_HYPOTHESIS = (
    "one free sample plus seven adapted microbriefs for KRW 3,900"
)

_EVIDENCE_DETAIL_MAX = 200
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{6,}\d")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_ACCOUNT_RE = re.compile(r"\b(?:acct|account|iban)[:\s#-]*[A-Za-z0-9]{6,}\b", re.I)
_CREDENTIAL_RE = re.compile(
    r"\b(?:password|passwd|secret|credential|api[_-]?key|token|bearer)"
    r"\s*[:=]\s*\S+",
    re.I,
)
_PATH_RE = re.compile(
    r"(?:(?:/|\\)(?:[\w.-]+(?:/|\\))+[\w.-]+|"
    r"(?:[A-Za-z]:\\(?:[\w.-]+\\)+[\w.-]+)|"
    r"screenshot[s]?/[\w./\\-]+)",
    re.I,
)
_PAYMENT_CLAIM_RE = re.compile(
    r"\b(?:paid|payment|revenue|charged|invoice|receipt|settled|매출|결제|입금)\b",
    re.I,
)


def revoked_reader_token(reader_id: str) -> str:
    digest = hashlib.sha256(reader_id.encode("utf-8")).hexdigest()[:16]
    return f"revoked:{digest}"


def sanitize_evidence_detail(detail: str) -> str:
    """Bound length and redact recursive private patterns under free text."""
    if len(detail) > _EVIDENCE_DETAIL_MAX:
        detail = detail[:_EVIDENCE_DETAIL_MAX]
    if _PAYMENT_CLAIM_RE.search(detail):
        raise EvidenceValidationError(
            "pilot evidence must not claim actual payment or revenue; "
            f"hypothesis is {ECONOMIC_HYPOTHESIS}"
        )
    detail = _EMAIL_RE.sub("[redacted]", detail)
    detail = _PHONE_RE.sub("[redacted]", detail)
    detail = _CARD_RE.sub("[redacted]", detail)
    detail = _ACCOUNT_RE.sub("[redacted]", detail)
    detail = _CREDENTIAL_RE.sub("[redacted]", detail)
    detail = _PATH_RE.sub("[redacted]", detail)
    return detail


def export_safe_evidence(record) -> dict:
    """Export shape without raw reader identity or private feedback text."""
    return {
        "id": record.id,
        "evidence_type": record.evidence_type,
        "anonymous_token": record.anonymous_token,
        "economic_hypothesis": ECONOMIC_HYPOTHESIS,
    }
