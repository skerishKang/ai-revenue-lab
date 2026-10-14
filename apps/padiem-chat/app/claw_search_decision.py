"""#4469: conversation-aware judgement of whether a public web search is warranted.

The disposition vocabulary is owned by Core's ``decide_search`` contract, which Chat,
Claw and B66 already consume; this module adds only the two things the Claw lane needs
on top of it — follow-up context resolution and a hard privacy filter on what may leave
the product. It performs no retrieval, grants no provider authority, and never calls a
model: an extra paid inference per turn is explicitly out of contract here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from padiem_ai_core.search_decision import SearchDecision, SearchDisposition, decide_search

MAX_PUBLIC_SEARCH_QUERY_CHARS = 200
_MAX_PRIOR_TURNS = 8

# Product-layer topical extension of Core's contract: categories whose truth changes
# outside the model, so a bare mention of them is worth a public lookup even when the
# sentence carries no explicit freshness word. Deterministic, bounded, never an authority.
_VOLATILE_PUBLIC_TOPICS = (
    "지원사업", "지원금", "공모", "공고", "신청 기간", "모집", "정책", "법률", "개정", "규제",
    "시세", "요금", "환율", "금리", "가격", "뉴스", "현황", "최근", "최신", "올해", "작년",
    "현재", "오늘",
)

# A turn that only points at something else cannot become a public query on its own.
_DEICTIC_STARTS = (
    "그럼", "그러면", "그래서", "그리고", "계속", "방금", "위", "아까", "이어서", "그거", "이거",
)
_DEICTIC_TERMS = (
    "이거", "그거", "해당", "위의", "앞선", "방금", "그 사업", "이 사업", "그 공고", "이 공고",
    "그거", "이거요", "계속",
)

# Anything matching these never leaves the product, even when the topic looks public.
_PRIVATE_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),                      # e-mail
    re.compile(r"(?<!\d)01[01][- ]?\d{3,4}[- ]?\d{4}(?!\d)"),     # mobile number
    re.compile(r"(?<!\d)\d{2,3}[- ]?\d{3,4}[- ]?\d{4}(?!\d)"),    # landline number
    re.compile(r"(?<!\d)\d{6,}"),                                 # long identifier runs
    re.compile(r"(?i)(bearer|refresh[-_ ]?token|api[-_ ]?key|client[-_ ]?secret|cookie)"),
    re.compile(r"(?i)\.(pdf|xlsx|docx|csv|zip|png|jpg)\b"),       # attached file names
    re.compile(r"(?i)(usr_|session[_-]?id|workspace[_-]?ref|actor[_-]?ref|binding[_-]?ref)"),
    re.compile(r"(견적|단가|원가|계좌|주민등록|passport|여권번호|고객명|거래처|사내|비밀|기밀)"),
)


class ClawSearchOutcome(str, Enum):
    SEARCH = "search"
    NO_SEARCH = "no_search"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class ClawSearchJudgement:
    outcome: ClawSearchOutcome
    reason: str
    query: str = ""

    @property
    def public_query(self) -> str | None:
        return self.query or None


def _user_turns(messages: object) -> tuple[str, ...]:
    if not isinstance(messages, (list, tuple)):
        return ()
    turns: list[str] = []
    for item in messages:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            turns.append(" ".join(content.split()))
    return tuple(turns)


def is_private(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PRIVATE_PATTERNS)


def _normalize_query(text: str) -> str:
    return " ".join(text.split())[:MAX_PUBLIC_SEARCH_QUERY_CHARS].strip()


_REQUEST_TAIL_PHRASES = (
    "알려줘", "알려주세요", "확인해줘", "확인해주세요", "정리해줘", "요약해줘", "알고 싶어",
    "有什么", "教えて", "가 어떻게", "인가요", "입니까", "니?", "요?", "?", "요", "니",
)


def _strip_request_phrases(text: str) -> str:
    cleaned = text.strip().rstrip("?.!~ ")
    for phrase in _REQUEST_TAIL_PHRASES:
        if cleaned.endswith(phrase):
            cleaned = cleaned[: -len(phrase)].strip()
    return cleaned.rstrip("?.!~ ")


def _strip_deictic_opener(text: str) -> str:
    stripped = text.strip()
    lowered = stripped.lower()
    for start in _DEICTIC_STARTS:
        if lowered.startswith(start):
            return stripped[len(start):].strip()
    return stripped


def _points_at_earlier_context(text: str) -> bool:
    lowered = text.strip().lower()
    if any(lowered.startswith(start) for start in _DEICTIC_STARTS):
        return True
    return any(term in lowered for term in _DEICTIC_TERMS)


def _topic_from_prior_turns(priors: tuple[str, ...], year: int) -> str | None:
    """Most recent prior turn that is itself worth a public lookup and carries no private mark.

    Only the subject phrase is kept: freshness words and question endings are the current
    turn's job, and the year is supplied by the server clock rather than by conversation text.
    """

    for turn in reversed(priors[-_MAX_PRIOR_TURNS:]):
        if is_private(turn):
            continue
        try:
            decision = decide_search(turn, task_id="auto")
        except ValueError:
            continue
        if decision.disposition is SearchDisposition.NO_SEARCH:
            if not any(cue in turn for cue in _VOLATILE_PUBLIC_TOPICS):
                continue
            decision = SearchDecision(SearchDisposition.SHOULD_SEARCH, "volatile_public_topic", query=turn)
        topic = _normalize_query(_strip_request_phrases(turn.replace(str(year), "")))
        if len(topic) >= 4:
            return topic
    return None


def judge_claw_public_search(messages: object, *, now: datetime | None = None) -> ClawSearchJudgement:
    """Decide SEARCH / NO_SEARCH / CLARIFY and build the only text allowed to leave."""

    turns = _user_turns(messages)
    if not turns:
        return ClawSearchJudgement(ClawSearchOutcome.NO_SEARCH, "no_user_turn")
    current, priors = turns[-1], turns[:-1]
    year = (now or datetime.now(timezone.utc)).year

    try:
        decision = decide_search(current, task_id="auto")
    except ValueError:
        return ClawSearchJudgement(ClawSearchOutcome.NO_SEARCH, "decision_unavailable")

    if decision.disposition is SearchDisposition.NO_SEARCH:
        if not any(cue in current for cue in _VOLATILE_PUBLIC_TOPICS):
            return ClawSearchJudgement(ClawSearchOutcome.NO_SEARCH, decision.reason)
        # Core found no trigger, but the subject itself is a volatile public category.
        decision = SearchDecision(SearchDisposition.SHOULD_SEARCH, "volatile_public_topic", query=current)

    if is_private(current):
        # A volatile-fact question that carries customer data is answered from the
        # model's own knowledge or refused; the private material never becomes a query.
        return ClawSearchJudgement(ClawSearchOutcome.NO_SEARCH, "privacy_blocked")

    if not _points_at_earlier_context(current):
        query = _normalize_query(_strip_request_phrases(current))
        if is_private(query) or len(query) < 2:
            return ClawSearchJudgement(ClawSearchOutcome.NO_SEARCH, "privacy_blocked")
        return ClawSearchJudgement(
            ClawSearchOutcome.SEARCH, f"self_contained:{decision.reason}", query
        )

    topic = _topic_from_prior_turns(priors, year)
    if topic is None:
        # Context cannot be confirmed: do not guess a subject and do not egress.
        return ClawSearchJudgement(ClawSearchOutcome.CLARIFY, "follow_up_context_unresolved")

    residue = _normalize_query(_strip_request_phrases(
        re.sub("|".join(re.escape(term) for term in _DEICTIC_TERMS), " ", _strip_deictic_opener(current))
    ))
    parts = [str(year), topic]
    if len(residue) >= 3 and residue not in topic:
        parts.append(residue)
    query = _normalize_query(" ".join(parts))
    if is_private(query):
        return ClawSearchJudgement(ClawSearchOutcome.NO_SEARCH, "privacy_blocked")
    return ClawSearchJudgement(
        ClawSearchOutcome.SEARCH, f"follow_up:{decision.reason}", query
    )


__all__ = [
    "ClawSearchJudgement",
    "ClawSearchOutcome",
    "MAX_PUBLIC_SEARCH_QUERY_CHARS",
    "is_private",
    "judge_claw_public_search",
]
