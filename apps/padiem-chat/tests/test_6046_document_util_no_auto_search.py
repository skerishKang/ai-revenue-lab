"""#6046 실서비스 E2E에서 발견한 결함의 load-bearing regression.

축사·SNS·회의정리(document util) 요청은 원고 본문 자체를 `messages[].content`로 보낸다.
Core 자동 검색 판정(`decide_search`)은 부분문자열 조합이라, 원고 안에 평범하게 적힌
"언제나"가 "언제"로 잡히고 같은 문서의 "축제·행사"와 짝을 이루어 external_event_schedule
MUST_SEARCH 가 발동한다. 판정 쿼리는 **문서 전문** 그대로다. 검색 API의 2,000자 상한
(`MAX_QUERY_CHARS`)을 넘는 순간 `/api/chat` 은 422 "검색어는 1자 이상 2000자 이하로
입력해 주세요." 로 활동집 생성이 죽고, 상한 아래에서는 사용자 문서가 웹 검색어로 나간다.
선언된 util scope 는 이미 "이 요청의 routing label" 이므로 (auto_grounding 가 아니라
calendar 분기가 그 의미로 쓴다) 같은 라벨로 자동 검색 분기에서도 빼는 것이 최소 수정이다.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.auto_grounding import AutoGroundingService
from app.config import Settings
from app.evidence import Evidence
from app.grounding import GroundedChatService
from app.main import create_app
import app.model_policy as model_policy_module
from app.model_policy import DEFAULT_B14_MODEL_ID


@pytest.fixture(autouse=True)
def _selected_model_for_grounding_contract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(model_policy_module, "EXECUTABLE_B14_MODEL_IDS", frozenset({DEFAULT_B14_MODEL_ID}))


# 실제 실패한 요청의 형태: 고정 템플릿 + 선택된 기록 본문. 총 길이 2,000자를 넘긴다.
BOOK_TEMPLATE_HEAD = "다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.\n\n"
BOOK_TEMPLATE_TAIL = (
    "\n\n위 기록을 바탕으로 다음을 생성해 주세요:\n"
    "1. 책/활동집 제목 후보 3개\n2. 목차 (5-8장)\n3. 각 장별 원고 초안 (200-400자)\n4. 마무리 인사\n\n"
    "주의: 원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요."
)
RECORD = (
    "[기록: 2026 커뮤니티 나눔의 날.txt]\n"
    "언제나 함께해 주신 여러분께 감사드립니다. 결실을 나누는 파티와 축제는 행사장 야외에서 열렸습니다. "
)
DOCUMENT = BOOK_TEMPLATE_HEAD + RECORD * 24 + BOOK_TEMPLATE_TAIL


class RecordingProvider:
    _automatic_search_enabled = True

    def __init__(self) -> None:
        self.search_calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.search_calls.append((query, limit))
        return [Evidence(
            id=f"u_{i}", title=f"소스 {i}", url=f"https://example.com/{i}",
            snippet=f"근거 {i}", retrieved_at="2026-10-28T00:00:00Z",
            provider="test", source_type="search",
        ) for i in range(1, limit + 1)]

    async def fetch(self, url: str):
        raise AssertionError("automatic search must not fetch pages")


def _b14_body() -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "작성된 원고입니다."}}],
        "business14": {
            "request_id": "b14req_util", "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID, "selected_provider": "Poolside",
        },
    }


def _stream_body() -> bytes:
    payload = {
        "id": "stream_util", "object": "chat.completion.chunk", "model": DEFAULT_B14_MODEL_ID,
        "choices": [{"index": 0, "delta": {"content": "작성된 원고입니다."}, "finish_reason": None}],
        "business14": {
            "request_id": "b14req_util", "route_mode": "manual",
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


def test_over_cap_document_fixture() -> None:
    """피처가 결함 조건을 유지하는지 먼저 못 박는다: 상한 초과 + 자동 검색 발동.

    이전 판본은 피처 문구가 달력 분기에 가로채여 네거티브 컨트롤이 검색 경로 자체를
    지나가지 않았다. 그래서 발동 사유를 직접 단언한다.
    """
    from padiem_ai_core.search_decision import decide_search

    from app.request_contract import _UTIL_SCOPES

    assert _UTIL_SCOPES == frozenset({"speech", "sns", "meeting"})
    assert len(DOCUMENT) > 2000, "the fixture must stay over the web-search query cap"
    decision = decide_search(DOCUMENT, task_id="auto")
    assert decision.requires_search and decision.reason == "external_event_schedule"
    assert len(decision.query) == len(DOCUMENT), "the decision must carry the whole document as its query"


@pytest.mark.parametrize("util", ["speech", "sns", "meeting"])
@pytest.mark.asyncio
async def test_document_util_scopes_answer_without_retrieval(util: str) -> None:
    """실서비스 422 재현: 2,000자가 넘는 원고를 세 util scope 로 보내면 검색 시도 없이 답변이 나와야 한다."""
    seen: list[dict] = []
    app, provider = build_app(seen)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": DOCUMENT}], "util": util},
        )

    assert response.status_code == 200, response.text
    assert provider.search_calls == [], "a document-scope request must never reach the web provider"
    assert response.json()["answer"] == "작성된 원고입니다."
    assert "evidence" not in response.json()
    assert len(seen) == 1
    assert seen[0]["messages"][1]["content"] == DOCUMENT


@pytest.mark.asyncio
async def test_document_scope_streams_without_a_grounding_degradation_notice() -> None:
    """/api/chat/stream 은 prepare() 경유이고 상한 초과를 조용히 강등으로 삼는다.

    util 없이는 "웹 검색을 사용할 수 없어 근거 없이 답변합니다" 고지(사실은 검색어 상한
    초과)가 붙고, util 이 있으면 애초에 검색을 판단하지 않아 고지가 없다. 검색 호출 수는
    두 경우 모두 0이라 강등 고지 여부를 본다.
    """
    seen: list[dict] = []
    app, provider = build_app(seen, stream=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        declared = await client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": DOCUMENT}], "util": "meeting"},
        )

    assert declared.status_code == 200, declared.text[:400]
    assert provider.search_calls == []
    assert '"notice"' not in declared.text, declared.text[:400]
    assert "웹 검색" not in declared.text

    seen2: list[dict] = []
    app2, _ = build_app(seen2, stream=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://test") as client:
        undeclared = await client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": DOCUMENT}]},
        )
    assert undeclared.status_code == 200
    # #6090: the undeclared document is still answered (never a 422), and the
    # notice now names the real cause — the body is longer than a search query —
    # instead of the misleading "웹 검색을 사용할 수 없어" degradation line. The
    # differential this test exists for is unchanged: declared => no notice at
    # all, undeclared => a notice.
    assert "웹 검색을 사용할 수 없어" not in undeclared.text
    assert "글이 너무 길어" in undeclared.text
    assert '"web_search_query_too_long"' in undeclared.text


@pytest.mark.asyncio
async def test_short_document_scope_does_not_egress_the_record_as_a_search_query() -> None:
    """422 절반만 막으면 결함은 남는다. 상한 아래 원고는 검색이 '시도'되어 사용자 문서가
    웹 검색어로 나간다. util 선언 자체가 자동 검색 분기에서 빼야 하는 이유."""
    body = BOOK_TEMPLATE_HEAD + RECORD + BOOK_TEMPLATE_TAIL
    assert len(body) <= 2000
    seen: list[dict] = []
    app, provider = build_app(seen)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": body}], "util": "meeting"},
        )

    assert response.status_code == 200, response.text
    assert provider.search_calls == [], "a document scope must not turn the user's record into a web query"
    assert "evidence" not in response.json()


@pytest.mark.asyncio
async def test_undeclared_request_answers_with_korean_length_guidance() -> None:
    """util 을 선언하지 않은 같은 장문도 이제 답변이 나온다 (#6090).

    #6046 당시 이 요청은 422 "검색어는 1자 이상 2000자 이하로 입력해 주세요." 였다.
    본문 전문이 자동 검색 질의로 넘어갔기 때문이다. #6090 은 검색 분기를 고쳤고,
    본문은 여전히 외부로 나가지 않으며(검색 호출 0) 대화는 한국어 안내와 함께 계속된다.
    """
    seen: list[dict] = []
    app, provider = build_app(seen)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": DOCUMENT}]},
        )

    assert response.status_code == 200, response.text[:300]
    assert response.json()["answer"] == "작성된 원고입니다."
    assert response.json()["metadata"]["web_grounding_error"] == "web_search_query_too_long"
    assert provider.search_calls == []


@pytest.mark.asyncio
async def test_explicit_search_flag_still_searches_inside_a_document_scope() -> None:
    """사용자가 명시적으로 검색을 시킨 요청까지 util scope 로 막지 않는다는 escape 증거."""
    seen: list[dict] = []
    app, provider = build_app(seen)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "오늘 발표된 서울시 예산 정책을 찾아서 알려줘"}],
                "util": "meeting", "web_search": True,
            },
        )

    assert response.status_code == 200, response.text[:300]
    assert len(provider.search_calls) == 1
