from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class SearchDisposition(str, Enum):
    MUST_SEARCH = "must_search"
    SHOULD_SEARCH = "should_search"
    NO_SEARCH = "no_search"


@dataclass(frozen=True, slots=True)
class SearchDecision:
    disposition: SearchDisposition
    reason: str
    query: str

    @property
    def requires_search(self) -> bool:
        return self.disposition in {
            SearchDisposition.MUST_SEARCH,
            SearchDisposition.SHOULD_SEARCH,
        }

    @property
    def must_search(self) -> bool:
        return self.disposition is SearchDisposition.MUST_SEARCH


_EXPLICIT_SEARCH = (
    "검색",
    "찾아봐",
    "찾아 줘",
    "찾아줘",
    "웹에서",
    "인터넷에서",
    "온라인에서",
    "확인해줘",
    "확인해 줘",
    "검증해줘",
    "검증해 줘",
    "search the web",
    "look up",
    "check online",
    "verify online",
)

_FRESHNESS = (
    "오늘",
    "지금",
    "현재",
    "최신",
    "최근",
    "요즘",
    "금일",
    "실시간",
    "이번 주",
    "이번주",
    "이번 달",
    "이번달",
    "올해",
    "today",
    "now",
    "current",
    "latest",
    "recent",
    "this week",
    "this month",
    "this year",
    "live",
)

_VOLATILE_FACTS = (
    "뉴스",
    "날씨",
    "기온",
    "환율",
    "금리",
    "주가",
    "시세",
    "가격",
    "요금",
    "재고",
    "품절",
    "예약",
    "운영시간",
    "영업시간",
    "장애",
    "서비스 상태",
    "출시일",
    "릴리스",
    "업데이트",
    "버전",
    "news",
    "weather",
    "exchange rate",
    "interest rate",
    "stock price",
    "price",
    "availability",
    "outage",
    "release",
    "version",
)

_CURRENT_OFFICE = (
    "대통령",
    "국무총리",
    "총리",
    "장관",
    "시장 누구",
    "도지사",
    "현직",
    "대표이사",
    "ceo",
    "president",
    "prime minister",
    "minister",
    "office holder",
)

_SOURCE_BOUND_TASKS = frozenset({"translate", "summarize"})

_TRANSFORMATION_CUES = (
    "번역해",
    "번역해줘",
    "요약해",
    "요약해줘",
    "다듬어",
    "교정해",
    "고쳐 써",
    "고쳐써",
    "rewrite",
    "translate",
    "summarize",
    "proofread",
)

_CREATIVE_CUES = (
    "시 써",
    "소설",
    "이야기 만들어",
    "카피 써",
    "문구 써",
    "이메일 써",
    "창작",
    "brainstorm",
    "write a poem",
    "write a story",
)

_STABLE_CONCEPT_CUES = (
    "무슨 뜻",
    "뜻이 뭐",
    "개념",
    "원리",
    "쉽게 설명",
    "왜 그런",
    "what does",
    "concept",
    "explain",
)

_EXTERNAL_FACT_CUES = (
    "사실이야",
    "맞아?",
    "맞나요",
    "존재해",
    "출처",
    "통계",
    "연구",
    "논문",
    "정책",
    "법률",
    "법규",
    "규정",
    "사양",
    "스펙",
    "지원하",
    "추천",
    "비교해",
    "누구야",
    "언제야",
    "몇 년",
    "몇년",
    "is it true",
    "source",
    "statistics",
    "study",
    "paper",
    "policy",
    "regulation",
    "spec",
    "recommend",
    "compare",
)


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _looks_like_arithmetic(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(compact) and bool(re.fullmatch(r"[0-9.,()+\-*/%^=×÷]+", compact))


def decide_search(text: str, *, task_id: str | None = None) -> SearchDecision:
    """Classify whether a user request needs current external web evidence.

    The classifier is deliberately deterministic and bounded. It decides whether
    retrieval is needed; it never performs retrieval and it never grants tool or
    provider authority.
    """

    if not isinstance(text, str) or not text.strip():
        raise ValueError("search decision text must be a non-empty string")
    query = text.strip()
    normalized = query.casefold()
    resolved_task = (task_id or "auto").strip().casefold()

    if _contains_any(normalized, _EXPLICIT_SEARCH):
        return SearchDecision(SearchDisposition.MUST_SEARCH, "explicit_search_request", query)

    if _contains_any(normalized, _FRESHNESS):
        return SearchDecision(SearchDisposition.MUST_SEARCH, "freshness_sensitive", query)

    if _contains_any(normalized, _VOLATILE_FACTS):
        return SearchDecision(SearchDisposition.MUST_SEARCH, "volatile_external_fact", query)

    if _contains_any(normalized, _CURRENT_OFFICE):
        return SearchDecision(SearchDisposition.MUST_SEARCH, "current_office_holder", query)

    if resolved_task in _SOURCE_BOUND_TASKS:
        return SearchDecision(SearchDisposition.NO_SEARCH, "source_bound_transformation", query)

    if _contains_any(normalized, _TRANSFORMATION_CUES):
        return SearchDecision(SearchDisposition.NO_SEARCH, "user_text_transformation", query)

    if _contains_any(normalized, _CREATIVE_CUES):
        return SearchDecision(SearchDisposition.NO_SEARCH, "creative_request", query)

    if _looks_like_arithmetic(normalized):
        return SearchDecision(SearchDisposition.NO_SEARCH, "deterministic_arithmetic", query)

    if _contains_any(normalized, _EXTERNAL_FACT_CUES):
        return SearchDecision(SearchDisposition.SHOULD_SEARCH, "external_fact_verification", query)

    if _contains_any(normalized, _STABLE_CONCEPT_CUES):
        return SearchDecision(SearchDisposition.NO_SEARCH, "stable_concept_explanation", query)

    return SearchDecision(SearchDisposition.NO_SEARCH, "no_external_evidence_trigger", query)
