from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import pytest

from padiem_ai_engine_client import PadiemAiEngineClientError

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
    config = tomllib.loads(wrangler)
    assert {item["binding"]: item["service"] for item in config["services"]}["P01_ENGINE_SERVICE"] == "padiem-ai-engine"
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


class FailingEngineClient:
    """The Engine transport refuses before any orchestration body exists."""

    def __init__(self, code, message: str, status: int | None) -> None:
        self.error = PadiemAiEngineClientError(code, message, status=status)

    async def orchestrate(self, request):
        raise self.error


def _start_failing(error: PadiemAiEngineClientError) -> B62OrchestrationError:
    client = FailingEngineClient(error.code, str(error), error.status)
    bridge = B62EngineOrchestrationBridge(client=client, store=FakeStore())
    with pytest.raises(B62OrchestrationError) as captured:
        asyncio.run(
            bridge.start(
                user_id="usr_0123456789abcdef0123456789abcdef",
                messages=[{"role": "user", "content": "질문"}],
                skill=get_task_mode("auto"),
                model_id="kilo/minimax-minimax-m3-free",
                user_text="질문",
                conversation_id=None,
            )
        )
    return captured.value


@pytest.mark.parametrize(
    ("engine_code", "status", "expected_copy"),
    (
        ("upstream_auth_error", 403, "인증"),
        ("upstream_server_error", 502, "오류"),
        ("timeout", 504, "시간이 초과"),
    ),
)
def test_engine_failure_code_crosses_the_bridge_with_product_copy(engine_code, status, expected_copy) -> None:
    """#5568: the browser gets the bounded code, never the Engine's text."""
    raw = "RAW PROVIDER BODY https://provider.internal/v1 secret sk-live-123"
    failure = _start_failing(PadiemAiEngineClientError(engine_code, raw, status=status))

    assert failure.code == engine_code
    assert failure.status_code == status
    assert expected_copy in failure.user_message
    assert "RAW PROVIDER" not in failure.user_message
    assert "provider.internal" not in failure.user_message
    assert "sk-live" not in failure.user_message


def test_identifier_code_outside_the_copy_map_crosses_with_the_generic_message() -> None:
    """#5568: a well-formed Engine code crosses; the copy stays product-authored."""
    failure = _start_failing(
        PadiemAiEngineClientError(
            "provider_route_private_42",
            "internal route https://provider.internal/v1 failed",
            status=500,
        )
    )

    assert failure.code == "provider_route_private_42"
    assert failure.status_code == 500
    assert "provider.internal" not in failure.user_message
    assert failure.user_message == "AI 작업을 처리하지 못했습니다. 다시 시도해 주세요."


@pytest.mark.parametrize(
    "engine_code",
    ("Provider Route Private", "provider/internal", "업스트림오류", "sk-live-123", "", "a" * 65),
)
def test_non_identifier_engine_code_collapses_to_unknown_error(engine_code: str) -> None:
    """#5568: anything that is not a bounded identifier is never echoed."""
    failure = _start_failing(
        PadiemAiEngineClientError(
            engine_code,
            "internal route https://provider.internal/v1 failed",
            status=500,
        )
    )

    assert failure.code == "unknown_error"
    assert failure.status_code == 500
    assert "provider.internal" not in failure.user_message
    assert failure.user_message == "AI 작업을 처리하지 못했습니다. 다시 시도해 주세요."


@pytest.mark.parametrize("shape", ["files_list", "files", "query_drives"])
def test_pc_plan_has_no_execution_deadline_on_the_engine_wire(shape):
    from app.chat_pc_drive import (
        build_chat_pc_agent_plan, build_chat_pc_files_agent_plan,
    )
    plan = (
        build_chat_pc_agent_plan() if shape == "query_drives"
        else build_chat_pc_files_agent_plan(list_only=shape == "files_list")
    )
    client = FakeClient(start_result=_completed_raw())
    bridge = B62EngineOrchestrationBridge(client=client, store=FakeStore())
    asyncio.run(bridge.start(
        user_id="usr_deadline_test",
        messages=[{"role": "user", "content": "PC files"}],
        skill=get_task_mode("auto"), model_id="test/model",
        user_text="PC files", conversation_id=None, agent_plan=plan,
    ))
    context = client.orchestrate_request["execution_context"]
    assert "timeout_seconds" in context
    assert context["timeout_seconds"] is None
    assert context["trace_id"] == client.orchestrate_request["trace_id"]


