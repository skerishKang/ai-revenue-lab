"""#5108: a casual Chat turn must not end on a web-evidence 404.

Reproduced production symptom: a normal conversation that asked for today's
date answered `HTTP 404 / no_evidence` because the request was classified as a
search-required request, the automatic search produced no usable evidence, and
the whole turn failed.

Contract under test:
  - a current date/weekday/time question is answered from the trusted server
    clock and never becomes a web-evidence request;
  - an automatic search that found no usable evidence may continue as a normal
    answer when the request does not depend on current external facts, and no
    source is shown;
  - Owner 2026-10-24: automatic and explicit search failures continue with
    an ungrounded notice; model failures remain model failures;
  - the conversation, the model and the grade are untouched by the fallback.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.auto_grounding import AutoGroundingService
from app.config import Settings
from app.evidence import Evidence
from app.grounding import GroundedChatService
from app.main import create_app
import app.model_policy as model_policy_module
from app.model_policy import DEFAULT_B14_MODEL_ID
from app.task_modes import get_task_mode
from app.web_tools import WebToolError

BASE = "https://chat.example.test"
OWNER = "usr_" + "d" * 32
CONVERSATION_ID = "chat_" + "e" * 32
SECRET = "5108-auto-grounding-fallback-session-secret"

DATE_QUESTION = "아니 오늘 집에 있을거야 근데 오늘 며칠인지나 알아?"
CLOCK_QUESTIONS = [
    "오늘 며칠이야?",
    "오늘 무슨 요일이야?",
    "지금 몇 시야?",
    "내일은 무슨 요일이야?",
]
CASUAL = "비 오는구나"
BARE_FRESHNESS = "오늘은 집에 있을 거야."
WEATHER = "오늘 광주 날씨 알려줘"
EXPLICIT = "웹에서 이 주장 사실인지 찾아봐"


@pytest.fixture(autouse=True)
def _selected_model_for_grounding_contract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        model_policy_module,
        "EXECUTABLE_B14_MODEL_IDS",
        frozenset({DEFAULT_B14_MODEL_ID}),
    )


def completion_payload(answer: str = "2026년 10월 20일 월요일입니다.") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": answer}}],
        "business14": {
            "request_id": "b14req_5108",
            "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_provider": "Poolside",
        },
    }


def sse_frame(answer: str = "2026년 10월 20일 월요일입니다.") -> bytes:
    """One SSE frame in the shape the streaming lane expects."""
    payload = {
        "id": "stream_5108",
        "object": "chat.completion.chunk",
        "model": DEFAULT_B14_MODEL_ID,
        "choices": [{"index": 0, "delta": {"content": answer}, "finish_reason": None}],
        "business14": {
            "request_id": "b14req_5108",
            "route_mode": "manual",
            "selected_provider": "Poolside",
            "selected_model": DEFAULT_B14_MODEL_ID,
        },
    }
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


class RecordingProvider:
    """A provider that records the queries and returns usable evidence."""

    def __init__(self, rows: int = 5):
        self.rows = rows
        self.search_calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.search_calls.append((query, limit))
        return [
            Evidence(
                id=f"auto_{index}",
                title=f"Verified source {index}",
                url=f"https://example.com/source/{index}",
                snippet=f"Verified current fact {index}",
                retrieved_at="2026-10-20T00:00:00Z",
                provider="test",
                source_type="search",
            )
            for index in range(1, min(self.rows, limit) + 1)
        ]

    async def fetch(self, url: str):
        raise AssertionError("automatic simple search must not fetch pages")


class EmptyProvider:
    """A provider whose search returns nothing usable."""

    def __init__(self):
        self.search_calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.search_calls.append((query, limit))
        return []

    async def fetch(self, url: str):
        raise AssertionError("fetch must not run")


class BrokenProvider:
    """A provider whose search endpoint is down.

    The production providers translate a provider outage into a
    ``WebToolError`` at the web-tools boundary, so the outage keeps its own
    failure code instead of being reported as a missing evidence result.
    """

    def __init__(self):
        self.search_calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.search_calls.append((query, limit))
        raise WebToolError("web_unavailable", "웹 검색을 사용할 수 없습니다.", 503)

    async def fetch(self, url: str):
        raise AssertionError("fetch must not run")


def install_provider(app, provider) -> None:
    app.state.web_provider = provider
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, provider)
    app.state.auto_grounding = AutoGroundingService(provider)


class OwnerHistory:
    def __init__(self):
        self.saved: list[tuple] = []

    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id, *, product_scope=None):
        return None

    async def append_exchange(
        self, user_id, conversation_id, user_text, assistant_text,
        project_id=None, *, product_scope: str,
    ):
        self.saved.append((user_id, conversation_id, user_text, assistant_text))
        return CONVERSATION_ID


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="b14", auth_mode="google",
        public_base_url=BASE,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="test-only-secret",
        b14_base_url="https://b14.example",
        session_secret=SECRET,
    )


def build_app(provider, *, handler=None, store=None):
    seen: list[dict] = []

    async def b14_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        if handler is not None:
            return await handler(request)
        # Answer in the shape the requested lane expects. The completed lane
        # reads one JSON body; the streaming lane reads SSE frames. The test
        # does not depend on which lane the resolved model selects.
        if payload.get("stream") is True:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=sse_frame(),
            )
        return httpx.Response(200, json=completion_payload())

    config = settings()
    app = create_app(
        config,
        history_store=store if store is not None else OwnerHistory(),
        transport=httpx.MockTransport(b14_handler),
    )
    app.state.usage_gate_enforced = False
    install_provider(app, provider)
    return app, config, seen


def post(app, config, path, body, *, user=OWNER):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            client.cookies.set(
                SESSION_COOKIE, create_session_token(config, user),
                domain="chat.example.test", path="/",
            )
            return await client.post(path, json=body)

    return asyncio.run(inner())


def messages(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


# --- the reported symptom -----------------------------------------------------

@pytest.mark.parametrize("question", CLOCK_QUESTIONS)
def test_clock_question_never_searches_and_answers_normally(question: str) -> None:
    """A current date/weekday/time question is answered from the server clock."""
    provider = RecordingProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages(question)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"]
    assert "answer_status" not in body
    assert "evidence" not in body
    assert provider.search_calls == []
    assert len(seen) == 1


def test_reported_follow_up_question_is_not_a_search_request() -> None:
    """The reproduced message keeps the conversation on the normal path."""
    provider = RecordingProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages(DATE_QUESTION)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer"]
    assert provider.search_calls == []
    assert len(seen) == 1


def test_clock_question_with_an_empty_search_provider_still_answers() -> None:
    """No web evidence is required, so a 0-result search cannot end the turn."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages("오늘 며칠이야?")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer"]
    assert provider.search_calls == []


