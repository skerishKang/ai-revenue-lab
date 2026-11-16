"""#7814 T4 — `_answer_orchestration` 1/2 앞 구간 골든 표.

`_answer_orchestration_intake`로 옮긴 구간(입력·턴 시작, 정책, 대화·사용량·PC
문맥)이 지키던 계약을 리팩터링 전 `main`의 실행 결과 그대로 고정한다.

- 옮긴 구간의 반환 경로마다 상태 코드와 응답 본문을 고정한다.
- 정상 입력 2개(모델 우선 direct / model_first_tool)는 끝까지 돌려 최종 SSE
  이벤트·대역 호출 기록·timing 줄의 범주 필드와 측정 구간을 고정한다.
- #7881 경로(PC 결과 없음 → 고정 안내·`reason=pc_dispatch_no_result_in_window`)
  도 포함한다.

timing 줄의 `*_ms` 값은 실행마다 달라지므로 범주 필드만 고정하고, 어떤 구간이
측정됐는지(`measured`)를 별도로 고정해 elapsed 기준점이 바뀌지 않게 한다.

골든은 같은 방식으로 리팩터링 전 `main`에서 먼저 떴다
(`fixtures/answer_orchestration_7814_intake.json`). 값은 전부 합성값이다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import orchestration_routes as routes
from app.b14_client import ChatStreamEvent, ChatToolCall

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "fixtures" / "answer_orchestration_7814_intake.json"
)

DEVICE_ID = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
PC_TEXT = "내 PC의 D드라이브 파일 목록을 봐줘"
TIMING_LOGGER = "padiem_chat.orchestration_timing"


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
        self.events = events
        self.calls = []

    def stream_text_auto(self, messages, **kwargs):
        self.calls.append({
            "skill": str(kwargs.get("skill")),
            "tools": [tool.name for tool in (kwargs.get("tools") or ())],
            "tool_choice": str(kwargs.get("tool_choice")),
        })
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
        return {"result": SimpleNamespace(
            answer="엔진 PC 답변",
            orchestration={"events": [], "answer": "엔진 PC 답변"},
            decision_status=None,
            conversation_id="chat_engine_pc",
            user_text=kwargs.get("user_text"),
        )}


class _Store:
    def __init__(self, conversation=None):
        self.appended = []
        self.conversation = conversation

    async def get_conversation(self, uid, conversation_id, **kwargs):
        return self.conversation

    async def append_exchange(self, user_id, conversation_id, user_text, answer, **kwargs):
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


def _request(payload, *, model_first=False, stream=False, b14=None, gate=None,
             store=None, bridge=None):
    headers = [(b"content-type", b"application/json")]
    if stream:
        headers.append((b"accept", b"application/x-ndjson"))
    request = Request({
        "type": "http", "method": "POST",
        "path": "/api/orchestration", "headers": headers,
    })
    request.scope["app"] = SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge or _Bridge(),
        orchestration_stream_enabled=stream,
        model_first_enabled=model_first,
        history_store=store or _Store(),
        usage_gate_enforced=gate is not None,
        usage_gate=gate,
        b14_client=b14,
        auto_grounding=None,
        settings=SimpleNamespace(runtime_mode="mock"),
    ))
    request._body = json.dumps(payload).encode("utf-8")
    return request


def _direct_events():
    return [
        ChatStreamEvent(delta_content="안녕"),
        ChatStreamEvent(delta_content="하세요"),
        ChatStreamEvent(done=True),
    ]


def _tool_events():
    return [ChatStreamEvent(
        tool_call=ChatToolCall(id="tc1", name="files", arguments={}),
    )]


def _pc_context():
    return {
        "pc_tools": {"device_id": DEVICE_ID,
                     "allowed_scopes": ["files_list", "files"]},
        "subject_id": "subject_1",
        "workspace_id": "workspace_1",
    }


def _install(monkeypatch, *, pc_context=None, tools_supported=True, lane=None):
    import app.chat_pc_drive as drive
    import app.pc_work_context as pc_work

    bridge = _Bridge()
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")

    async def _pc_context_fn(request, *, uid, requested_device_id=None, user_text=None):
        return pc_context

    async def _supported(request, model_id):
        return tools_supported

    async def _no_pc_text(request, *, owner_id):
        return None

    monkeypatch.setattr(drive, "resolve_chat_pc_stream_context", _pc_context_fn)
    monkeypatch.setattr(drive, "chat_pc_route_declares_tools", _supported)
    monkeypatch.setattr(pc_work, "build_pc_work_context_text", _no_pc_text)
    if lane is not None:
        monkeypatch.setattr(drive, "execute_chat_pc_drive_lane", lane)
    return bridge


def _timing(caplog):
    fields, measured = {}, []
    for record in caplog.records:
        line = record.getMessage()
        if not line.startswith("orchestration_timing_com2 "):
            continue
        for token in line.split()[1:]:
            key, _, value = token.partition("=")
            if key.endswith("_ms"):
                if value != "-1.0":
                    measured.append(key)
            else:
                fields[key] = value
    return {"fields": fields, "measured": measured}


def _body(response):
    raw = getattr(response, "body", b"")
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return raw.decode("utf-8", "replace")


def _events(text):
    """NDJSON body -> ordered event names; JSON body -> its top-level keys."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item.get("type") or item.get("event") or sorted(item))
    return out