def test_general_request_keeps_exact_legacy_context_bytes(monkeypatch):
    import json
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.orchestration_bridge.uuid.uuid4",
        lambda: SimpleNamespace(hex="a" * 32),
    )
    kwargs = dict(
        user_id="usr_deadline_test",
        messages=[{"role": "user", "content": "ordinary question"}],
        skill=get_task_mode("auto"), model_id="test/model",
        conversation_id=None,
    )
    request = B62EngineOrchestrationBridge.build_engine_request(**kwargs)
    legacy = dict(request, execution_context={"trace_id": "b62_orch_" + "a" * 24})
    assert json.dumps(request).encode() == json.dumps(legacy).encode()
    unrelated = B62EngineOrchestrationBridge.build_engine_request(
        **kwargs, agent_plan={"agent_id": "agent:other@1", "steps": []},
    )
    assert unrelated.pop("agent_plan") == {"agent_id": "agent:other@1", "steps": []}
    assert json.dumps(unrelated).encode() == json.dumps(legacy).encode()

def test_pc_context_omitted_or_none_keeps_legacy_request_bytes(monkeypatch):
    import json
    from types import SimpleNamespace
    import app.orchestration_bridge as module
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    kwargs = dict(user_id="usr_1", messages=[{"role": "user", "content": "hello"}],
                  skill=SimpleNamespace(id="auto"), model_id="route/pinned", conversation_id=None)
    expected = {
        "agent": {"id": "b62_auto", "title": "Padiem Chat", "description": "Padiem Chat request",
                  "system_instruction": None, "task_type": "general", "optimize_for": "balanced",
                  "max_tokens": None, "model_policy": {"model": "route/pinned"}},
        "messages": [{"role": "user", "content": "hello"}],
        "trace_id": "b62_orch_" + "a" * 24,
        "execution_context": {"trace_id": "b62_orch_" + "a" * 24},
        "subject_id": "usr_1", "max_retries": 3, "require_evidence": False,
        "require_verification": False,
    }
    wire = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    assert wire(B62EngineOrchestrationBridge.build_engine_request(**kwargs)) == wire(expected)
    assert wire(B62EngineOrchestrationBridge.build_engine_request(**kwargs, pc_tools=None)) == wire(expected)


async def test_verified_pc_bridge_uses_one_progress_opt_in_stream():
    class StreamingClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.calls = []
        async def stream_orchestration(self, request, *, pc_progress=False):
            self.calls.append((request, pc_progress))
            raw = _completed_raw("final")
            for event in raw["events"]:
                yield {"event": event}
            yield {"orchestration": raw}
    client = StreamingClient()
    bridge = B62EngineOrchestrationBridge(client=client, store=FakeStore())
    records = [row async for row in bridge.start_stream(
        user_id="usr_1", messages=[{"role": "user", "content": "list"}],
        skill=get_task_mode("auto"), model_id="route/pinned", user_text="list",
        conversation_id=None, subject_id="subject_1", session_id="chat_pcq_" + "a" * 32,
        pc_tools={"device_id": "node/meshdomain1/pc-1", "allowed_scopes": ["files_list"]},
    )]
    assert len(client.calls) == 1 and client.orchestrate_request is None
    request, flag = client.calls[0]
    assert flag is True and "pc_progress" not in request  # opt-in is a client header
    assert request["pc_tools"] == {"device_id": "node/meshdomain1/pc-1", "allowed_scopes": ["files_list"]}
    assert "agent_plan" not in request and "declared_plan" not in request
    assert request["agent"]["model_policy"] == {"model": "route/pinned"}
    assert records[-1]["result"].answer == "final"


