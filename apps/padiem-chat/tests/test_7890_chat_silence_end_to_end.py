"""#7890 1 — a silent PC turn is bounded by the turn's own answer budget.

The fake dispatch never returns. The test drives the real Chat orchestration
route and captures the budget the route hands to the PC tool lane, then checks
the fixed notice and the timing-line reason the production path emits.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import orchestration_routes as routes
from app import pc_dispatch_wait_window as window
from app.b14_client import ChatStreamEvent, ChatToolCall
from app.orchestration_bridge import B62EngineOrchestrationBridge

TIMING_LOGGER = "padiem_chat.orchestration_timing"
NOTICE = window.PC_DISPATCH_NO_RESULT_TEXT


class _Events:
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
    def stream_text_auto(self, messages, **kwargs):
        return _Events([ChatStreamEvent(
            tool_call=ChatToolCall(id="tc1", name="files_list", arguments={}),
        )])


class _Bridge(B62EngineOrchestrationBridge):
    ready = True

    def __init__(self):
        super().__init__(client=object(), store=object())

    async def start(self, **kwargs):
        await asyncio.sleep(30)


class _Store:
    async def get_conversation(self, uid, conversation_id, **kwargs):
        return None

    async def append_exchange(self, *args, **kwargs):
        return "chat_saved"

    async def begin_chat_stream_turn(self, **fields):
        return "chat_saved"

    async def finish_chat_stream_turn(self, **fields):
        return "chat_saved"


class _Gate:
    async def authorize(self, *, raw_ip, user_id):
        return SimpleNamespace(allowed=True, code="usage_denied", user_message="",
                               status_code=429, retry_after_seconds=1)


def _request(b14, bridge, gate, store):
    request = Request({
        "type": "http", "method": "POST", "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge,
        orchestration_stream_enabled=False,
        model_first_enabled=True,
        history_store=store,
        usage_gate_enforced=True,
        usage_gate=gate,
        b14_client=b14,
        auto_grounding=None,
        settings=SimpleNamespace(runtime_mode="mock", auth_mode="google"),
    ))
    request._body = json.dumps({
        "messages": [{"role": "user", "content": "안녕"}], "tier": "plus",
    }).encode("utf-8")
    return request


def _timing_fields(caplog):
    fields = {}
    for record in caplog.records:
        line = record.getMessage()
        if not line.startswith("orchestration_timing_com2 "):
            continue
        for token in line.split()[1:]:
            key, _, value = token.partition("=")
            if not key.endswith("_ms"):
                fields[key] = value
    return fields


@pytest.fixture(autouse=True)
def _fresh_reason():
    window.reset_wait_reason()


def test_a_silent_pc_turn_has_a_bounded_budget_a_notice_and_a_reason(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=TIMING_LOGGER)
    import app.chat_pc_drive as drive
    import app.pc_work_context as pc_work

    bridge, store, b14 = _Bridge(), _Store(), _B14()
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "usr_" + "1" * 32)

    async def _pc_context(request, *, uid, requested_device_id=None, user_text=None):
        return {
            "pc_tools": {"device_id": "dev_1", "allowed_scopes": ["files_list"]},
            "subject_id": "subject_1", "workspace_id": "workspace_1",
        }

    async def _supported(request, model_id):
        return True

    async def _no_context_text(request, *, owner_id):
        return None

    monkeypatch.setattr(drive, "resolve_chat_pc_stream_context", _pc_context)
    monkeypatch.setattr(drive, "chat_pc_route_declares_tools", _supported)
    monkeypatch.setattr(pc_work, "build_pc_work_context_text", _no_context_text)

    captured = {}

    async def _silent_lane(request, **kwargs):
        captured["result_wait_seconds"] = kwargs.get("result_wait_seconds")
        window.note_wait_reason(window.PC_DISPATCH_NO_RESULT_CODE)
        return NOTICE, "chat_saved"

    monkeypatch.setattr(drive, "execute_chat_pc_drive_lane", _silent_lane)

    request = _request(b14, bridge, _Gate(), store)
    response = asyncio.run(routes.api_orchestration(request))
    body = response.body.decode("utf-8", "replace") if isinstance(response.body, bytes) \
        else str(response.body)

    assert NOTICE in body, body[:300]
    wait = captured["result_wait_seconds"]
    assert 0 < wait <= routes.DEFAULT_ANSWER_BUDGET_MS / 1000.0, wait
    fields = _timing_fields(caplog)
    assert fields.get("reason") == window.PC_DISPATCH_NO_RESULT_CODE, fields
    assert fields.get("path") == "model_first_tool", fields