def snapshot(case: str, monkeypatch, caplog) -> dict:
    caplog.set_level(logging.INFO, logger=TIMING_LOGGER)
    bridge = None
    b14 = None
    gate = None
    store = None
    lane = None
    pc_context = None
    payload = {"messages": [{"role": "user", "content": "안녕"}], "tier": "free"}
    model_first = False

    if case == "no_bridge":
        bridge = _Bridge()
        monkeypatch.setattr(routes, "_bridge", lambda request: None)
        monkeypatch.setattr(routes, "auth_ready", lambda request: True)
        monkeypatch.setattr(routes, "current_user_id", lambda request: "owner")
    elif case == "no_user":
        bridge = _Bridge()
        monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
        monkeypatch.setattr(routes, "auth_ready", lambda request: True)
        monkeypatch.setattr(routes, "current_user_id", lambda request: None)
    elif case == "not_applicable":
        bridge = _install(monkeypatch)
        payload = dict(payload, attachments=[{"name": "a.txt"}])
    elif case == "usage_denied":
        gate = _Gate(allowed=False)
        bridge = _install(monkeypatch)
    elif case == "conversation_not_found":
        store = _Store(conversation=None)
        bridge = _install(monkeypatch)
        payload = dict(payload, conversation_id="missing")
    elif case in ("model_first_direct", "model_first_tool", "pc_no_result"):
        model_first = True
        b14 = _B14(_tool_events() if case != "model_first_direct" else _direct_events())
        if case != "model_first_direct":
            pc_context = _pc_context()
            payload = {
                "messages": [{"role": "user", "content": PC_TEXT}],
                "tier": "plus", "device_id": DEVICE_ID,
            }

            async def _lane(request, **kwargs):
                if case == "pc_no_result":
                    from app.pc_dispatch_wait_window import (
                        PC_DISPATCH_NO_RESULT_CODE, note_wait_reason,
                    )
                    note_wait_reason(PC_DISPATCH_NO_RESULT_CODE)
                    from app.pc_dispatch_wait_window import PC_DISPATCH_NO_RESULT_TEXT
                    return PC_DISPATCH_NO_RESULT_TEXT, "chat_pc_saved"
                return "PC 파일 결과", "chat_pc_saved"

            lane = _lane
        else:
            gate = _Gate()
        bridge = _install(monkeypatch, pc_context=pc_context, lane=lane)
    else:
        raise AssertionError(case)

    request = _request(payload, model_first=model_first, b14=b14,
                       gate=gate, store=store, bridge=bridge)

    async def run():
        response = await routes.api_orchestration(request)
        return response

    response = asyncio.run(run())
    text = _body(response)
    result = {
        "status": response.status_code,
        "media_type": getattr(response, "media_type", None),
        "events": _events(text),
        "body": text,
        "timing": _timing(caplog),
        "calls": {
            "b14": b14.calls if b14 is not None else [],
            "bridge_started": len(bridge.started) if bridge is not None else 0,
            "bridge_streamed": len(bridge.streamed) if bridge is not None else 0,
        },
    }
    return result


CASES = (
    "no_bridge", "no_user", "not_applicable", "usage_denied",
    "conversation_not_found", "model_first_direct",
    "model_first_tool", "pc_no_result",
)


def test_golden_is_the_pre_refactor_intake_table():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert set(golden) == set(CASES)
    assert golden["no_bridge"]["status"] == 503
    assert golden["no_user"]["status"] == 401
    assert golden["not_applicable"]["status"] == 422
    assert golden["usage_denied"]["status"] == 429
    assert golden["conversation_not_found"]["status"] == 422
    assert golden["model_first_direct"]["timing"]["fields"]["path"] == "model_first_direct"
    assert golden["model_first_tool"]["timing"]["fields"]["path"] == "model_first_tool"
    assert golden["pc_no_result"]["timing"]["fields"]["reason"] == "pc_dispatch_no_result_in_window"


@pytest.mark.parametrize("case", CASES)
def test_intake_snapshot_matches_the_pre_refactor_golden(case, monkeypatch, caplog):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[case]
    assert snapshot(case, monkeypatch, caplog) == golden