async def _pc_sse(records, *, answer="verified PC result", pending_fields=None,
                  final_records=None):
    from app.claw_live_events import chat_pc_orchestration_sse
    from app.orchestration_bridge import B62OrchestrationResult
    events = [_event("run_started", 1), _event("run_completed", 2)]
    raw = {"execution": {"answer": answer}, "events": events, "approval_pause": None}
    result = B62OrchestrationResult(project_public_orchestration(raw), answer, "user", None)
    async def stream():
        yield {"event": events[0]}
        for record in records:
            yield record
        if final_records is None:
            yield {"event": events[1]}
            yield {"result": result}
        else:
            for record in final_records:
                yield record
    completions = []
    async def complete(value):
        completions.append(value.answer)
        return {"conversation_id": "chat_1"}
    response = chat_pc_orchestration_sse(
        stream(), pc_run_id="chat_pcq_" + "a" * 32, on_completed=complete,
        pending_fields=pending_fields,
    )
    chunks = [chunk async for chunk in response.body_iterator]
    return b"".join(chunks).decode(), completions


async def test_cut_pc_stream_hands_the_run_to_pending_recovery_instead_of_failing():
    """#5895: a stream that stops mid-turn must not read as a refusal.

    The Engine kept running and stored the answer; the relay used to send one
    terminal invalid_engine_stream error frame, which every client renders as a
    connection failure -- including a tab that loaded the page before any fix to
    the client shipped. The relay now sends the pending continuation naming the
    run the server already opened, leaves the run row unmarked so the
    owner-scoped read-back can still deliver the stored result, and never
    claims the turn completed.
    """
    import json
    run = "chat_pcq_" + "a" * 32
    pending = {"run_id": run, "conversation_id": "chat_" + "c" * 32}
    text, completions = await _pc_sse(
        [{"heartbeat": {"run_id": "run_1", "trace_id": "trace_1", "elapsed_ms": 1000}}],
        pending_fields=pending, final_records=[],
    )
    assert "event: error" not in text
    assert "event: done" in text
    values = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    final = values[-1]
    assert final["done"] is True and final["pc_pending"] is True
    assert final["run_id"] == run and final["conversation_id"] == pending["conversation_id"]
    assert completions == []
    # A run that really ended without any opened run still fails closed.
    text, _ = await _pc_sse(
        [{"heartbeat": {"run_id": "run_1", "trace_id": "trace_1", "elapsed_ms": 1000}}],
        final_records=[],
    )
    assert "event: error" in text and "event: done" not in text


async def test_engine_pc_progress_heartbeat_and_result_relay_is_closed_and_ordered():
    import json
    run = "chat_pcq_" + "a" * 32
    records = []
    for sequence, stage in enumerate(("accepted", "picked_up", "executing", "result"), 1):
        records.append({"pc_progress": {
            "pc_run_id": run, "dispatch_id": "dispatch_1", "kind": "command",
            "stage": stage, "sequence": sequence, "elapsed_ms": sequence * 1000,
        }})
        if stage == "picked_up":
            records.append({"heartbeat": {"run_id": "run_1", "trace_id": "trace_1", "elapsed_ms": 3000}})
    text, completions = await _pc_sse(records)
    kinds = [line[7:] for line in text.splitlines() if line.startswith("event: ")]
    assert kinds == ["pc_progress", "pc_progress", "heartbeat", "pc_progress", "pc_progress", "delta", "done"]
    values = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert [v["stage"] for v in values if "stage" in v] == ["accepted", "picked_up", "executing", "result"]
    assert "stage" not in values[2] and "done" not in values[2]
    assert completions == ["verified PC result"]
    assert "PRIVATE" not in text and "tool_arguments" not in text


@pytest.mark.parametrize("extra", ["path", "output", "ops", "secret"])
async def test_pc_relay_rejects_fields_outside_the_display_allowlist(extra):
    value = {"pc_run_id": "chat_pcq_" + "a" * 32, "dispatch_id": "dispatch_1",
             "kind": "command", "stage": "accepted", "sequence": 1, "elapsed_ms": 0,
             extra: "PRIVATE_DO_NOT_LEAK"}
    text, completions = await _pc_sse([{"pc_progress": value}])
    assert "event: error" in text and "event: done" not in text
    assert "PRIVATE_DO_NOT_LEAK" not in text and completions == []


