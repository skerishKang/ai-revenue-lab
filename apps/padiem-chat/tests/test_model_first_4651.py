"""#4651 model-first: answer directly unless the model asks for a PC tool."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from starlette.requests import Request

from app import orchestration_routes as routes
from app.b14_client import ChatStreamEvent, ChatToolCall
from app.model_first import model_first_enabled


DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
PC_TEXT = "내 PC의 D드라이브 파일 목록을 봐줘"


class _Stream:
    def __init__(self, events):
        self._events = list(events)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def aclose(self):
        self.closed = True


class _B14:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def stream_text_auto(
        self, messages, *, skill=None, additional_system_context=None,
        tools=(), tool_choice=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "skill": skill,
                "additional_system_context": additional_system_context,
                "tools": tuple(tools),
                "tool_choice": tool_choice,
            }
        )
        return _Stream(self.events)


class _Bridge:
    ready = True

    def __init__(self):
        self.started = []
        self.streamed = []

    async def start(self, **kwargs):
        self.started.append(kwargs)
        return SimpleNamespace(
            answer="엔진 답변",
            orchestration={"events": [], "answer": "엔진 답변"},
            decision_status=None,
            conversation_id="chat_engine",
            user_text=kwargs.get("user_text"),
        )

    async def start_stream(self, **kwargs):
        self.streamed.append(kwargs)
        yield {
            "result": SimpleNamespace(
                answer="엔진 PC 답변",
                orchestration={"events": [], "answer": "엔진 PC 답변"},
                decision_status=None,
                conversation_id="chat_engine_pc",
                user_text=kwargs.get("user_text"),
            )
        }


class _Store:
    def __init__(self):
        self.appended = []

    async def append_exchange(
        self, user_id, conversation_id, user_text, answer, **kwargs,
    ):
        self.appended.append((user_text, answer))
        return "chat_saved"

    async def begin_chat_stream_turn(self, **fields):
        return "chat_engine_pc"

    async def finish_chat_stream_turn(self, **fields):
        return "chat_engine_pc"


class _Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    async def authorize(self, *, raw_ip, user_id):
        self.calls.append((raw_ip, user_id))
        return SimpleNamespace(
            allowed=self.allowed,
            code="usage_denied",
            user_message="사용 한도를 초과했습니다.",
            status_code=429,
            retry_after_seconds=1,
        )


def _evidence():
    return [
        SimpleNamespace(
            id="web-1",
            title="예시",
            url="https://example.test/a",
            snippet="근거",
            retrieved_at="2026-11-03T00:00:00Z",
            provider="test",
            source_type="web",
        )
    ]


class _Grounding:
    async def prepare(
        self, messages, *, skill=None, additional_system_context=None,
        explicit_search=False,
    ):
        return SimpleNamespace(
            prepared=SimpleNamespace(context="웹 검색 근거", evidence=_evidence()),
            error=None,
        )


def _request(
    payload,
    *,
    model_first=False,
    stream=False,
    b14=None,
    gate=None,
    auto_grounding=None,
    bridge=None,
):
    headers = [(b"content-type", b"application/json")]
    if stream:
        headers.append((b"accept", b"application/x-ndjson"))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/orchestration",
            "headers": headers,
        }
    )
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=bridge or _Bridge(),
            orchestration_stream_enabled=stream,
            model_first_enabled=model_first,
            history_store=_Store(),
            usage_gate_enforced=gate is not None,
            usage_gate=gate,
            b14_client=b14,
            auto_grounding=auto_grounding,
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def _call(request):
    async def run():
        response = await routes.api_orchestration(request)
        if hasattr(response, "body_iterator"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk.encode() if isinstance(chunk, str) else chunk
            return SimpleNamespace(
                status_code=response.status_code,
                body=body,
                media_type=response.media_type,
            )
        return response

    return asyncio.run(run())


def _install(monkeypatch, *, pc_context=None, tools_supported=True, lane=None):
    import app.chat_pc_drive as drive
    import app.pc_work_context as pc_context_module

    bridge = _Bridge()
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")

    async def _pc_context(request, *, uid, requested_device_id=None, user_text=None):
        return pc_context

    async def _supported(request, model_id):
        return tools_supported

    async def _no_pc_text(request, *, owner_id):
        return None

    monkeypatch.setattr(drive, "resolve_chat_pc_stream_context", _pc_context)
    monkeypatch.setattr(drive, "chat_pc_route_declares_tools", _supported)
    monkeypatch.setattr(pc_context_module, "build_pc_work_context_text", _no_pc_text)
    if lane is not None:
        monkeypatch.setattr(drive, "execute_chat_pc_drive_lane", lane)
    return bridge


def _direct_events():
    return [
        ChatStreamEvent(delta_content="안녕"),
        ChatStreamEvent(delta_content="하세요"),
        ChatStreamEvent(done=True),
    ]


def _timing_lines(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("orchestration_timing_com2 ")
    ]


def test_flag_is_off_by_default():
    assert model_first_enabled({}) is False
    assert model_first_enabled({"PADIEM_CHAT_MODEL_FIRST": "1"}) is True
    assert model_first_enabled({"PADIEM_CHAT_MODEL_FIRST": "off"}) is False


def test_route_installation_carries_the_switch_and_both_entries_pass_it():
    from pathlib import Path

    from starlette.applications import Starlette

    app = Starlette()
    routes.install_orchestration_routes(app, None, model_first_enabled=True)
    assert app.state.model_first_enabled is True

    root = Path(__file__).resolve().parents[1]
    host = (root / "app" / "local_cpython.py").read_text(encoding="utf-8")
    worker = (root / "worker.py").read_text(encoding="utf-8")
    assert "model_first_enabled=model_first_enabled(os.environ)" in host
    assert "model_first_enabled=model_first_enabled(self.env)" in worker


def test_switch_off_keeps_the_engine_path(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="padiem_chat.orchestration_timing")
    b14 = _B14(_direct_events())
    bridge = _install(monkeypatch)

    response = _call(
        _request(
            {"messages": [{"role": "user", "content": "안녕"}], "tier": "free"},
            model_first=False,
            b14=b14,
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body)["answer"] == "엔진 답변"
    assert len(bridge.started) == 1
    assert b14.calls == []
    assert " path=engine " in _timing_lines(caplog)[-1]


def test_hello_is_answered_directly_without_the_engine(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="padiem_chat.orchestration_timing")
    b14 = _B14(_direct_events())
    gate = _Gate()
    bridge = _install(monkeypatch)
    request = _request(
        {"messages": [{"role": "user", "content": "안녕"}], "tier": "free"},
        model_first=True,
        b14=b14,
        gate=gate,
    )

    response = _call(request)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"] == "안녕하세요"
    assert body["conversation_id"] == "chat_saved"
    assert set(body) == {"orchestration", "answer", "decision_status", "conversation_id"}
    assert "type" not in body
    assert bridge.started == [] and bridge.streamed == []
    assert len(b14.calls) == 1
    assert len(gate.calls) == 1
    assert b14.calls[0]["tools"] == ()
    assert request.app.state.history_store.appended == [("안녕", "안녕하세요")]
    timing_line = _timing_lines(caplog)[-1]
    assert " path=model_first_direct " in timing_line
    assert "usage_ms=-1.0" not in timing_line


def test_pc_tool_call_uses_the_existing_lane_and_only_allowed_tools(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="padiem_chat.orchestration_timing")
    b14 = _B14(
        [ChatStreamEvent(tool_call=ChatToolCall(id="tc1", name="files", arguments={}))]
    )
    sent = []

    async def lane(request, **kwargs):
        sent.append(kwargs)
        return "PC 파일 결과", "chat_pc_saved"

    bridge = _install(
        monkeypatch,
        pc_context={
            "pc_tools": {
                "device_id": DEVICE_ID,
                "allowed_scopes": ["files_list", "files"],
            },
            "subject_id": "subject_1",
            "workspace_id": "workspace_1",
        },
        lane=lane,
    )
    request = _request(
        {
            "messages": [{"role": "user", "content": PC_TEXT}],
            "tier": "plus",
            "device_id": DEVICE_ID,
        },
        model_first=True,
        b14=b14,
    )

    response = _call(request)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"] == "PC 파일 결과"
    assert body["conversation_id"] == "chat_pc_saved"
    assert bridge.started == [] and bridge.streamed == []
    assert len(sent) == 1
    assert sent[0]["selected_tool"] == "files"
    offered = {tool.name for tool in b14.calls[0]["tools"]}
    assert offered == {"files", "files_list"}
    assert b14.calls[0]["tool_choice"] == "auto"
    assert " path=model_first_tool " in _timing_lines(caplog)[-1]


def test_web_grounding_keeps_evidence_on_the_direct_answer(monkeypatch):
    b14 = _B14(_direct_events())
    _install(monkeypatch)
    request = _request(
        {"messages": [{"role": "user", "content": "오늘 뉴스 알려줘"}], "tier": "free"},
        model_first=True,
        b14=b14,
        auto_grounding=_Grounding(),
    )

    response = _call(request)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"] == "안녕하세요"
    assert body["answer_status"] == "answered_with_evidence"
    assert body["evidence"][0]["id"] == "web-1"
    assert body["tool"]["id"] == "web_search"
    assert "웹 검색 근거" in (b14.calls[0]["additional_system_context"] or "")


def test_usage_denial_stops_before_any_model_or_engine_call(monkeypatch):
    b14 = _B14(_direct_events())
    bridge = _install(monkeypatch)
    gate = _Gate(allowed=False)
    request = _request(
        {"messages": [{"role": "user", "content": "안녕"}], "tier": "free"},
        model_first=True,
        b14=b14,
        gate=gate,
    )

    response = _call(request)

    assert response.status_code == 429
    assert b14.calls == []
    assert bridge.started == [] and bridge.streamed == []
    assert len(gate.calls) == 1


def test_offline_selected_pc_withholds_tools_and_explains_the_pc(monkeypatch):
    import app.pc_work_context as pc_context_module

    b14 = _B14(_direct_events())
    bridge = _install(monkeypatch)

    async def _offline(request, *, owner_id):
        return "선택한 PC가 꺼져 있거나 연결이 끊겨 있습니다. PC 작업을 실행하지 마세요."

    monkeypatch.setattr(pc_context_module, "build_pc_work_context_text", _offline)
    request = _request(
        {"messages": [{"role": "user", "content": PC_TEXT}], "tier": "free"},
        model_first=True,
        b14=b14,
    )

    response = _call(request)

    assert response.status_code == 200
    assert bridge.started == [] and bridge.streamed == []
    assert b14.calls[0]["tools"] == ()
    assert "꺼져" in (b14.calls[0]["additional_system_context"] or "")
    assert json.loads(response.body)["answer"] == "안녕하세요"


def test_model_without_tool_support_keeps_the_pc_engine_lane(monkeypatch):
    from app.model_policy import ResolvedModelPolicy

    b14 = _B14(_direct_events())
    bridge = _install(
        monkeypatch,
        pc_context={
            "pc_tools": {"device_id": DEVICE_ID, "allowed_scopes": ["files"]},
            "subject_id": "subject_1",
            "workspace_id": "workspace_1",
        },
        tools_supported=False,
    )
    monkeypatch.setattr(
        routes,
        "resolve_request_model_policy",
        lambda messages: ResolvedModelPolicy(
            model_id="google/gemma-3-27b-it", messages=messages,
        ),
    )
    request = _request(
        {"messages": [{"role": "user", "content": PC_TEXT}], "tier": "free"},
        model_first=True,
        b14=b14,
    )

    response = _call(request)

    assert response.status_code == 200
    assert b14.calls == []
    assert len(bridge.streamed) == 1


def test_pc_tools_are_intersected_with_the_server_scope(monkeypatch):
    b14 = _B14(_direct_events())
    _install(
        monkeypatch,
        pc_context={
            "pc_tools": {"device_id": DEVICE_ID, "allowed_scopes": ["query_drives"]},
            "subject_id": "subject_1",
            "workspace_id": "workspace_1",
        },
    )
    request = _request(
        {"messages": [{"role": "user", "content": PC_TEXT}], "tier": "free"},
        model_first=True,
        b14=b14,
    )

    _call(request)

    assert [tool.name for tool in b14.calls[0]["tools"]] == ["query_drives"]


def test_write_tool_is_offered_only_when_the_turn_asks_for_a_change():
    from app.model_first import pc_tools_for_context

    context = {
        "pc_tools": {
            "device_id": DEVICE_ID,
            "allowed_scopes": ["files", "files_write"],
        }
    }
    read_only = {tool.name for tool in pc_tools_for_context(context, "파일 목록 보여줘")}
    writing = {tool.name for tool in pc_tools_for_context(context, "이 파일 고쳐줘")}
    assert read_only == {"files"}
    assert writing == {"files", "files_write"}


def test_direct_path_uses_the_same_dispatch_guard(monkeypatch):
    b14 = _B14(_direct_events())
    _install(monkeypatch)
    seen = {}

    async def _guard(request, model_id, store, catalog):
        seen["guard"] = (model_id, store, catalog)
        return "guard"

    def _apply(client, guard):
        seen["apply"] = (client, guard)
        return client

    monkeypatch.setattr(routes, "create_guard_from_request", _guard)
    monkeypatch.setattr(routes, "apply_guard_to_client", _apply)
    request = _request(
        {"messages": [{"role": "user", "content": "안녕"}], "tier": "free"},
        model_first=True,
        b14=b14,
    )
    request.app.state.central_model_policy_store = "policy-store"
    request.app.state.b14_catalog_source = "catalog"

    response = _call(request)

    assert response.status_code == 200
    assert isinstance(seen["guard"][0], str) and seen["guard"][0]
    assert seen["guard"][1:] == ("policy-store", "catalog")
    assert seen["apply"] == (b14, "guard")
    assert len(b14.calls) == 1


def test_unoffered_tool_call_is_refused_before_the_lane(monkeypatch):
    b14 = _B14(
        [ChatStreamEvent(tool_call=ChatToolCall(id="tc1", name="files_write", arguments={}))]
    )
    sent = []

    async def lane(request, **kwargs):
        sent.append(kwargs)
        return "쓰기 결과", "chat_pc_saved"

    _install(
        monkeypatch,
        pc_context={
            "pc_tools": {"device_id": DEVICE_ID, "allowed_scopes": ["query_drives"]},
            "subject_id": "subject_1",
            "workspace_id": "workspace_1",
        },
        lane=lane,
    )
    request = _request(
        {"messages": [{"role": "user", "content": "드라이브만 보여줘"}], "tier": "free"},
        model_first=True,
        b14=b14,
    )

    response = _call(request)

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "model_first_tool_not_allowed"
    assert sent == []


def test_ndjson_direct_answer_streams_and_saves_once(monkeypatch):
    b14 = _B14(_direct_events())
    _install(monkeypatch)
    request = _request(
        {"messages": [{"role": "user", "content": "안녕"}], "tier": "free", "stream": 1},
        model_first=True,
        stream=True,
        b14=b14,
    )

    response = _call(request)

    assert response.status_code == 200
    frames = [
        json.loads(chunk.decode("utf-8"))
        for chunk in response.body.splitlines()
        if chunk.strip()
    ]
    assert [frame["type"] for frame in frames] == ["meta", "delta", "delta", "done"]
    assert "".join(frame["text"] for frame in frames if frame["type"] == "delta") == "안녕하세요"
    assert frames[-1]["conversation_id"] == "chat_saved"
    assert len(request.app.state.history_store.appended) == 1


def test_ndjson_model_first_tool_sends_p01_progress_frames(monkeypatch):
    b14 = _B14(
        [ChatStreamEvent(tool_call=ChatToolCall(id="model-private-id", name="files", arguments={}))]
    )
    sent = []

    async def lane(request, **kwargs):
        sent.append(kwargs)
        return "PC 작업 결과", "chat_pc_saved"

    _install(
        monkeypatch,
        pc_context={
            "pc_tools": {"device_id": DEVICE_ID, "allowed_scopes": ["files_list", "files"]},
            "subject_id": "subject_private",
            "workspace_id": "workspace_private",
        },
        lane=lane,
    )
    request = _request(
        {
            "messages": [{"role": "user", "content": PC_TEXT}],
            "tier": "plus",
            "device_id": DEVICE_ID,
            "stream": 1,
        },
        model_first=True,
        stream=True,
        b14=b14,
    )

    response = _call(request)
    frames = [json.loads(line) for line in response.body.splitlines() if line.strip()]

    assert response.status_code == 200
    assert [frame["type"] for frame in frames] == ["meta", "progress", "progress", "delta", "done"]
    assert frames[1] == {
        "type": "progress", "kind": "tool_started", "sequence": 1, "label": "PC 작업 중",
    }
    assert frames[2] == {
        "type": "progress", "kind": "tool_completed", "sequence": 2, "label": "PC 작업 완료",
    }
    assert all(set(frame) <= {"type", "kind", "sequence", "label", "stage", "elapsed_ms", "text", "done", "stream",
                               "conversation_id", "message_id", "usage", "answer_status", "evidence", "tool"}
               for frame in frames)
    assert "model-private-id" not in response.body.decode("utf-8")
    assert "workspace_private" not in response.body.decode("utf-8")
    assert len(sent) == 1 and sent[0]["selected_tool"] == "files"
    assert response.media_type == "application/x-ndjson"
