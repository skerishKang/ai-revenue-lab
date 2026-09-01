"""Deterministic source-quality selection for grounded web evidence.

This module ranks and filters retrieved evidence before it becomes model context.
It does not claim that a source is true or false, does not replace claim-level
verification, and does not grant tool/provider authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Sequence
from urllib.parse import urlsplit

from .contracts import Evidence
from .search_decision import SearchDecision, SearchDisposition, decide_search
from .web_runtime import normalize_public_url

MAX_QUALITY_CANDIDATES = 32
MAX_DOMAIN_HINTS = 64
MAX_SELECTED_SOURCES = 10

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣._+-]*", re.UNICODE)

# These are retrieval-language/freshness cues rather than subject-matter terms.
# Keeping them out of relevance scoring prevents a result from passing merely
# because both the query and page say e.g. "current" or "latest".
_QUERY_STOPWORDS = frozenset(
    {
        "현재",
        "지금",
        "오늘",
        "최신",
        "최근",
        "요즘",
        "검색",
        "검색해",
        "검색해서",
        "찾아봐",
        "찾아줘",
        "확인",
        "확인해줘",
        "알려줘",
        "알려주세요",
        "뭐야",
        "무엇",
        "맞아",
        "맞지",
        "웹에서",
        "인터넷에서",
        "current",
        "latest",
        "recent",
        "today",
        "now",
        "search",
        "verify",
        "online",
        "web",
        "tell",
        "me",
        "please",
    }
)

_COMMUNITY_SUFFIXES = (
    "dcinside.com",
    "fmkorea.com",
    "reddit.com",
    "quora.com",
    "namu.wiki",
)

_COMMUNITY_INTENT_CUES = (
    "반응",
    "후기",
    "경험",
    "사용기",
    "커뮤니티",
    "사람들 생각",
    "사람들 의견",
    "평가 어때",
    "여론",
    "reddit",
    "community",
    "reviews",
    "user experience",
    "what do people think",
)


class SourceTier(str, Enum):
    PRIMARY = "primary"
    TRUSTED_SECONDARY = "trusted_secondary"
    GENERAL = "general"
    COMMUNITY = "community"


@dataclass(frozen=True, slots=True)
class SourceQualityPolicy:
    """Bounded, product-neutral source selection policy.

    Domain hints are optional caller-owned context. They let a product/task state
    that a known official source (for example a central bank or the product's own
    documentation) is authoritative without baking a giant global allowlist into
    Core.
    """

    authoritative_domains: tuple[str, ...] = ()
    trusted_secondary_domains: tuple[str, ...] = ()
    min_relevance_score: float = 0.18
    max_candidates: int = MAX_QUALITY_CANDIDATES
    max_selected_sources: int = 5

    def __post_init__(self) -> None:
        for name in ("authoritative_domains", "trusted_secondary_domains"):
            raw = getattr(self, name)
            if not isinstance(raw, tuple):
                raw = tuple(raw)
            if len(raw) > MAX_DOMAIN_HINTS:
                raise ValueError(f"{name} exceeds the bounded domain-hint limit")
            normalized = tuple(_normalize_domain_hint(item) for item in raw)
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{name} must not contain duplicates")
            object.__setattr__(self, name, normalized)
        if set(self.authoritative_domains) & set(self.trusted_secondary_domains):
            raise ValueError("a domain cannot be both authoritative and trusted-secondary")
        if (
            isinstance(self.min_relevance_score, bool)
            or not isinstance(self.min_relevance_score, (int, float))
            or not 0.0 <= float(self.min_relevance_score) <= 1.0
        ):
            raise ValueError("min_relevance_score must be between 0 and 1")
        object.__setattr__(self, "min_relevance_score", float(self.min_relevance_score))
        if (
            isinstance(self.max_candidates, bool)
            or not isinstance(self.max_candidates, int)
            or not 1 <= self.max_candidates <= MAX_QUALITY_CANDIDATES
        ):
            raise ValueError(f"max_candidates must be between 1 and {MAX_QUALITY_CANDIDATES}")
        if (
            isinstance(self.max_selected_sources, bool)
            or not isinstance(self.max_selected_sources, int)
            or not 1 <= self.max_selected_sources <= MAX_SELECTED_SOURCES
        ):
            raise ValueError(f"max_selected_sources must be between 1 and {MAX_SELECTED_SOURCES}")


@dataclass(frozen=True, slots=True)
class SourceQualityAssessment:
    evidence: Evidence
    tier: SourceTier
    relevance_score: float
    authority_score: float
    total_score: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, Evidence):
            raise ValueError("evidence must be Evidence")
        if not isinstance(self.tier, SourceTier):
            raise ValueError("tier must be SourceTier")
        for name in ("relevance_score", "authority_score", "total_score"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, round(float(value), 6))
        if not isinstance(self.reasons, tuple) or any(not isinstance(item, str) or not item for item in self.reasons):
            raise ValueError("reasons must be a tuple of non-empty strings")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence.id,
            "tier": self.tier.value,
            "relevance_score": self.relevance_score,
            "authority_score": self.authority_score,
            "total_score": self.total_score,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class SourceQualitySelection:
    evidence: tuple[Evidence, ...]
    assessments: tuple[SourceQualityAssessment, ...]
    rejected_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, tuple) or any(not isinstance(item, Evidence) for item in self.evidence):
            raise ValueError("evidence must be a tuple of Evidence")
        if not isinstance(self.assessments, tuple) or any(
            not isinstance(item, SourceQualityAssessment) for item in self.assessments
        ):
            raise ValueError("assessments must be a tuple of SourceQualityAssessment")
        if isinstance(self.rejected_count, bool) or not isinstance(self.rejected_count, int) or self.rejected_count < 0:
            raise ValueError("rejected_count must be a non-negative integer")


def _normalize_domain_hint(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("domain hint must be a string")
    raw = value.strip().lower().rstrip(".")
    if not raw or len(raw) > 253 or "/" in raw or ":" in raw or " " in raw:
        raise ValueError("domain hint must be a plain hostname")
    try:
        normalized = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("domain hint is invalid") from exc
    if not re.fullmatch(r"[a-z0-9.-]+", normalized) or normalized.startswith(".") or ".." in normalized:
        raise ValueError("domain hint is invalid")
    return normalized


def _host_for(evidence: Evidence) -> str:
    if not evidence.url:
        return ""
    try:
        normalized = normalize_public_url(evidence.url)
        return (urlsplit(normalized).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _domain_matches(host: str, hint: str) -> bool:
    return bool(host) and (host == hint or host.endswith("." + hint))


def _is_generic_official_domain(host: str) -> bool:
    if not host:
        return False
    # Korean government domains are explicit. For global domains, only a literal
    # gov label near the registrable suffix is treated as an official signal.
    if host.endswith(".go.kr"):
        return True
    labels = host.split(".")
    return "gov" in labels[-3:]


def _tier_for(host: str, policy: SourceQualityPolicy) -> tuple[SourceTier, str]:
    if any(_domain_matches(host, hint) for hint in policy.authoritative_domains):
        return SourceTier.PRIMARY, "authoritative_domain_hint"
    if _is_generic_official_domain(host):
        return SourceTier.PRIMARY, "official_domain_pattern"
    if any(_domain_matches(host, hint) for hint in policy.trusted_secondary_domains):
        return SourceTier.TRUSTED_SECONDARY, "trusted_secondary_domain_hint"
    if any(_domain_matches(host, suffix) for suffix in _COMMUNITY_SUFFIXES):
        return SourceTier.COMMUNITY, "community_domain"
    return SourceTier.GENERAL, "general_web_domain"


def _tokens(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(value))


def _significant_query_tokens(query: str) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for token in _tokens(query):
        if token in _QUERY_STOPWORDS or len(token) < 2 or token in seen:
            continue
        seen.add(token)
        result.append(token)
    if result:
        return tuple(result)
    # If every token is a cue, keep the bounded original tokens rather than making
    # every page equally relevant.
    return tuple(dict.fromkeys(token for token in _tokens(query) if len(token) >= 2))


def _community_intent(query: str) -> bool:
    normalized = query.casefold()
    return any(cue in normalized for cue in _COMMUNITY_INTENT_CUES)


def _relevance(query: str, evidence: Evidence) -> tuple[float, tuple[str, ...]]:
    query_terms = _significant_query_tokens(query)
    if not query_terms:
        return 0.0, ("no_significant_query_terms",)

    title_tokens = set(_tokens(evidence.title))
    snippet_tokens = set(_tokens(evidence.snippet))
    host_tokens = set(_tokens(_host_for(evidence).replace(".", " ")))

    title_matches = tuple(term for term in query_terms if term in title_tokens)
    snippet_matches = tuple(term for term in query_terms if term in snippet_tokens)
    host_matches = tuple(term for term in query_terms if term in host_tokens)
    any_matches = set(title_matches) | set(snippet_matches) | set(host_matches)

    # Exact token matching is intentional: a Korean entity such as `파디엠` must
    # not become relevant merely because a result contains the shorter token `디엠`.
    if not any_matches:
        return 0.0, ("no_exact_query_token_match",)

    count = len(query_terms)
    title_coverage = len(set(title_matches)) / count
    snippet_coverage = len(set(snippet_matches)) / count
    host_coverage = len(set(host_matches)) / count

    normalized_query = " ".join(query_terms)
    normalized_title = " ".join(_tokens(evidence.title))
    phrase_bonus = 0.15 if normalized_query and normalized_query in normalized_title else 0.0

    score = min(
        1.0,
        (0.5 * title_coverage)
        + (0.3 * snippet_coverage)
        + (0.05 * host_coverage)
        + phrase_bonus,
    )
    reasons: list[str] = []
    if title_matches:
        reasons.append("query_term_in_title")
    if snippet_matches:
        reasons.append("query_term_in_snippet")
    if host_matches:
        reasons.append("query_term_in_host")
    if phrase_bonus:
        reasons.append("query_phrase_in_title")
    return score, tuple(reasons)


def assess_source_quality(
    query: str,
    evidence: Evidence,
    *,
    decision: SearchDecision | None = None,
    policy: SourceQualityPolicy | None = None,
) -> SourceQualityAssessment:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(evidence, Evidence):
        raise ValueError("evidence must be Evidence")
    resolved_policy = policy or SourceQualityPolicy()
    resolved_decision = decision or decide_search(query)
    if not isinstance(resolved_decision, SearchDecision):
        raise ValueError("decision must be SearchDecision")

    host = _host_for(evidence)
    tier, tier_reason = _tier_for(host, resolved_policy)
    relevance, relevance_reasons = _relevance(query, evidence)
    community_intent = _community_intent(query)

    authority = {
        SourceTier.PRIMARY: 1.0,
        SourceTier.TRUSTED_SECONDARY: 0.78,
        SourceTier.GENERAL: 0.5,
        SourceTier.COMMUNITY: 0.22,
    }[tier]
    if community_intent and tier is SourceTier.COMMUNITY:
        authority = 0.72

    if resolved_decision.disposition is SearchDisposition.MUST_SEARCH:
        relevance_weight, authority_weight = 0.58, 0.42
    elif resolved_decision.disposition is SearchDisposition.SHOULD_SEARCH:
        relevance_weight, authority_weight = 0.66, 0.34
    else:
        relevance_weight, authority_weight = 0.72, 0.28

    total = (relevance * relevance_weight) + (authority * authority_weight)
    reasons = list(relevance_reasons)
    reasons.append(tier_reason)
    if community_intent:
        reasons.append("community_intent")
    return SourceQualityAssessment(
        evidence=evidence,
        tier=tier,
        relevance_score=relevance,
        authority_score=authority,
        total_score=min(1.0, total),
        reasons=tuple(reasons),
    )


def select_grounding_evidence(
    query: str,
    evidence_items: Sequence[Evidence],
    *,
    decision: SearchDecision | None = None,
    policy: SourceQualityPolicy | None = None,
    limit: int | None = None,
) -> SourceQualitySelection:
    """Filter, deduplicate and rank evidence for model grounding.

    Provider order is never trusted as truth authority. A rejected result is only
    considered unsuitable for this query/context; the function does not assert
    that the underlying page is false.
    """

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    resolved_policy = policy or SourceQualityPolicy()
    resolved_decision = decision or decide_search(query)
    resolved_limit = resolved_policy.max_selected_sources if limit is None else limit
    if (
        isinstance(resolved_limit, bool)
        or not isinstance(resolved_limit, int)
        or not 1 <= resolved_limit <= MAX_SELECTED_SOURCES
    ):
        raise ValueError(f"limit must be between 1 and {MAX_SELECTED_SOURCES}")

    unique: list[Evidence] = []
    seen_urls: set[str] = set()
    considered = 0
    for item in evidence_items:
        if considered >= resolved_policy.max_candidates:
            break
        if not isinstance(item, Evidence):
            continue
        considered += 1
        if not item.url:
            continue
        try:
            canonical = normalize_public_url(item.url)
        except ValueError:
            continue
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        unique.append(item)

    assessments = [
        assess_source_quality(
            query,
            item,
            decision=resolved_decision,
            policy=resolved_policy,
        )
        for item in unique
    ]
    accepted = [
        item
        for item in assessments
        if item.relevance_score >= resolved_policy.min_relevance_score
    ]
    accepted.sort(
        key=lambda item: (
            -item.total_score,
            -item.relevance_score,
            item.evidence.url or "",
            item.evidence.id,
        )
    )
    selected_assessments = tuple(accepted[:resolved_limit])
    return SourceQualitySelection(
        evidence=tuple(item.evidence for item in selected_assessments),
        assessments=selected_assessments,
        rejected_count=max(0, len(unique) - len(selected_assessments)),
    )
