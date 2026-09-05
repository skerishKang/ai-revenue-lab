from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.orchestration_bridge import (
    B62EngineOrchestrationBridge,
    B62OrchestrationError,
    OrchestrationSnapshot,
    project_public_orchestration,
)
from app.orchestration_routes import parse_approval_intent, parse_cancel_intent
from app.task_modes import get_task_mode


APP_ROOT = Path(__file__).resolve().parents[1]


def _event(kind: str, sequence: int) -> dict:
    return {
        "event_id": f"evt_{sequence}",
        "run_id": "run_1",
        "trace_id": "trace_1",
        "app_id": "padiem-chat",
        "kind": kind,
        "sequence": sequence,
        "message": "PRIVATE MESSAGE MUST NOT PROJECT",
        "metadata": {"secret": "DO_NOT_RENDER", "tool_arguments": {"token": "NO"}},
    }


def _paused_raw() -> dict:
    return {
        "execution": {
            "answer": "intermediate private answer",
            "route": {"selected_provider": "PRIVATE_PROVIDER", "selected_model": "PRIVATE_MODEL"},
            "metadata": {"private": "NO"},
        },
        "context": {"idempotency_key": "PRIVATE"},
        "plan": {"steps": [{"tool_id": "PRIVATE_TOOL"}]},
        "resolved_tool_ids": ["PRIVATE_TOOL"],
        "events": [_event("run_started", 1), _event("approval_paused", 2)],
        "approval_pause": {
            "status": "paused",
            "continuation_id": "pause_1",
            "run_id": "run_1",
            "trace_id": "trace_1",
            "agent_id": "agent_1",
            "tool_id": "PRIVATE_TOOL",
            "requirement": "user_confirmation",
            "approval_scope": ["PRIVATE_SCOPE"],
            "created_at": "2099-01-01T00:00:00+00:00",
            "expires_at": "2099-01-01T01:00:00+00:00",
        },
        "continuation_ref": "cont_abcdefgh12345678",
    }


def _completed_raw(answer: str = "완료된 답변") -> dict:
    return {
        "execution": {
            "answer": answer,
            "route": {"selected_provider": "PRIVATE_PROVIDER", "selected_model": "PRIVATE_MODEL"},
            "metadata": {"private": "NO"},
        },
        "context": {"private": "NO"},
        "plan": {"private": "NO"},
        "resolved_tool_ids": ["PRIVATE_TOOL"],
        "events": [
            _event("run_started", 1),
            _event("run_resumed", 2),
            _event("run_completed", 3),
        ],
        "approval_pause": None,
    }


class FakeClient:
    def __init__(self, start_result: dict | None = None, resume_result: dict | None = None) -> None:
        self.start_result = start_result or _paused_raw()
        self.resume_result = resume_result or _completed_raw()
        self.orchestrate_request = None
        self.resume_request = None
        self.cancel_request = None

    async def orchestrate(self, request):
        self.orchestrate_request = request
        return self.start_result

    async def resume_orchestration(self, request):
        self.resume_request = request
        return self.resume_result

    async def cancel_orchestration_pause(self, request):
        self.cancel_request = request
        return {
            "ok": True,
            "status": "cancelled",
            "events": [_event("run_started", 1), _event("run_cancelled", 2)],
        }


class FakeStore:
    def __init__(self) -> None:
        self.snapshot = None
        self.saved = []
        self.decisions = []
        self.states = []

    async def save_pause(self, **kwargs):
        self.saved.append(kwargs)
        self.snapshot = OrchestrationSnapshot(
            continuation_ref=kwargs["continuation_ref"],
            user_id=kwargs["user_id"],
            pause_id=kwargs["pause_id"],
            engine_request=dict(kwargs["engine_request"]),
            user_text=kwargs["user_text"],
            conversation_id=kwargs["conversation_id"],
            expires_at=kwargs["expires_at"],
            state="active",
        )

    async def load_active(self, *, user_id, continuation_ref):
        if (
            self.snapshot is None
            or self.snapshot.user_id != user_id
            or self.snapshot.continuation_ref != continuation_ref
        ):
            raise B62OrchestrationError(
                "continuation_not_available",
                "이 작업은 더 이상 이어갈 수 없습니다.",
                status_code=409,
            )
        return self.snapshot

    async def record_decision(self, **kwargs):
        self.decisions.append(kwargs)

    async def set_state(self, **kwargs):
        self.states.append(kwargs)


