from __future__ import annotations

import pytest

from padiem_ai_core.search_decision import SearchDisposition, decide_search


@pytest.mark.parametrize(
    "prompt",
    [
        "오늘 AI 업계 최신 뉴스 알려줘",
        "지금 서울 날씨가 어때?",
        "원달러 환율 확인해줘",
        "이 제품 현재 가격이 얼마야?",
        "한국 대통령 누구야?",
        "웹에서 이 주장 사실인지 찾아봐",
        "What is the latest stable version of Python?",
    ],
)
def test_must_search_for_fresh_or_explicit_external_facts(prompt: str) -> None:
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.requires_search is True
    assert decision.must_search is True
    assert decision.query == prompt


@pytest.mark.parametrize(
    "prompt",
    [
        "이 연구 결과가 사실이야?",
        "이 논문의 출처를 설명해줘",
        "두 서비스의 지원 정책을 비교해줘",
        "광주에서 가족 식사 장소 추천해줘",
    ],
)
def test_should_search_for_external_verification(prompt: str) -> None:
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.SHOULD_SEARCH
    assert decision.requires_search is True
    assert decision.must_search is False


@pytest.mark.parametrize(
    ("prompt", "task_id"),
    [
        ("이 문장을 영어로 번역해줘", "translate"),
        ("붙여넣은 글을 세 줄로 요약해줘", "summarize"),
        ("문장을 자연스럽게 다듬어줘", "write"),
        ("가을에 관한 짧은 시 써줘", "auto"),
        ("중력의 원리를 쉽게 설명해줘", "explain"),
        ("12 * (3 + 4)", "auto"),
    ],
)
def test_no_search_for_source_bound_creative_math_or_stable_concepts(prompt: str, task_id: str) -> None:
    decision = decide_search(prompt, task_id=task_id)
    assert decision.disposition is SearchDisposition.NO_SEARCH
    assert decision.requires_search is False


def test_freshness_overrides_source_bound_task() -> None:
    decision = decide_search("오늘 공개된 보도자료를 찾아서 요약해줘", task_id="summarize")
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.reason in {"explicit_search_request", "freshness_sensitive"}


@pytest.mark.parametrize(
    "prompt",
    [
        "오늘 며칠이야?",
        "오늘 무슨 요일이야?",
        "지금 몇 시야?",
        "내일은 무슨 요일이야?",
        "아니 오늘 집에 있을거야 근데 오늘 며칠인지나 알아?",
    ],
)
def test_current_calendar_questions_never_need_web_evidence(prompt: str) -> None:
    # The trusted dispatch pre-instruction already carries the server clock, so
    # a date/weekday/time question is answered from the system time and must
    # never become a search-required request.
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.NO_SEARCH
    assert decision.requires_search is False
    assert decision.evidence_required is False
    assert decision.reason == "local_clock_fact"


def test_a_current_weather_request_still_needs_web_evidence() -> None:
    decision = decide_search("오늘 광주 날씨 알려줘")
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.evidence_required is True


def test_an_explicit_lookup_keeps_its_evidence_required() -> None:
    decision = decide_search("오늘 공개된 AI 정책을 찾아서 알려줘")
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.evidence_required is True
    assert decision.reason == "explicit_search_request"


def test_a_bare_freshness_statement_may_continue_without_evidence() -> None:
    # The search is still attempted, but the statement needs no current fact,
    # so a search without usable evidence may continue as a normal answer.
    decision = decide_search("오늘은 집에 있을 거야.")
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.evidence_required is False


def test_a_local_text_transformation_is_not_hijacked_by_a_lookup_word() -> None:
    decision = decide_search("이 문장 찾아서 고쳐줘")
    assert decision.disposition is SearchDisposition.NO_SEARCH
    assert decision.requires_search is False


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        # 1. the current date, weekday and time are server-clock facts
        ("오늘 며칠이야?", SearchDisposition.NO_SEARCH),
        ("오늘 무슨 요일이야?", SearchDisposition.NO_SEARCH),
        ("지금 몇 시야?", SearchDisposition.NO_SEARCH),
        ("What time is it?", SearchDisposition.NO_SEARCH),
        # 2. a published event schedule is a web fact
        ("몇 시에 경기가 시작해?", SearchDisposition.MUST_SEARCH),
        ("What time is the concert tonight?", SearchDisposition.MUST_SEARCH),
        # 3. the latest news is a web fact
        ("오늘 AI 뉴스 알려줘", SearchDisposition.MUST_SEARCH),
        # 4. a current office holder is a web fact
        ("현재 대통령", SearchDisposition.MUST_SEARCH),
        # 5. the weather is a web fact
        ("오늘 날씨 어때?", SearchDisposition.MUST_SEARCH),
        ("지금 비 와?", SearchDisposition.MUST_SEARCH),
        # 6. a price is a web fact
        ("파스 주가는 얼마지?", SearchDisposition.MUST_SEARCH),
        # 7. ordinary conversation is not
        ("고마워", SearchDisposition.NO_SEARCH),
        ("비 오는구나", SearchDisposition.NO_SEARCH),
        # 8. a document transformation is not
        ("이 문장 번역해줘", SearchDisposition.NO_SEARCH),
        ("rewrite this paragraph", SearchDisposition.NO_SEARCH),
    ],
)
def test_the_search_intent_classes_stay_separated(
    prompt: str, expected: SearchDisposition,
) -> None:
    decision = decide_search(prompt)
    assert decision.disposition is expected
    if expected is SearchDisposition.MUST_SEARCH:
        assert decision.evidence_required is True


