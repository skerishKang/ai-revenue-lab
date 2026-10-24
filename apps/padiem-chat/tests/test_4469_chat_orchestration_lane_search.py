"""#4469: the Chat composer is answered by the P01 orchestration lane, so the
shared public web search has to run on that lane too.

The production symptom was a Chat answer that said the search results had not
been provided: the browser sends every Chat turn to `/api/orchestration`
first, and that lane never ran the auto-grounding search that lives in the
Chat stream route. These tests pin the fixed lane contract:

* a turn that needs current external facts runs the existing Core search
  decision and the existing provider, and the grounded evidence reaches the
  Engine as additional system context;
* the grounded answer returns the public evidence and the web-search tool
  marker, exactly like the Chat stream route already does;
* a turn that needs no external fact performs no provider call at all;
* the browser forwards that evidence into the stream so the answer shows its
  sources.

No provider, Engine, D1 or network call is made here: the search service, the
Engine bridge and the browser transport are recorded.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from app import orchestration_routes as routes
from app.orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError

OWNER = "usr_" + "a" * 32
SEARCH_QUESTION = "오늘 Meta의 최신 실적을 웹에서 확인해 줘"
GREETING = "안녕"

STATIC = Path(__file__).resolve().parents[1] / "static"


class _RecordingBridge(B62EngineOrchestrationBridge):
    """The real bridge request builder with the Engine transport recorded."""

    def __init__(self) -> None:
        super().__init__(client=object(), store=object())
        self.requests: list[dict] = []

    async def start(self, **fields):
        self.requests.append(self.build_engine_request(
            user_id=fields["user_id"],
            messages=fields["messages"],
            skill=fields["skill"],
            model_id=fields["model_id"],
            conversation_id=fields["conversation_id"],
            additional_system_context=fields.get("additional_system_context"),
        ))
        return SimpleNamespace(
            orchestration={"status": "completed"},
            answer="확인했습니다.",
            decision_status="completed",
            user_text=fields["user_text"],
            conversation_id="chat_" + "c" * 32,
        )


class _PreparedEvidence:
    def __init__(self, context: str, evidence: list) -> None:
        self.context = context
        self.evidence = evidence


class _FakeAutoGrounding:
    """The recorded auto-grounding service of the Chat stream route."""

    def __init__(self, prepared: _PreparedEvidence | None) -> None:
        self._prepared = prepared
        self.calls: list[dict] = []

    async def prepare(self, messages, *, skill, additional_system_context=None, explicit_search=False):
        self.calls.append({
            "messages": messages,
            "skill": skill,
            "additional_system_context": additional_system_context,
            "explicit_search": explicit_search,
        })
        plan = SimpleNamespace(prepared=self._prepared)
        return plan


class _History:
    async def get_conversation(self, user_id, conversation_id):
        return None

    async def append_exchange(self, *args, **kwargs):
        return "chat_" + "s" * 32


def _install(monkeypatch, auto_grounding):
    bridge = _RecordingBridge()
    history = _History()

    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)

    import app.chat_pc_drive as lane

    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)
    monkeypatch.setattr(
        lane,
        "execute_chat_pc_drive_lane",
        _no_pc_lane,
    )
    return bridge, history


async def _no_pc_lane(*args, **kwargs):
    return None


class _FailingBridge:
    """A bridge whose Engine leg already failed with a bounded product code."""

    def __init__(self, error: B62OrchestrationError) -> None:
        self.error = error

    async def start(self, **fields):
        raise self.error


def _install_bridge(monkeypatch, bridge):
    history = _History()
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)

    import app.chat_pc_drive as lane

    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)
    monkeypatch.setattr(lane, "execute_chat_pc_drive_lane", _no_pc_lane)
    return history


def _request(payload, bridge, history, auto_grounding):
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=bridge,
            history_store=history,
            usage_gate_enforced=False,
            usage_gate=None,
            b66_member_admin_store=SimpleNamespace(
                is_admin=False,
                runtime_access=None,
            ),
            settings=SimpleNamespace(runtime_mode="mock"),
            auto_grounding=auto_grounding,
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def _payload(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}]}


def _evidence() -> list:
    from padiem_ai_core.contracts import Evidence

    return [
        Evidence(
            id="ev_1",
            title="Meta Platforms earnings",
            url="https://example.com/meta-earnings",
            snippet="reported revenue",
            retrieved_at="2026-10-22T00:00:00Z",
            provider="tinyfish",
            source_type="search",
        )
    ]


def test_a_search_turn_grounds_the_orchestration_lane(monkeypatch) -> None:
    """The lane that answers the turn runs the shared search."""
    prepared = _PreparedEvidence("웹 근거 사용 규칙\n[1] example", _evidence())
    auto_grounding = _FakeAutoGrounding(prepared)
    bridge, history = _install(monkeypatch, auto_grounding)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload(SEARCH_QUESTION), bridge, history, auto_grounding),
    ))

    assert response.status_code == 200
    body = json.loads(response.body)
    # The Engine received the grounded context.
    assert len(bridge.requests) == 1
    assert bridge.requests[0]["additional_system_context"] == prepared.context
    # The browser contract carries the tool marker and the public evidence.
    assert body["tool"] == {"id": "web_search", "title": "웹 검색"}
    assert body["answer_status"] == "answered_with_evidence"
    assert len(body["evidence"]) == 1
    assert body["evidence"][0]["url"] == "https://example.com/meta-earnings"
    assert body["evidence"][0]["retrieved_at"] == "2026-10-22T00:00:00Z"
    # The provider identity stays server-side.
    assert "provider" not in body["evidence"][0]


def test_a_greeting_turn_performs_no_search_and_no_grounding(monkeypatch) -> None:
    """A request that needs no current external fact calls no provider."""
    auto_grounding = _FakeAutoGrounding(None)
    bridge, history = _install(monkeypatch, auto_grounding)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload(GREETING), bridge, history, auto_grounding),
    ))

    assert response.status_code == 200
    body = json.loads(response.body)
    assert "additional_system_context" not in bridge.requests[0]
    assert "evidence" not in body
    assert "tool" not in body


def test_the_lane_without_a_search_service_calls_no_provider(monkeypatch) -> None:
    """A lane that has no search service fails closed and answers normally."""
    bridge, history = _install(monkeypatch, None)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload(SEARCH_QUESTION), bridge, history, None),
    ))

    assert response.status_code == 200
    body = json.loads(response.body)
    assert "evidence" not in body
    assert "tool" not in body


def test_the_browser_forwards_the_grounded_evidence_into_the_stream() -> None:
    """The evidence reaches the answer surface, so the sources are shown."""
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    assert "donePayload.evidence = data.evidence;" in transport
    assert "donePayload.tool = data.tool;" in transport
    assert "donePayload.answer_status = data.answer_status;" in transport

    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "window.PadiemSearchSources?.render?.(article, data.evidence);" in app
    assert 'recordTaskEvent?.(article, "web_search")' in app

    sources = (STATIC / "search-sources.js").read_text(encoding="utf-8")
    assert "window.PadiemSearchSources = Object.freeze({" in sources


def test_the_public_evidence_projection_keeps_the_browser_contract() -> None:
    """The projection is the existing allowlisted Chat contract."""
    from app.public_chat import public_chat_result

    projected = public_chat_result({"evidence": [
        {
            "id": "ev_1",
            "title": "Meta Platforms earnings",
            "url": "https://example.com/meta-earnings",
            "snippet": "reported revenue",
            "retrieved_at": "2026-10-22T00:00:00Z",
            "provider": "tinyfish",
            "source_type": "search",
        }
    ]})
    evidence = projected["evidence"][0]
    assert evidence["url"] == "https://example.com/meta-earnings"
    assert "provider" not in evidence
    assert re.match(r"^https://", evidence["url"])


def test_the_error_response_carries_the_bounded_orchestration_code(monkeypatch) -> None:
    """#5568: the Chat response exposes the product code the composer renders."""
    message = "AI 서비스 인증 확인에 실패했습니다. 잠시 후 다시 시도해 주세요."
    bridge = _FailingBridge(B62OrchestrationError("upstream_auth_error", message, status_code=403))
    history = _install_bridge(monkeypatch, bridge)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload(GREETING), bridge, history, None),
    ))

    assert response.status_code == 403
    assert json.loads(response.body) == {
        "error": {"code": "upstream_auth_error", "message": message},
    }


def test_the_success_response_bytes_are_unchanged(monkeypatch) -> None:
    """#5568: the code line is failure-only; a successful turn serializes as before."""
    bridge, history = _install(monkeypatch, None)

    response = asyncio.run(routes.api_orchestration(
        _request(_payload(GREETING), bridge, history, None),
    ))

    assert response.status_code == 200
    expected = {
        "orchestration": {"status": "completed"},
        "answer": "확인했습니다.",
        "decision_status": "completed",
        "conversation_id": "chat_" + "s" * 32,
    }
    assert response.body == json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