def test_stream_grounding_plan_for_a_clock_question_carries_no_evidence() -> None:
    """The streaming lane's grounding plan stays empty for a clock question.

    The streaming endpoint consumes this plan. A clock question is not a
    web-evidence request, so the plan carries no prepared evidence and the
    provider is never asked.
    """
    provider = RecordingProvider()
    service = AutoGroundingService(provider)
    plan = asyncio.run(service.prepare(
        messages("오늘 무슨 요일이야?"),
        skill=get_task_mode(),
        additional_system_context=None,
    ))
    assert plan.prepared is None
    assert plan.searched is False
    assert plan.decision.requires_search is False
    assert provider.search_calls == []


# --- automatic search that finds nothing ---------------------------------------

def test_automatic_search_without_usable_evidence_continues_normally() -> None:
    """A request that does not need current facts keeps the normal answer."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages(BARE_FRESHNESS)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"]
    # The search ran, found nothing, and no source is presented.
    assert len(provider.search_calls) == 1
    assert "evidence" not in body
    assert "answer_status" not in body
    assert len(seen) == 1


def test_stream_grounding_plan_after_the_fallback_carries_no_evidence() -> None:
    """The streaming lane keeps the turn alive on the same fallback."""
    provider = EmptyProvider()
    service = AutoGroundingService(provider)
    plan = asyncio.run(service.prepare(
        messages(BARE_FRESHNESS),
        skill=get_task_mode(),
        additional_system_context=None,
    ))
    # The search ran and found nothing; the plan stays empty, so the streaming
    # endpoint answers normally and shows no source.
    assert len(provider.search_calls) == 1
    assert plan.prepared is None
    assert plan.searched is False
    assert plan.decision.requires_search is True


def test_stream_grounding_plan_still_carries_the_evidence_when_found() -> None:
    """A successful automatic search still prepares the evidence."""
    provider = RecordingProvider()
    service = AutoGroundingService(provider)
    plan = asyncio.run(service.prepare(
        messages(WEATHER),
        skill=get_task_mode(),
        additional_system_context=None,
    ))
    assert plan.prepared is not None
    assert plan.searched is True
    assert len(provider.search_calls) == 1


def test_weather_question_answers_with_an_ungrounded_notice() -> None:
    """Missing evidence is disclosed and the model still answers."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages(WEATHER)}
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["web_grounding_error"] == "web_grounding_no_evidence"
    assert response.json()["notice"] == "웹 근거를 찾지 못해 근거 없이 답변합니다"
    assert "evidence" not in response.json()
    assert len(seen) == 1


