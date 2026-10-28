"""#6090 load-bearing regression: general Chat long input must never be a 422.

실서비스 재현(로컬 하네스 실측):

- `POST /api/chat` 은 대화 본문 길이를 제한하지 않는다. 240,022자 일반 글은 200 으로 답했다.
- 같은 240,022자에 흔한 신선도 단어 하나("지금")가 들어가면 Core 자동검색 판정이
  MUST_SEARCH(freshness_sensitive) 를 내고, 판정 쿼리는 **본문 전문**이다. 그 본문이
  검색 제공자 질의 계약(2,000자)을 넘는 순간 `GroundingError(422, invalid_tool_input,
  "검색어는 1자 이상 2000자 이하로 입력해 주세요.")` 가 대화 전체를 죽였다.
- 즉 사용자가 쓴 글의 길이가 문제가 아니라, **긴 글을 검색 질의로 넘긴 분기**가 원인이다.

그래서 본문이 검색 질의가 될 수 없는 크기일 때:
  * 자동 분기는 검색을 시도하지 않고(본문 외부 전송 없음) 답변을 계속한다.
  * 현재 사실 질문이면 모델이 기억으로 답하지 않도록 한국어 안내를 붙인다.
  * 사용자가 직접 검색을 요청한 경우에도 422 대신 같은 한국어 안내 + 자동 대안으로 강등한다.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.auto_grounding import (
    AUTOMATIC_SEARCH_OVER_QUERY_CAP,
    AutoGroundingService,
)
from app.config import Settings
from app.evidence import Evidence
from app.grounding import GroundedChatService
from app.main import create_app
import app.model_policy as model_policy_module
from app.model_policy import DEFAULT_B14_MODEL_ID
from app.web_tools import (
    MAX_QUERY_CHARS,
    SEARCH_QUERY_TOO_LONG_CODE,
    SEARCH_QUERY_TOO_LONG_MESSAGE,
)
from padiem_ai_core.search_decision import decide_search


@pytest.fixture(autouse=True)
def _selected_model_for_grounding_contract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(model_policy_module, "EXECUTABLE_B14_MODEL_IDS", frozenset({DEFAULT_B14_MODEL_ID}))


# 일반 Chat 장문. 실제 사용자가 붙여 넣는 문서·회의록 크기(20만 자)를 그대로 쓴다.
BODY = "가나다라마바사 " * 30_000                    # 240,000자
DOCUMENT = "지금 정리 중인 초안입니다. " + BODY          # 흔한 신선도 단어 포함
CURRENT_FACT = "지금 서울 날씨 알려줘. " + BODY          # 실제 최신 사실 질문
SHORT = "이 문장을 다듬어 주세요."
SHORT_CURRENT_FACT = "지금 서울 날씨 알려줘."


class RecordingProvider:
    _automatic_search_enabled = True

    def __init__(self) -> None:
        self.search_calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.search_calls.append((query, limit))
        return [Evidence(
            id=f"u_{i}", title=f"소스 {i}", url=f"https://example.com/{i}",
            snippet=f"근거 {i}", retrieved_at="2026-10-29T00:00:00Z",
            provider="test", source_type="search",
        ) for i in range(1, limit + 1)]

    async def fetch(self, url: str):
        raise AssertionError("automatic search must not fetch pages")


def _b14_body() -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "정리한 답변입니다."}}],
        "business14": {
            "request_id": "b14req_6090", "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID, "selected_provider": "Poolside",
        },
    }


def _stream_body() -> bytes:
    payload = {
        "id": "stream_6090", "object": "chat.completion.chunk", "model": DEFAULT_B14_MODEL_ID,
        "choices": [{"index": 0, "delta": {"content": "정리한 답변입니다."}, "finish_reason": None}],
        "business14": {
            "request_id": "b14req_6090", "route_mode": "manual",
            "selected_provider": "Poolside", "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_upstream_model": "poolside/laguna-s-2.1", "fallback_used": False, "attempt_count": 1,
        },
    }
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n" + b"data: [DONE]\n\n"


def build_app(seen: list[dict], *, stream: bool = False):
    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if stream:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_stream_body())
        return httpx.Response(200, json=_b14_body())

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example", web_provider="mock"),
        transport=httpx.MockTransport(handler),
    )
    provider = RecordingProvider()
    app.state.web_provider = provider
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, provider)
    app.state.auto_grounding = AutoGroundingService(provider)
    return app, provider


async def post(payload: dict, *, stream: bool = False):
    seen: list[dict] = []
    app, provider = build_app(seen, stream=stream)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat/stream" if stream else "/api/chat", json=payload,
        )
    return response, provider, seen


def test_fixtures_carry_the_reproduced_conditions() -> None:
    """실측한 결함 조건을 고정한다: 본문이 제공자 질의 상한을 넘고, 판정 쿼리는 본문 전문이다."""
    assert len(DOCUMENT) > MAX_QUERY_CHARS
    assert len(CURRENT_FACT) > MAX_QUERY_CHARS
    decision = decide_search(DOCUMENT, task_id="auto")
    assert decision.requires_search and decision.reason == "freshness_sensitive"
    assert decision.query == DOCUMENT.strip(), "the decision still carries the whole body as its query"
    assert decide_search(CURRENT_FACT, task_id="auto").evidence_required is True


@pytest.mark.asyncio
async def test_short_message_answers_normally() -> None:
    response, provider, seen = await post({"messages": [{"role": "user", "content": SHORT}]})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "정리한 답변입니다."
    assert provider.search_calls == []
    assert len(seen) == 1
    assert seen[0]["messages"][-1]["content"] == SHORT


@pytest.mark.asyncio
async def test_boundary_at_provider_query_cap_is_answered() -> None:
    """경계: 제공자 질의 계약과 같은 길이는 여전히 답변이 나온다(422 아님).

    이 경계 아래에서 자동 분기가 본문을 검색 질의로 내보내는 동작은 #6090 실측 보고의
    P1 항목이며, 이 테스트는 그 동작이 조용히 사라지지 않았는지를 고정한다.
    """
    head = "지금 정리한 초안입니다. "
    text = head + "가" * (MAX_QUERY_CHARS - len(head))
    assert len(text) == MAX_QUERY_CHARS
    response, provider, _ = await post({"messages": [{"role": "user", "content": text}]})
    assert response.status_code == 200, response.text
    assert provider.search_calls, "at the provider cap the automatic branch still searches"
    assert len(provider.search_calls[0][0]) == MAX_QUERY_CHARS


@pytest.mark.asyncio
async def test_200k_document_is_answered_without_external_search() -> None:
    """주 회귀: 20만 자 본문 + 흔한 신선도 단어 → 200 답변, 외부 전송 0, 422 없음."""
    response, provider, seen = await post({"messages": [{"role": "user", "content": DOCUMENT}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "정리한 답변입니다."
    assert provider.search_calls == [], "a document-sized body must never be a web query"
    assert len(seen) == 1
    # The model still receives the whole request; only the search branch is off.
    assert seen[0]["messages"][-1]["content"] == DOCUMENT.strip()


@pytest.mark.asyncio
async def test_200k_current_fact_question_is_disclosed_in_korean() -> None:
    """현재 사실 질문이면 조용히 기억으로 답하지 않고 한국어 안내를 붙인다."""
    response, provider, _ = await post({"messages": [{"role": "user", "content": CURRENT_FACT}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert provider.search_calls == []
    assert body["notice"] == SEARCH_QUERY_TOO_LONG_MESSAGE
    assert body["metadata"]["web_grounding_error"] == SEARCH_QUERY_TOO_LONG_CODE


@pytest.mark.asyncio
async def test_200k_plain_document_has_no_misleading_notice() -> None:
    """검색이 필요 없는 장문에는 '웹 검색을 사용할 수 없어' 같은 잘못된 안내를 붙이지 않는다."""
    response, provider, _ = await post({"messages": [{"role": "user", "content": DOCUMENT}]})
    assert response.status_code == 200, response.text
    assert "notice" not in response.json()
    assert provider.search_calls == []


@pytest.mark.asyncio
async def test_explicit_search_with_document_sized_body_degrades_with_korean_guidance() -> None:
    """사용자가 직접 검색을 요청해도 422 로 죽이지 않는다: 같은 모델이 답하고 안내를 붙인다."""
    response, provider, seen = await post(
        {"messages": [{"role": "user", "content": CURRENT_FACT}], "web_search": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["notice"] == SEARCH_QUERY_TOO_LONG_MESSAGE
    assert body["metadata"]["web_grounding_error"] == SEARCH_QUERY_TOO_LONG_CODE
    assert provider.search_calls == []
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_short_explicit_search_still_searches() -> None:
    """수정이 검색 자체를 막지 않았다는 differential 증거."""
    response, provider, _ = await post(
        {"messages": [{"role": "user", "content": SHORT_CURRENT_FACT}], "web_search": True},
    )
    assert response.status_code == 200, response.text
    assert len(provider.search_calls) == 1


@pytest.mark.asyncio
async def test_stream_200k_document_is_not_refused() -> None:
    response, provider, _ = await post(
        {"messages": [{"role": "user", "content": DOCUMENT}]}, stream=True,
    )
    assert response.status_code == 200, response.text[:400]
    assert provider.search_calls == []
    assert '"error"' not in response.text, response.text[:400]


@pytest.mark.asyncio
async def test_stream_200k_current_fact_question_carries_the_korean_guidance() -> None:
    response, provider, _ = await post(
        {"messages": [{"role": "user", "content": CURRENT_FACT}]}, stream=True,
    )
    assert response.status_code == 200, response.text[:400]
    assert SEARCH_QUERY_TOO_LONG_MESSAGE in response.text
    assert provider.search_calls == []


@pytest.mark.asyncio
async def test_typed_search_query_over_the_provider_cap_names_what_to_do() -> None:
    """명시적으로 입력한 검색어가 제공자 질의 한도를 넘으면 숫자가 아니라 대안을 안내한다."""
    response, provider, _ = await post({
        "messages": [{"role": "user", "content": SHORT}],
        "tool": "web_search",
        "tool_input": "가" * (MAX_QUERY_CHARS + 1),
    })
    assert response.status_code == 422, response.text
    message = response.json()["error"]["message"]
    assert message == SEARCH_QUERY_TOO_LONG_MESSAGE
    assert "파일 첨부" in message and "나눠서" in message
    assert provider.search_calls == []


def test_automatic_skip_reason_is_recorded() -> None:
    """자동 분기가 왜 건너뛰었는지가 판정 사유로 남는다(조용한 분류 변경 금지)."""
    service = AutoGroundingService(RecordingProvider())
    from app.task_modes import get_task_mode

    decision = service.decide(
        [{"role": "user", "content": DOCUMENT}], skill=get_task_mode("auto"),
    )
    assert decision.reason == AUTOMATIC_SEARCH_OVER_QUERY_CAP
    assert decision.requires_search is False
    assert decision.query == DOCUMENT.strip()