async def test_ordinary_text_on_pc_stream_is_emitted_once_without_pc_execution():
    text, completions = await _pc_sse([{"text_delta": {"delta": "ordinary answer"}}],
                                    answer="ordinary answer")
    assert text.count("event: delta") == 1
    assert '"delta":"ordinary answer"' in text
    assert "pc_progress" not in text and completions == ["ordinary answer"]


async def test_pc_relay_refuses_wrong_run_replay_and_heartbeat_identity():
    run = "chat_pcq_" + "a" * 32
    base = {"pc_run_id": run, "dispatch_id": "dispatch_1", "kind": "read",
            "stage": "accepted", "sequence": 1, "elapsed_ms": 0}
    for records in [
        [{"pc_progress": {**base, "pc_run_id": "chat_pcq_" + "b" * 32}}],
        [{"pc_progress": base}, {"pc_progress": base}],
        [{"heartbeat": {"run_id": "other", "trace_id": "trace_1", "elapsed_ms": 0}}],
    ]:
        text, completions = await _pc_sse(records)
        assert "event: error" in text and "event: done" not in text
        assert completions == []


async def test_stream_approval_resume_keeps_the_original_user_turn_receipt():
    class PausedClient(FakeClient):
        async def stream_orchestration(self, request, *, pc_progress=False):
            raw = _paused_raw()
            for event in raw["events"]:
                yield {"event": event}
            yield {"orchestration": raw}
    client, store = PausedClient(), FakeStore()
    bridge = B62EngineOrchestrationBridge(client=client, store=store)
    run_id = "chat_pcq_" + "a" * 32
    rows = [row async for row in bridge.start_stream(
        user_id="usr_1", subject_id="sub_1", session_id=run_id,
        messages=[{"role": "user", "content": "question"}], skill=get_task_mode("auto"),
        model_id="route/pinned", user_text="question", conversation_id="chat_saved",
        pc_tools={"device_id": "node/meshdomain1/pc-1", "allowed_scopes": ["files_list"]})]
    assert rows[-1]["result"].orchestration["approval_pause"] is not None
    resumed = await bridge.resume(user_id="usr_1", continuation_ref="cont_abcdefgh12345678",
        pause_id="pause_1", outcome="approved")
    assert resumed.stream_run_id == run_id and resumed.conversation_id == "chat_saved"
    assert client.resume_request["session_id"] == run_id
    assert resumed.answer == "완료된 답변"


@pytest.mark.parametrize("wire_record,expected_code,expected_copy,expected_cause", [
    ({"ok": False, "error": {"code": "upstream_auth_error",
       "message": "Model execution failed.", "metadata": {"secret": "PRIVATE_DO_NOT_LEAK"}}},
     "upstream_auth_error", "AI 서비스 인증 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.", None),
    ({"ok": True, "pc_progress": {"stage": "PRIVATE_DO_NOT_LEAK"}},
     "invalid_engine_stream", "AI 작업을 처리하지 못했습니다. 다시 시도해 주세요.",
     {"exception_class": "EngineNdjsonContractError", "record_kind": "pc_progress"}),
])
async def test_real_engine_error_and_malformed_fixture_cross_client_bridge_and_sse(
    wire_record, expected_code, expected_copy, expected_cause,
):
    import json
    from padiem_ai_engine_client import EngineStreamTransportResponse, PadiemAiEngineClient
    from app.claw_live_events import chat_pc_orchestration_sse
    calls, closed, completions = [], [], []
    class Transport:
        async def request(self, **kwargs):
            raise AssertionError("must not fall back to JSON")
        async def stream_request(self, *, method, url, headers, body):
            calls.append({"method": method, "url": url, "headers": headers, "body": body})
            async def chunks():
                try:
                    data = (json.dumps(wire_record) + "\n").encode()
                    yield data[:7]
                    yield data[7:]
                    raise AssertionError("terminal error must stop reading")
                finally:
                    closed.append(True)
            return EngineStreamTransportResponse(
                status=200, chunks=chunks(), headers={"content-type": "application/x-ndjson"})
    client = PadiemAiEngineClient(
        transport=Transport(), app_id="padiem-chat", caller_id="padiem-chat", credential="x" * 64)
    bridge = B62EngineOrchestrationBridge(client=client, store=FakeStore())
    stream = bridge.start_stream(
        user_id="usr_1", subject_id="sub_1", session_id="chat_pcq_" + "a" * 32,
        messages=[{"role": "user", "content": "question"}], skill=get_task_mode("auto"),
        model_id="route/pinned", user_text="question", conversation_id=None,
        pc_tools={"device_id": "node/meshdomain1/pc-1", "allowed_scopes": ["files_list"]})
    async def complete(result):
        completions.append(result)
    response = chat_pc_orchestration_sse(
        stream, pc_run_id="chat_pcq_" + "a" * 32, on_completed=complete)
    text = b"".join([part async for part in response.body_iterator]).decode()
    errors = [json.loads(line[6:])["error"] for line in text.splitlines() if line.startswith("data: ")]
    assert len(errors) == 1
    assert errors[0]["code"] == expected_code
    assert errors[0]["message"] == expected_copy  # keep authored product copy
    assert errors[0].get("cause") == expected_cause
    assert "PRIVATE_DO_NOT_LEAK" not in text
    assert "event: done" not in text and "event: delta" not in text
    assert calls and len(calls) == 1 and closed == [True] and completions == []


