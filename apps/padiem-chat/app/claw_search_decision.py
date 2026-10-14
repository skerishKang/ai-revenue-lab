"""#4469: AI-decided public web search for the Claw lane.

The decision belongs to a model: the Engine's ``search_judgement`` operation reads the
conversation and says whether current public evidence is needed and how to ask for it.
What stays here is not a classifier but the two things a model verdict must never be
trusted to do by itself — bound what may leave the product, and refuse private material.
No retrieval happens here and nothing in this module grants provider or tool authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

MAX_PUBLIC_SEARCH_QUERY_CHARS = 200
MAX_JUDGEMENT_DIGEST_CHARS = 3_000
CLAW_JUDGEMENT_AGENT_ID = "claw-public-search-judgement"

# Private shapes stop a query outright; they are never redacted into something sendable.
_PRIVATE_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),                       # e-mail
    re.compile(r"(?<!\d)01[01][- ]?\d{3,4}[- ]?\d{4}(?!\d)"),       # mobile number
    re.compile(r"(?<!\d)\d{2,3}[- ]?\d{3,4}[- ]?\d{4}(?!\d)"),      # landline number
    re.compile(r"(?i)(bearer|refresh[-_ ]?token|api[-_ ]?key|client[-_ ]?secret|cookie)"),
    re.compile(r"(?i)\.(pdf|xlsx|docx|csv|zip|png|jpg)\b"),         # attachment names
    re.compile(r"(?i)(usr_|session[-_]?id|workspace[-_]?ref|actor[-_]?ref|binding[-_]?ref)"),
    re.compile(r"(견적|단가|원가|계좌|주민등록|여권번호|고객명|거래처|사내|비밀|기밀)"),
)


class ClawSearchOutcome(str, Enum):
    SEARCH = "search"
    NO_SEARCH = "no_search"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class ClawSearchVerdict:
    outcome: ClawSearchOutcome
    reason: str
    query: str | None = None

    @property
    def should_search(self) -> bool:
        return self.outcome is ClawSearchOutcome.SEARCH and bool(self.query)


def is_private(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _PRIVATE_PATTERNS)


def evidence_agent() -> dict[str, Any]:
    """One server-owned read-only profile; it selects no model and authorises nothing."""

    return {
        "id": CLAW_JUDGEMENT_AGENT_ID,
        "title": "Claw public search judgement",
        "description": "Read-only decision on whether public evidence is needed.",
        "system_instruction": "Judge public evidence need only.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 256,
        "model_policy": {"model": "none/disabled", "max_retries": 0},
    }


def build_judgement_digest(context: Any, *, max_chars: int = MAX_JUDGEMENT_DIGEST_CHARS) -> str | None:
    """Bound the owner-verified conversation the judge is allowed to read.

    The Claw lane hands over the same server-resolved context string the answer lane
    receives, so nothing here re-reads browser turns. This text stays inside Padiem.
    """

    if isinstance(context, str):
        digest = " ".join(context.split())
        if not digest:
            return None
        return digest[-max_chars:] if len(digest) > max_chars else digest
    if not isinstance(context, (list, tuple)):
        return None
    lines: list[str] = []
    for item in context:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        lines.append(f"{role}: {' '.join(content.split())[:600]}")
    if not lines:
        return None
    digest = "\n".join(lines[-12:])
    return digest[-max_chars:] if len(digest) > max_chars else digest


def normalize_judged_query(value: Any) -> str | None:
    """Bound and re-check the model's query before anything can leave the product."""

    if not isinstance(value, str):
        return None
    query = " ".join(value.split())[:MAX_PUBLIC_SEARCH_QUERY_CHARS].strip()
    if len(query) < 2 or is_private(query):
        return None
    return query


def verdict_from_model(raw: Any) -> ClawSearchVerdict:
    """Map a validated Engine judgement onto this lane's three outcomes."""

    if not isinstance(raw, dict) or not isinstance(raw.get("needs_search"), bool):
        return ClawSearchVerdict(ClawSearchOutcome.NO_SEARCH, "judgement_unavailable")
    reason = raw.get("reason") if isinstance(raw.get("reason"), str) else "clarify_context"
    if not raw["needs_search"]:
        outcome = (
            ClawSearchOutcome.CLARIFY if reason == "clarify_context" else ClawSearchOutcome.NO_SEARCH
        )
        return ClawSearchVerdict(outcome, f"model:{reason}")
    query = normalize_judged_query(raw.get("query"))
    if query is None:
        # The model asked for a lookup, but what it proposed cannot be sent safely.
        return ClawSearchVerdict(ClawSearchOutcome.CLARIFY, "model_query_unusable")
    return ClawSearchVerdict(ClawSearchOutcome.SEARCH, f"model:{reason}", query)


__all__ = [
    "CLAW_JUDGEMENT_AGENT_ID",
    "ClawSearchOutcome",
    "ClawSearchVerdict",
    "MAX_JUDGEMENT_DIGEST_CHARS",
    "MAX_PUBLIC_SEARCH_QUERY_CHARS",
    "build_judgement_digest",
    "evidence_agent",
    "is_private",
    "normalize_judged_query",
    "verdict_from_model",
]