def test_public_projection_drops_route_plan_context_tool_and_event_metadata() -> None:
    public = project_public_orchestration(_paused_raw())

    assert public["answer"] is None
    assert public["continuation_ref"] == "cont_abcdefgh12345678"
    assert public["approval_pause"] == {
        "status": "paused",
        "continuation_id": "pause_1",
        "requirement": "user_confirmation",
        "expires_at": "2099-01-01T01:00:00+00:00",
    }
    serialized = repr(public)
    for forbidden in (
        "PRIVATE_PROVIDER",
        "PRIVATE_MODEL",
        "PRIVATE_TOOL",
        "PRIVATE_SCOPE",
        "DO_NOT_RENDER",
        "tool_arguments",
        "idempotency_key",
    ):
        assert forbidden not in serialized


def test_start_uses_engine_owned_client_and_persists_exact_server_request() -> None:
    client = FakeClient()
    store = FakeStore()
    bridge = B62EngineOrchestrationBridge(client=client, store=store)
    skill = get_task_mode("auto")

    result = asyncio.run(
        bridge.start(
            user_id="usr_0123456789abcdef0123456789abcdef",
            messages=[{"role": "user", "content": "질문"}],
            skill=skill,
            model_id="kilo/minimax-minimax-m3-free",
            user_text="질문",
            conversation_id=None,
        )
    )

    request = client.orchestrate_request
    assert request["subject_id"] == "usr_0123456789abcdef0123456789abcdef"
    assert request["agent"]["model_policy"] == {
        "model": "kilo/minimax-minimax-m3-free"
    }
    assert request["messages"] == [{"role": "user", "content": "질문"}]
    assert request["execution_context"] == {"trace_id": request["trace_id"]}
    assert "tool_authorization" not in request
    assert "tool_runtime" not in request
    assert result.orchestration["approval_pause"]["continuation_id"] == "pause_1"
    assert store.saved[0]["engine_request"] == request


def test_resume_uses_server_snapshot_and_server_minted_decision_evidence() -> None:
    client = FakeClient()
    store = FakeStore()
    bridge = B62EngineOrchestrationBridge(client=client, store=store)
    skill = get_task_mode("auto")
    asyncio.run(
        bridge.start(
            user_id="usr_0123456789abcdef0123456789abcdef",
            messages=[{"role": "user", "content": "질문"}],
            skill=skill,
            model_id="kilo/minimax-minimax-m3-free",
            user_text="질문",
            conversation_id="chat_0123456789abcdef0123456789abcdef",
        )
    )
    exact_snapshot = dict(store.snapshot.engine_request)

    result = asyncio.run(
        bridge.resume(
            user_id="usr_0123456789abcdef0123456789abcdef",
            continuation_ref="cont_abcdefgh12345678",
            pause_id="pause_1",
            outcome="approved",
        )
    )

    sent = client.resume_request
    for key, value in exact_snapshot.items():
        assert sent[key] == value
    assert sent["continuation_ref"] == "cont_abcdefgh12345678"
    decision = sent["decision"]
    assert decision["pause_id"] == "pause_1"
    assert decision["outcome"] == "approved"
    assert decision["decision_id"].startswith("decision_")
    assert decision["authority_ref"] == "b62_session:usr_0123456789abcdef0123456789abcdef"
    assert decision["evidence_ref"].startswith("b62_decision:decision_")
    assert store.decisions[0]["authority_ref"] == decision["authority_ref"]
    assert store.decisions[0]["evidence_ref"] == decision["evidence_ref"]
    assert result.answer == "완료된 답변"
    assert any(item["state"] == "completed" for item in store.states)


