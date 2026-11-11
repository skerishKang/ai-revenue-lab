"""#7459 6-(2): PC 턴 30초 조기 타임아웃·model_first_failed 누수 및 확인 대기(approval_pause) 오류 종료 재현 시험."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN, ENGINE_ORCHESTRATE_PATH
from starlette.requests import Request

from app import orchestration_routes as routes
from app.b14_client import ChatStreamEvent, ChatToolCall
from app.chat_pc_drive import CHAT_PC_QUERY_AGENT_ID, _execute_chat_pc_files_lane, build_chat_pc_agent_plan
from app.chat_pc_errors import ChatPCApprovalPause
from app.local_engine_transport import LocalEngineHttpTransport, LocalEngineTransportError
from app.orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError
from app.orchestration_stream import ndjson_answer
from app.orchestration_timing import OrchestrationTiming
from app.request_timing import reset_timing, start_timing


DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
PC_TEXT = "내 PC의 D드라이브 파일 목록을 봐줘"

PAUSE_ORCHESTRATION = {
    "events": [
        {
            "event_id": "evt_1",
            "run_id": "run_1",
            "trace_id": "trace_1",
            "app_id": "padiem-chat",
            "kind": "approval_paused",
            "sequence": 1,
        }
    ],
    "approval_pause": {
        "status": "paused",
        "continuation_id": "pause_7459",
        "requirement": "user_confirmation",
        "expires_at": "2099-01-01T00:00:00+00:00",
    },
    "continuation_ref": "cont_7459_pause_ref",
    "answer": None,
}


class _DelayedJsonEngine:
    def __init__(self, body: bytes, *, delay: float) -> None:
        self._body = body
        self._delay = delay

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return
        await asyncio.sleep(self._delay)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": self._body, "more_body": False})


class _RunningEngine:
    def __init__(self, app) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False, lifespan="off")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("stub engine did not start")
            time.sleep(0.01)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def __exit__(self, *exc_info) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class _Stream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def aclose(self):
        return None


class _B14:
    def __init__(self, events):
        self._events = list(events)

    def stream_text_auto(self, messages, *, skill=None, additional_system_context=None, tools=(), tool_choice=None):
        return _Stream(self._events)


class _Store:
    async def append_exchange(self, user_id, conversation_id, user_text, answer, **kwargs):
        return "chat_saved"


class _BridgeStub:
    ready = True


def _request(payload, *, stream: bool, b14):
    headers = [(b"content-type", b"application/json")]
    if stream:
        headers.append((b"accept", b"application/x-ndjson"))
    req = Request({"type": "http", "method": "POST", "path": "/api/orchestration", "headers": headers})
    req.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=_BridgeStub(),
            orchestration_stream_enabled=stream,
            model_first_enabled=True,
            history_store=_Store(),
            usage_gate_enforced=False,
            usage_gate=None,
            b14_client=b14,
            auto_grounding=None,
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    req._body = json.dumps(payload).encode("utf-8")
    return req


def _call(request):
    async def _run():
        res = await routes.api_orchestration(request)
        if hasattr(res, "body_iterator"):
            body = b""
            async for chunk in res.body_iterator:
                body += chunk.encode() if isinstance(chunk, str) else chunk
            return SimpleNamespace(status_code=res.status_code, body=body, media_type=res.media_type)
        return res

    return asyncio.run(_run())


async def test_7459_pc_plan_with_no_deadline_outlives_completed_default_timeout_and_records_p01_once():
    """컴2 재현: 일반 완료 타임아웃(0.08s)보다 긴 PC 작업(0.25s)이 조기 절단되지 않고 p01 시간은 1회만 기록된다."""
    stub = _DelayedJsonEngine(b'{"ok":true,"orchestration":{"events":[]}}', delay=0.25)
    with _RunningEngine(stub) as origin:
        transport = LocalEngineHttpTransport(origin, timeout=0.08, stream_timeout=2.0)
        pc_body = json.dumps(
            {
                "agent_plan": build_chat_pc_agent_plan(),
                "execution_context": {"trace_id": "t1", "timeout_seconds": None},
            }
        ).encode("utf-8")
        timing_bucket, timing_token = start_timing()
        try:
            started = time.monotonic()
            response = await transport.request(
                method="POST",
                url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}",
                headers={"X-Padiem-Engine-Caller": "b62-chat-host"},
                body=pc_body,
            )
            elapsed_ms = (time.monotonic() - started) * 1000.0
            recorded_p01 = timing_bucket.snapshot()["p01"]
        finally:
            reset_timing(timing_token)
            await transport.aclose()

    assert response.status == 200
    assert elapsed_ms >= 200.0
    assert recorded_p01 < elapsed_ms * 1.5

    stub_ordinary = _DelayedJsonEngine(b'{"ok":true}', delay=0.25)
    with _RunningEngine(stub_ordinary) as origin:
        transport = LocalEngineHttpTransport(origin, timeout=0.08, stream_timeout=2.0)
        try:
            with pytest.raises(LocalEngineTransportError) as exc_info:
                await transport.request(
                    method="POST",
                    url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}",
                    headers={"X-Padiem-Engine-Caller": "b62-chat-host"},
                    body=b'{"execution_context":{"trace_id":"t2"}}',
                )
            assert exc_info.value.timed_out is True
        finally:
            await transport.aclose()


async def test_7459_bridge_translates_local_transport_errors_instead_of_leaking_value_error():
    class _FailingClient:
        def __init__(self, exc):
            self._exc = exc

        async def orchestrate(self, wire):
            raise self._exc

    class _NoopStateStore:
        pass

    timeout_bridge = B62EngineOrchestrationBridge(
        client=_FailingClient(LocalEngineTransportError("timed out", timed_out=True)),
        store=_NoopStateStore(),
    )
    with pytest.raises(B62OrchestrationError) as timeout_exc:
        await timeout_bridge.start(
            user_id="usr_test",
            messages=[{"role": "user", "content": "질문"}],
            skill=SimpleNamespace(id="auto", title="Chat", description="Chat"),
            model_id="test/model",
            user_text="질문",
            conversation_id=None,
        )
    assert timeout_exc.value.code == "upstream_timeout"
    assert timeout_exc.value.status_code == 504

    conn_bridge = B62EngineOrchestrationBridge(
        client=_FailingClient(LocalEngineTransportError("connection failed", timed_out=False)),
        store=_NoopStateStore(),
    )
    with pytest.raises(B62OrchestrationError) as conn_exc:
        await conn_bridge.start(
            user_id="usr_test",
            messages=[{"role": "user", "content": "질문"}],
            skill=SimpleNamespace(id="auto", title="Chat", description="Chat"),
            model_id="test/model",
            user_text="질문",
            conversation_id=None,
        )
    assert conn_exc.value.code == "upstream_unavailable"
    assert conn_exc.value.status_code == 502


async def test_7459_pc_files_lane_raises_approval_pause_without_marking_run_failed(monkeypatch):
    notices = []

    class _PauseStore:
        async def record_chat_pc_drive_run(self, **kwargs):
            return "chat_paused_conv"

        async def get_claw_run(self, uid, run_id):
            return {"run_id": run_id, "conversation_id": "chat_paused_conv", "result_summary": "pending"}

        async def append_local_task_result(self, **kwargs):
            notices.append(kwargs)
            return True

    class _PauseBridge(B62EngineOrchestrationBridge):
        def __init__(self):
            super().__init__(client=object(), store=object())

        async def start(self, **kwargs):
            return SimpleNamespace(
                orchestration=PAUSE_ORCHESTRATION,
                answer=None,
                user_text=kwargs["user_text"],
                conversation_id=kwargs["conversation_id"],
            )

    import app.pc_delegation_routes as delegation

    async def _no_delegation(request, uid):
        return None

    monkeypatch.setattr(delegation, "load_pc_delegation", _no_delegation)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(orchestration_bridge=_PauseBridge())))

    with pytest.raises(ChatPCApprovalPause) as pause_info:
        await _execute_chat_pc_files_lane(
            req,
            store=_PauseStore(),
            uid="usr_" + "1" * 32,
            subject_id="sub_1",
            workspace_id="ws_1",
            user_text="파일 수정해줘",
            skill=SimpleNamespace(id="auto"),
            model_id="test/model",
            conversation_id=None,
            device_id=DEVICE_ID,
            agent_plan={"agent_id": CHAT_PC_QUERY_AGENT_ID, "steps": [{"step_id": "write_file", "tool_id": "claw.pc.write_file"}]},
        )

    assert pause_info.value.conversation_id == "chat_paused_conv"
    assert pause_info.value.orchestration["continuation_ref"] == "cont_7459_pause_ref"
    assert notices == []


def test_7459_model_first_ndjson_and_json_emit_orchestration_pause_instead_of_error(monkeypatch):
    import app.chat_pc_drive as drive
    import app.pc_work_context as pc_context_module

    async def _pausing_lane(request, **kwargs):
        raise ChatPCApprovalPause(
            PAUSE_ORCHESTRATION,
            conversation_id="chat_paused_conv",
            run_id="chat_pcq_" + "a" * 32,
        )

    async def _pc_context(request, *, uid, requested_device_id=None, user_text=None):
        return {
            "pc_tools": {"device_id": DEVICE_ID, "allowed_scopes": ["files_list", "files"]},
            "subject_id": "subject_1",
            "workspace_id": "workspace_1",
        }

    async def _supported(request, model_id):
        return True

    async def _no_pc_text(request, *, owner_id):
        return None

    monkeypatch.setattr(routes, "_bridge", lambda request: _BridgeStub())
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")
    monkeypatch.setattr(drive, "resolve_chat_pc_stream_context", _pc_context)
    monkeypatch.setattr(drive, "chat_pc_route_declares_tools", _supported)
    monkeypatch.setattr(drive, "execute_chat_pc_drive_lane", _pausing_lane)
    monkeypatch.setattr(pc_context_module, "build_pc_work_context_text", _no_pc_text)

    stream_req = _request(
        {"messages": [{"role": "user", "content": PC_TEXT}], "tier": "plus", "device_id": DEVICE_ID, "stream": 1},
        stream=True,
        b14=_B14([ChatStreamEvent(tool_call=ChatToolCall(id="tc_pause", name="files", arguments={}))]),
    )
    stream_res = _call(stream_req)
    frames = [json.loads(raw) for raw in stream_res.body.splitlines() if raw.strip()]
    assert [f["type"] for f in frames] == ["meta", "progress", "orchestration_pause"]
    assert frames[1]["kind"] == "tool_started"
    assert frames[2]["orchestration"]["approval_pause"]["continuation_id"] == "pause_7459"
    assert frames[2]["conversation_id"] == "chat_paused_conv"
    assert all(f["type"] != "error" for f in frames)
    assert all(f.get("kind") != "tool_failed" for f in frames)

    json_req = _request(
        {"messages": [{"role": "user", "content": PC_TEXT}], "tier": "plus", "device_id": DEVICE_ID},
        stream=False,
        b14=_B14([ChatStreamEvent(tool_call=ChatToolCall(id="tc_pause2", name="files", arguments={}))]),
    )
    json_res = _call(json_req)
    assert json_res.status_code == 200
    body = json.loads(json_res.body)
    assert body["answer"] is None
    assert body["orchestration"]["approval_pause"]["continuation_id"] == "pause_7459"
    assert body["conversation_id"] == "chat_paused_conv"


def test_7459_ndjson_answer_emits_orchestration_pause_instead_of_engine_execution_failed():
    class _PauseStreamBridge:
        async def start_stream(self, **kwargs):
            yield {
                "result": SimpleNamespace(
                    answer=None,
                    orchestration=PAUSE_ORCHESTRATION,
                    conversation_id="chat_ndjson_pause",
                )
            }

        async def start(self, **kwargs):
            raise AssertionError("buffered fallback must not run on approval_pause")

    async def _run():
        return [
            json.loads(chunk.decode("utf-8"))
            async for chunk in ndjson_answer(
                bridge=_PauseStreamBridge(),
                stream_kwargs={},
                buffered_kwargs={},
                timing=OrchestrationTiming(),
                on_completed=lambda r: {},
            )
        ]

    frames = asyncio.run(_run())
    assert [f["type"] for f in frames] == ["meta", "orchestration_pause"]
    assert frames[1]["orchestration"]["continuation_ref"] == "cont_7459_pause_ref"