@pytest.mark.parametrize(
    "prompt",
    [
        "이번 주 무슨 요일에 축제가 열려?",
        "What time is the concert tonight?",
    ],
)
def test_an_external_event_or_schedule_is_not_a_clock_question(prompt: str) -> None:
    # The day or time of an external event is a web fact, not the server clock.
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.requires_search is True
    assert decision.evidence_required is True
    assert decision.reason != "local_clock_fact"


@pytest.mark.parametrize(
    "prompt",
    [
        "현재 대통령",
        "현재 CEO",
    ],
)
def test_a_current_office_holder_never_takes_the_no_evidence_fallback(
    prompt: str,
) -> None:
    # A current office holder is a current external fact: the answer must never
    # continue without retrieved evidence.
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.evidence_required is True
    assert decision.reason != "local_clock_fact"


@pytest.mark.parametrize(
    "prompt",
    [
        "몇 시에 경기가 시작해?",
        "무슨 요일에 파이팅 열려?",
        "영화는 몇 시에 시작해요?",
        "콘서트 언제 열려?",
        "공연은 몇 시에 시작해?",
        "행사 시작 시각 알려줘",
        "팝콘 언제 팔려?",
        "What time is the concert tonight?",
    ],
)
def test_a_published_event_schedule_needs_web_evidence(prompt: str) -> None:
    # The published day or time of an external event is a web fact. It used to
    # fall through to "no external evidence trigger" and the product answered a
    # third-party schedule from memory.
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.requires_search is True
    assert decision.evidence_required is True
    assert decision.reason == "external_event_schedule"


@pytest.mark.parametrize(
    "prompt",
    [
        "회의록 요약해줘",
        "공연 문장 번역해줘",
        "영화 시나리오 작성해줘",
        "팝콘 레시피 알려줘",
    ],
)
def test_an_event_word_alone_never_forces_a_web_search(prompt: str) -> None:
    # Only the published time of an event is a web fact. A request that merely
    # mentions the event keeps the ordinary processing path.
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.NO_SEARCH
    assert decision.requires_search is False
    assert decision.evidence_required is False


@pytest.mark.parametrize(
    "prompt",
    [
        "지금 비 와?",
        "지금 비 와요?",
        "지금 눈 와?",
        "is it raining in Seoul right now",
    ],
)
def test_a_current_condition_question_needs_web_evidence(prompt: str) -> None:
    # A current condition asked as a question is a web fact. It used to be
    # classified so that a failed search could continue as a normal answer, and
    # the product could state the current weather without evidence.
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.requires_search is True
    assert decision.evidence_required is True
    assert decision.reason == "current_condition_question"


@pytest.mark.parametrize(
    "prompt",
    [
        "비 오는구나",
        "지금 비 온다",
    ],
)
def test_a_current_condition_remark_never_requires_evidence(prompt: str) -> None:
    # A remark about the weather is not a request for verified weather. The
    # search may still be attempted, but a failed search may continue as an
    # ordinary answer, and it never asserts the current weather as fact.
    decision = decide_search(prompt)
    assert decision.evidence_required is False
    if decision.disposition is SearchDisposition.NO_SEARCH:
        assert decision.requires_search is False


@pytest.mark.parametrize(
    "prompt",
    [
        "몇 시에 만나요?",
        "내일 몇 시에 모임이야?",
    ],
)
def test_the_users_own_plan_is_not_a_published_schedule(prompt: str) -> None:
    # The user's own appointment belongs to the product's calendar lane, not to
    # a published web schedule.
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.NO_SEARCH
    assert decision.requires_search is False


def test_blank_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        decide_search("   ")