async def test_pc_relay_generic_failure_names_class_and_record_kind_without_payload():
    import json
    text, completions = await _pc_sse([{"pc_progress": {"path": "PRIVATE_DO_NOT_LEAK"}}])
    error = next(json.loads(line[6:])["error"] for line in text.splitlines() if line.startswith("data: "))
    assert error["code"] == "invalid_engine_stream"
    assert error["cause"] == {"exception_class": "ValueError", "record_kind": "pc_progress"}
    assert "PRIVATE_DO_NOT_LEAK" not in text and completions == []
    assert "event: done" not in text


async def test_iterator_failure_does_not_blame_previous_valid_record():
    import json
    from app.claw_live_events import chat_pc_orchestration_sse
    async def stream():
        yield {"text_delta": {"delta": "hello"}}
        raise RuntimeError("PRIVATE_DO_NOT_LEAK")
    async def complete(result):
        raise AssertionError("must not commit a failure")
    response = chat_pc_orchestration_sse(
        stream(), pc_run_id="chat_pcq_" + "a" * 32, on_completed=complete)
    text = b"".join([part async for part in response.body_iterator]).decode()
    error = next(json.loads(line[6:])["error"] for line in text.splitlines()
                 if line.startswith("data: ") and "error" in json.loads(line[6:]))
    assert error["code"] == "invalid_engine_stream"
    assert error["cause"] == {"exception_class": "RuntimeError", "record_kind": "unknown"}
    assert "PRIVATE_DO_NOT_LEAK" not in text and "event: done" not in text


@pytest.mark.parametrize("status", ["pending", "running", "completed", None])
@pytest.mark.parametrize("typed_error", [True, False])
async def test_terminal_stream_error_settles_only_the_existing_owner_pc_run(status, typed_error):
    """Real D1 SQL: errors settle pending/running, never completed or text-only turns."""
    import test_5015_multi_tool_result_storage as db
    from app.claw_live_events import chat_pc_orchestration_sse
    connection = db._database()
    try:
        store = db._store(connection)
        if status is not None:
            db._stage_run(connection, status=status, action="pc_files_query")
        async def stream():
            if typed_error:
                raise B62OrchestrationError("upstream_auth_error", "safe error", status_code=403)
            yield {"invalid": "PRIVATE_DO_NOT_LEAK"}
        async def complete(result):
            raise AssertionError("error cannot complete a run")
        async def fail():
            # Mirrors the owner-bound route callback, using the real atomic guard.
            assert not await store.update_claw_run_status(db.OTHER_OWNER, db.RUN, "failed")
            await store.update_claw_run_status(db.OWNER, db.RUN, "failed")
        response = chat_pc_orchestration_sse(stream(), pc_run_id=db.RUN,
            on_completed=complete, on_failed=fail)
        text = b"".join([part async for part in response.body_iterator]).decode()
        assert "event: error" in text and "event: done" not in text
        assert "PRIVATE_DO_NOT_LEAK" not in text
        row = await store.get_claw_run(db.OWNER, db.RUN)
        assert (row["status"] if row else None) == (
            "failed" if status in ("pending", "running") else status)
        assert connection.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0] == 0
    finally:
        connection.close()


