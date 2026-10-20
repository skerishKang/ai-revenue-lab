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
    # Whether the answer may NOT be produced without retrieved web evidence.
    # A search can be attempted for a request whose answer does not depend on
    # it (a bare "today ..." question), so a failed automatic search may still
    # continue as a normal answer. A request about weather, news, rates or any
    # other current external fact keeps the honest failure instead.
    evidence_required: bool = True

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
    "tonight",
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

# A freshness word that only states the user's own situation needs no current
# fact ("오늘은 집에 있을 거야"). A request that asks for current information
# does, so its search failure stays an honest error instead of a normal answer.
_INFORMATION_REQUEST = (
    "알려",
    "알아봐",
    "알아보고",
    "어때",
    "어떤",
    "어떻게",
    "무엇",
    "뭐",
    "무슨",
    "얼마",
    "누구",
    "몇",
    "맞나",
    "맞지",
    "있나",
    "있어",
    "tell me",
    "what",
    "how",
    "who",
    "when",
    "which",
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


# "찾아서" also appears in a LOCAL text transformation ("이 문장 찾아서 고쳐줘"),
# so the lookup form is only an explicit search when the found information is
# asked to be reported.
_LOOKUP_REPORT = re.compile(
    r"찾아서\s*(?:알려|알려줘|알려주세요|정리|정리해|정리해줘|요약|요약해|요약해줘"
    r"|보여|보여줘|설명|설명해|전달|전달해|답변|답변해)"
)


def _looks_like_arithmetic(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(compact) and bool(re.fullmatch(r"[0-9.,()+\-*/%^=×÷]+", compact))


# The current date, weekday and time of day are server facts, not web facts.
# The trusted dispatch pre-instruction already carries the server clock, so a
# question about the calendar must never become a web-evidence request.
_CLOCK_CLAUSE_SEPARATORS = (
    "근데", "그런데", "그리고", "그래서", "but", "and", ",", "，", "。", ";", "；",
)
# A pure clock question asks for the current date, weekday or time AS SUCH.
# "오늘 무슨 요일이야?" is a clock question; "무슨 요일에 축제가 열려?" asks for
# the schedule of an external event and stays a web-evidence request.
_CLOCK_EVENT_TIME_FORM = re.compile(
    r"(?:며칠|무슨\s*요일|무슨\s*날짜|몇\s*시|몇\s*시간)\s*에"
)
# The English form is the self-referential one: "What time is it?" asks for the
# clock, "What time is the concert tonight?" asks for an external schedule.
_CLOCK_QUESTION_SUFFIX_EN = re.compile(
    r"(?:what\s+time\s+is\s+it|what'?s\s+the\s+time|what\s+day\s+is\s+it"
    r"|what'?s\s+(?:today'?s\s+)?(?:the\s+)?date"
    r"|what\s+day\s+of\s+the\s+week\s+is\s+it)"
    r"\s*[?.!]*$",
    re.IGNORECASE,
)
# An external event, a business schedule or a booking time is a web fact even
# when the question mentions today, tonight or a weekday. The plan words
# ("약속", "모임") stay out: the user's own appointment is not a published
# schedule and belongs to the product's own calendar lane.
_EXTERNAL_SCHEDULE_MARKERS = (
    "축제",
    "공연",
    "콘서트",
    "경기",
    "회의",
    "행사",
    "상영",
    "상영회",
    "발매",
    "세미나",
    "워크숍",
    "전시",
    "전시회",
    "영화",
    "항공",
    "기차",
    "파티",
    "파이팅",
    "팝콘",
    "티켓",
    "영업",
    "휴무",
    "개장",
    "마감",
    "열려",
    "concert",
    "festival",
    "game",
    "match",
    "meeting",
    "schedule",
    "event",
    "movie",
    "film",
    "screening",
    "flight",
    "train",
    "show",
    "workshop",
    "seminar",
    "opening",
    "closing",
    "ticket",
)
# A current condition (rain, snow, fog) is a web fact when the request asks
# about it. The casual remark form ("비 오는구나") stays ordinary conversation.
_CURRENT_CONDITION_CUES = (
    "비가",
    "비 와",
    "비 와요",
    "비올",
    "눈이",
    "눈 와",
    "눈 와요",
    "소나기",
    "천둥",
    "안개",
    "폭염",
    "한파",
    "우박",
    "서리",
    "영하",
    "영싱",
    "흐림",
    "맑음",
    "습도",
    "raining",
    "rains",
    "snowing",
    "snows",
    "foggy",
    "cloudy",
    "sunny",
    "temperature",
    "humidity",
    "thunder",
)
# The interrogative forms that turn a current condition into a real question.
# The information-request markers already carry the Korean and English question
# vocabulary; the explicit question forms cover the rest.
_QUESTION_FORMS = (
    "?",
    "is it",
    "is there",
    "are there",
    "does it",
    "do i",
    "do you",
    "will it",
    "tell me",
    "find out",
)



def _last_clause(text: str) -> str:
    """The final clause of a request, where a closing question lives."""
    clause = text
    for separator in _CLOCK_CLAUSE_SEPARATORS:
        index = clause.rfind(separator)
        if index >= 0:
            clause = clause[index + len(separator):]
    return clause.strip()


def _is_local_clock_question(normalized: str) -> bool:
    """Whether the request only asks for the current date, weekday or time.

    A self-contained clock question is answered by the server clock that the
    dispatch pre-instruction already provides. A request that names a current
    external fact (weather, news, rates, an office holder) or an external
    event/schedule (a festival, a concert, business hours) is not a clock
    question and keeps the existing web-evidence path.
    """
    if _contains_any(normalized, _VOLATILE_FACTS) or _contains_any(
        normalized, _CURRENT_OFFICE
    ):
        return False
    if _contains_any(normalized, _EXTERNAL_SCHEDULE_MARKERS):
        return False
    if _is_current_condition_question(normalized):
        return False
    clause = _last_clause(normalized)
    if not clause:
        return False
    # "무슨 요일에 축제가 열려?" asks for an external schedule, not the clock.
    if _CLOCK_EVENT_TIME_FORM.search(clause):
        return False
    if _CLOCK_QUESTION_SUFFIX_EN.search(clause):
        return True
    if "요일" in clause:
        return True
    if "며칠" in clause and "걸" not in clause:
        return True
    if "날짜" in clause and _contains_any(clause, ("오늘", "내일", "어제", "지금", "현재")):
        return True
    if re.search(r"몇\s*시(?!에)", clause):
        return True
    if re.search(r"(?:현재|지금)\s*시간", clause):
        return True
    return False


def _is_current_condition_question(normalized: str) -> bool:
    """Whether the request asks about a current external condition.

    "지금 비 와?" asks for the weather right now, so it is a web-evidence
    question. "비 오는구나" is an ordinary remark and stays one.
    """
    if not _contains_any(normalized, _CURRENT_CONDITION_CUES):
        return False
    if _contains_any(normalized, _QUESTION_FORMS):
        return True
    return _contains_any(normalized, _INFORMATION_REQUEST)



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

    if _contains_any(normalized, _EXPLICIT_SEARCH) or _LOOKUP_REPORT.search(normalized):
        return SearchDecision(
            SearchDisposition.MUST_SEARCH, "explicit_search_request", query
        )

    # The published day or time of an external event, a business schedule or a
    # booking is a web fact, never the server clock. Without this the request
    # fell through to "no external evidence trigger" and the product answered a
    # third-party schedule from memory.
    if _contains_any(normalized, _EXTERNAL_SCHEDULE_MARKERS):
        return SearchDecision(
            SearchDisposition.MUST_SEARCH, "external_event_schedule", query,
            evidence_required=True,
        )

    # A current condition (rain, snow, fog) asked as a question is a web fact
    # too. Without this the freshness branch treated it as a request that may
    # continue as a normal answer, and the product could state the current
    # weather without any evidence.
    if _is_current_condition_question(normalized):
        return SearchDecision(
            SearchDisposition.MUST_SEARCH, "current_condition_question", query,
            evidence_required=True,
        )

    # A calendar/clock question is answered by the server clock, never by the
    # web. It must not become a search-required request.
    if _is_local_clock_question(normalized):
        return SearchDecision(
            SearchDisposition.NO_SEARCH, "local_clock_fact", query,
            evidence_required=False,
        )

    if _contains_any(normalized, _FRESHNESS):
        # A freshness word alone does not prove the answer needs the web: the
        # search is still attempted, but a request that neither names a current
        # external fact nor asks for information may continue as a normal answer
        # when no usable evidence is found. A current office holder always
        # needs evidence, so it never takes that fallback.
        return SearchDecision(
            SearchDisposition.MUST_SEARCH, "freshness_sensitive", query,
            evidence_required=(
                _contains_any(normalized, _VOLATILE_FACTS)
                or _contains_any(normalized, _CURRENT_OFFICE)
                or _contains_any(normalized, _INFORMATION_REQUEST)
            ),
        )

    if _contains_any(normalized, _VOLATILE_FACTS):
        return SearchDecision(
            SearchDisposition.MUST_SEARCH, "volatile_external_fact", query
        )

    if _contains_any(normalized, _CURRENT_OFFICE):
        return SearchDecision(
            SearchDisposition.MUST_SEARCH, "current_office_holder", query
        )

    if resolved_task in _SOURCE_BOUND_TASKS:
        return SearchDecision(
            SearchDisposition.NO_SEARCH, "source_bound_transformation", query,
            evidence_required=False,
        )

    if _contains_any(normalized, _TRANSFORMATION_CUES):
        return SearchDecision(
            SearchDisposition.NO_SEARCH, "user_text_transformation", query,
            evidence_required=False,
        )

    if _contains_any(normalized, _CREATIVE_CUES):
        return SearchDecision(
            SearchDisposition.NO_SEARCH, "creative_request", query,
            evidence_required=False,
        )

    if _looks_like_arithmetic(normalized):
        return SearchDecision(
            SearchDisposition.NO_SEARCH, "deterministic_arithmetic", query,
            evidence_required=False,
        )

    if _contains_any(normalized, _EXTERNAL_FACT_CUES):
        return SearchDecision(
            SearchDisposition.SHOULD_SEARCH, "external_fact_verification", query,
            evidence_required=True,
        )

    if _contains_any(normalized, _STABLE_CONCEPT_CUES):
        return SearchDecision(
            SearchDisposition.NO_SEARCH, "stable_concept_explanation", query,
            evidence_required=False,
        )

    # No web evidence is requested at all, so no answer depends on it.
    return SearchDecision(
        SearchDisposition.NO_SEARCH, "no_external_evidence_trigger", query,
        evidence_required=False,
    )