def test_explicit_web_search_answers_with_an_ungrounded_notice() -> None:
    """Explicit search failure remains visible above the model answer."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages(EXPLICIT)}
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["web_grounding_error"] == "web_grounding_no_evidence"
    assert response.json()["notice"] == "웹 근거를 찾지 못해 근거 없이 답변합니다"
    assert "evidence" not in response.json()
    assert len(seen) == 1


def test_search_provider_outage_continues_with_its_own_metadata() -> None:
    """A search outage is reported as the search failure it is."""
    provider = BrokenProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages(BARE_FRESHNESS)}
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["web_grounding_error"] == "web_grounding_unavailable"
    assert response.json()["notice"] == "웹 검색을 사용할 수 없어 근거 없이 답변합니다"
    assert "evidence" not in response.json()
    assert len(seen) == 1


def test_model_error_is_not_reported_as_a_search_error() -> None:
    """A B14 failure stays a model failure, never a web-grounding failure."""

    async def failing_model(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "upstream"}})

    provider = RecordingProvider()
    app, config, seen = build_app(provider, handler=failing_model)
    response = post(
        app, config, "/api/chat", {"messages": messages(CASUAL)}
    )
    assert response.status_code >= 500
    assert response.json()["error"]["code"] != "no_evidence"


def test_current_office_holder_fallback_discloses_missing_evidence() -> None:
    """Current-fact fallback always discloses missing evidence."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages("현재 대통령")}
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["web_grounding_error"] == "web_grounding_no_evidence"
    assert response.json()["notice"] == "웹 근거를 찾지 못해 근거 없이 답변합니다"
    assert "evidence" not in response.json()
    assert len(seen) == 1