async def test_disconnected_pc_stream_does_not_claim_a_terminal_failure():
    from app.claw_live_events import chat_pc_orchestration_sse
    failures = []
    async def stream():
        raise asyncio.CancelledError()
        yield
    async def complete(result):
        raise AssertionError("no final result")
    async def fail():
        failures.append(True)
    response = chat_pc_orchestration_sse(stream(), pc_run_id="chat_pcq_" + "a" * 32,
        on_completed=complete, on_failed=fail)
    with pytest.raises(asyncio.CancelledError):
        _ = [part async for part in response.body_iterator]
    assert failures == []


def test_byok_stream_reference_is_only_on_wire_and_resume_requires_fresh_owner_key():
    import json
    class Client(FakeClient):
        async def stream_orchestration(self, request, **kwargs):
            self.stream_request = request
            yield {'orchestration': _paused_raw()}
    async def run():
        ref = 'unit-opaque-user-key-reference'
        client, store = Client(), FakeStore()
        bridge = B62EngineOrchestrationBridge(client=client, store=store)
        kwargs = dict(user_id='usr_owner', messages=[{'role':'user','content':'hi'}],
            skill=get_task_mode('auto'), model_id='google/unit-model', user_text='hi',
            conversation_id=None, pc_tools=None, subject_id='usr_owner', session_id='chat_unit',
            byok_selection={'provider':'gemini','model':'unit-model'}, user_credential_ref=ref)
        records = [record async for record in bridge.start_stream(**kwargs)]
        assert client.stream_request['user_credential_ref'] == ref
        assert client.stream_request['max_retries'] == 0
        assert ref not in json.dumps(store.saved) and ref not in repr(records)
        assert store.snapshot.engine_request['agent']['model_policy']['user_credential_required'] is True
        with pytest.raises(B62OrchestrationError) as error:
            await bridge.resume(user_id='usr_owner', continuation_ref=store.snapshot.continuation_ref,
                pause_id=store.snapshot.pause_id, outcome='approved')
        assert error.value.code == 'byok_credential_required'
        async def resolve(selection):
            assert selection == {'provider':'gemini','model':'unit-model'}
            return 'google/unit-model', 'unit-rotated-opaque-reference'
        await bridge.resume(user_id='usr_owner', continuation_ref=store.snapshot.continuation_ref,
            pause_id=store.snapshot.pause_id, outcome='approved', user_credential_resolver=resolve)
        assert client.resume_request['user_credential_ref'] == 'unit-rotated-opaque-reference'
        assert 'unit-rotated-opaque-reference' not in json.dumps(store.saved)
    asyncio.run(run())


def test_byok_switch_off_does_not_read_credentials_and_supported_on_uses_owner(monkeypatch):
    from types import SimpleNamespace
    import app.byok_bridge as byok
    from app.config import Settings
    calls = []
    async def resolve(state, *, uid, selection):
        calls.append(uid)
        return SimpleNamespace(endpoint='https://generativelanguage.googleapis.com/v1beta', api_key='unit-secret-no-real-key')
    monkeypatch.setattr(byok, 'resolve_owner_custom_credential', resolve)
    selection = SimpleNamespace(provider='gemini', model='gemini-unit-model')
    state = SimpleNamespace(settings=Settings())
    assert asyncio.run(byok.resolve_reference(state, 'usr_owner', selection)) is None
    assert calls == []
    state.settings = Settings(byok_via_b14=True)
    model, ref = asyncio.run(byok.resolve_reference(state, 'usr_owner', selection))
    assert model == 'google/gemini-unit-model'
    assert calls == ['usr_owner']
    assert 'unit-secret-no-real-key' not in repr(ref)
    assert asyncio.run(byok.resolve_reference(state, 'usr_owner', SimpleNamespace(provider='anthropic',model='claude-unit'))) is None
    assert calls == ['usr_owner']