def test_cross_user_continuation_is_rejected_before_engine_resume() -> None:
    client = FakeClient()
    store = FakeStore()
    bridge = B62EngineOrchestrationBridge(client=client, store=store)
    skill = get_task_mode("auto")
    asyncio.run(
        bridge.start(
            user_id="usr_0123456789abcdef0123456789abcdef",
            messages=[{"role": "user", "content": "질문"}],
            skill=skill,
            model_id="kilo/minimax-minimax-m3-free",
            user_text="질문",
            conversation_id=None,
        )
    )

    with pytest.raises(B62OrchestrationError) as captured:
        asyncio.run(
            bridge.resume(
                user_id="usr_ffffffffffffffffffffffffffffffff",
                continuation_ref="cont_abcdefgh12345678",
                pause_id="pause_1",
                outcome="approved",
            )
        )
    assert captured.value.code == "continuation_not_available"
    assert client.resume_request is None


def test_browser_approval_intent_cannot_supply_authority_or_resume_request() -> None:
    valid = {
        "continuationRef": "cont_abcdefgh12345678",
        "pauseId": "pause_1",
        "outcome": "approved",
        "requiresTrustedDecision": True,
    }
    assert parse_approval_intent(valid) == (
        "cont_abcdefgh12345678",
        "pause_1",
        "approved",
    )

    for forbidden in ("decision_id", "authority_ref", "evidence_ref", "engine_request", "messages"):
        with pytest.raises(B62OrchestrationError):
            parse_approval_intent({**valid, forbidden: "browser_minted"})


def test_browser_cancel_intent_is_continuation_only() -> None:
    assert parse_cancel_intent({"continuationRef": "cont_abcdefgh12345678"}) == "cont_abcdefgh12345678"
    with pytest.raises(B62OrchestrationError):
        parse_cancel_intent({"continuationRef": "cont_abcdefgh12345678", "reason": "override"})


def test_worker_and_schema_keep_activation_fail_closed() -> None:
    pyproject = (APP_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    wrangler = (APP_ROOT / "wrangler.toml").read_text(encoding="utf-8")
    worker = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    support = (APP_ROOT / "app" / "worker_orchestration.py").read_text(encoding="utf-8")
    migration = (APP_ROOT / "migrations" / "006_orchestration_continuations.sql").read_text(encoding="utf-8")

    assert "padiem-ai-engine-client @ file://" in pyproject
    assert 'main = "worker.py"' in wrangler
    assert "ENGINE_SERVICE" not in wrangler
    assert "PADIEM_CHAT_ORCHESTRATION_ENABLED" not in wrangler
    assert "PADIEM_CHAT_ENGINE_CALLER_SECRET" not in wrangler
    assert "build_orchestration_bridge" in worker
    assert "install_orchestration_routes" in worker
    assert "PadiemAiEngineClient" in support
    assert "ENGINE_INTERNAL_ORIGIN" in support
    assert "/internal/v1/" not in support
    assert "process-local" not in support.lower()
    assert "orchestration_continuations" in migration
    assert "orchestration_decisions" in migration
    assert "request_json" in migration


def test_browser_transport_never_calls_engine_internal_routes_directly() -> None:
    transport = (APP_ROOT / "static" / "chat-transport.js").read_text(encoding="utf-8")
    lifecycle = (APP_ROOT / "static" / "message-lifecycle.js").read_text(encoding="utf-8")

    assert '"/api/orchestration/status"' in transport
    assert '"/api/orchestration"' in transport
    assert '"/api/orchestration/resume"' in transport
    assert '"/api/orchestration/cancel"' in transport
    assert "/internal/v1/" not in transport
    assert "authority_ref" not in transport
    assert "evidence_ref" not in transport
    assert "decision_id" not in transport
    assert "requiresTrustedDecision" not in transport
    assert "PadiemChatOrchestrationUI.render" not in transport
    assert "document." not in transport
    assert "PadiemChatOrchestrationController" in lifecycle
    assert "orchestrationUi.render" in lifecycle