def test_external_event_schedule_fallback_discloses_missing_evidence() -> None:
    """An event schedule fallback discloses missing evidence."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat",
        {"messages": messages("몇 시에 경기가 시작해?")},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["web_grounding_error"] == "web_grounding_no_evidence"
    assert response.json()["notice"] == "웹 근거를 찾지 못해 근거 없이 답변합니다"
    assert "evidence" not in response.json()
    assert len(seen) == 1


def test_a_mention_of_an_event_keeps_the_ordinary_answer_path() -> None:
    """A request that merely mentions an event is not forced to search."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat",
        {"messages": messages("영화 시나리오 작성해줘")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer"]
    # The provider was never asked: the ordinary path answered directly.
    assert provider.search_calls == []
    assert len(seen) == 1


def test_current_weather_fallback_discloses_missing_evidence() -> None:
    """A weather fallback never claims web evidence."""
    provider = EmptyProvider()
    app, config, seen = build_app(provider)
    response = post(
        app, config, "/api/chat", {"messages": messages("지금 비 와?")}
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["web_grounding_error"] == "web_grounding_no_evidence"
    assert response.json()["notice"] == "웹 근거를 찾지 못해 근거 없이 답변합니다"
    assert "evidence" not in response.json()
    assert len(seen) == 1


# --- conversation continuity --------------------------------------------------

def test_fallback_keeps_the_conversation_and_the_model_grade() -> None:
    """The fallback does not duplicate or lose the conversation turn."""
    store = OwnerHistory()
    provider = EmptyProvider()
    app, config, seen = build_app(provider, store=store)
    response = post(
        app, config, "/api/chat",
        {
            "messages": messages(BARE_FRESHNESS),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] == CONVERSATION_ID
    assert len(store.saved) == 1
    user_id, conversation_id, user_text, answer = store.saved[0]
    assert user_id == OWNER
    assert user_text == BARE_FRESHNESS
    assert answer
    # One model call, with the request-scoped grade still bound.
    assert len(seen) == 1
    assert seen[0]["model"] == DEFAULT_B14_MODEL_ID


@pytest.mark.parametrize("status,code", [(403, "web_grounding_auth_error"), (502, "web_grounding_unavailable"), (404, "web_grounding_no_evidence")])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_web_failure_keeps_the_same_model_turn_with_notice(status, code, explicit, path):
    class FailedProvider(EmptyProvider):
        async def search(self, query, limit=5):
            self.search_calls.append((query, limit))
            if status == 404:
                return []
            # Provider response and credentials must never reach the browser.
            raise WebToolError("upstream_auth_error" if status == 403 else "web_unavailable", "private-provider-response", status)

    async def model(request):
        payload = json.loads(request.content)
        if payload.get("stream"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=sse_frame("모델 답변") + b"data: [DONE]\n\n")
        return httpx.Response(200, json=completion_payload("모델 답변"))

    provider = FailedProvider()
    app, config, seen = build_app(provider, handler=model)
    payload = {"messages": messages(WEATHER)}
    if explicit:
        if path.endswith("/stream"):
            payload["web_search"] = True
        else:
            payload["tool"] = "web_search"
    response = post(app, config, path, payload)
    assert response.status_code == 200, response.text
    if path.endswith("/stream"):
        from test_auto_grounding import parse_public_sse
        frames = parse_public_sse(response.text)
        assert "".join(data["delta"] for event, data in frames if event == "delta") == "모델 답변"
        body = [data for event, data in frames if event == "done"][-1]
    else:
        body = response.json()
        assert body["answer"] == "모델 답변"
    assert body["metadata"] == {"web_grounding_error": code}
    assert body["notice"] == ("웹 근거를 찾지 못해 근거 없이 답변합니다" if status == 404 else "웹 검색을 사용할 수 없어 근거 없이 답변합니다")
    assert "evidence" not in body and "tool" not in body and "error" not in body
    assert "private-provider-response" not in response.text
    assert len(provider.search_calls) == 1
    assert len(seen) == 1
    assert seen[0]["model"] == DEFAULT_B14_MODEL_ID


def test_model_auth_error_after_successful_search_is_not_a_web_error():
    async def model(request):
        return httpx.Response(403, json={"error": {"code": "upstream_auth_error", "message": "private"}})
    app, config, seen = build_app(RecordingProvider(), handler=model)
    response = post(app, config, "/api/chat", {"messages": messages(WEATHER)})
    # The existing Chat model adapter maps provider authentication to 502.
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_auth_error"
    assert "notice" not in response.json() and "metadata" not in response.json()
    assert len(seen) == 1
