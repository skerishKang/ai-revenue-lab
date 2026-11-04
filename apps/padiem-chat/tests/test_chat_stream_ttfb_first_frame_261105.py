"""TTFB first-frame contract for /api/chat/stream (261105).

The response headers and the first SSE frame (``meta`` = accepted, thinking)
must reach the wire without waiting for the model's first token. A slow first
token can no longer hide behind a dead connection: once headers are committed,
dispatch failures travel as in-stream ``error`` frames with the same safe code
and Korean message the JSON contract carried. Stage times are logged once per
request with no request content in them.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest
from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.b14_streaming import B14StreamEvent

from app.b14_client import ChatRuntimeError
from app.config import Settings
from app.main import create_app

GENERIC_MESSAGE = "답변을 불러오지 못했습니다. 다시 시도해 주세요."
INTERNAL_SENTINEL = "raw-internal-failure-detail-must-never-leak"


def _payload() -> dict:
    return {"messages": [{"role": "user", "content": "안녕"}]}


def _event(content: str | None = None, *, done: bool = False) -> B14StreamEvent:
    return B14StreamEvent(
        model="secret/free-model",
        delta_content=content,
        route=B14RouteMetadata(route_mode="auto"),
        done=done,
    )


class ScriptedClient:
    """Events raised before the first delta are dispatch-stage failures."""

    def __init__(self, script):
        self.script = list(script)
        self.closed = False

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None):
        try:
            for item in self.script:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            self.closed = True


class LateTokenClient:
    """Holds the model's first token back until the test releases it."""

    def __init__(self):
        self.release = asyncio.Event()
        self.token_sent = False

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None):
        await self.release.wait()
        self.token_sent = True
        yield _event("첫 토큰")
        yield _event(done=True)


def _app_with_client(client) -> object:
    app = create_app(Settings(runtime_mode="mock"))
    app.state.b14_client = client
    app.state.usage_gate_enforced = False
    return app


def _drive_app(scope, payload, send):
    body = json.dumps(payload).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def call():
        await app_for_scope(scope, receive, send)

    async def app_for_scope(scope, receive, send):
        raise NotImplementedError

    return call


async def _collect_stream(app, payload, client):
    """Drive the ASGI app directly so frame timing is observable.

    Returns the response-start message and every body chunk, with two promises:
    ``headers_seen`` resolves when the response headers went out, and
    ``meta_seen`` resolves when the first frame was flushed.
    """
    state = {"start": None, "chunks": [], "requested": False}
    headers_seen = asyncio.Event()
    meta_seen = asyncio.Event()
    request_done = asyncio.Event()

    body = json.dumps(payload).encode("utf-8")

    async def receive():
        if not state["requested"]:
            state["requested"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await request_done.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            state["start"] = message
            headers_seen.set()
        elif message["type"] == "http.response.body":
            state["chunks"].append(message.get("body", b""))
            if b"event: meta" in b"".join(state["chunks"]):
                meta_seen.set()
            if not message.get("more_body"):
                request_done.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat/stream",
        "raw_path": b"/api/chat/stream",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "headers": [(b"content-type", b"application/json")],
    }
    task = asyncio.ensure_future(app(scope, receive, send))
    await asyncio.wait_for(headers_seen.wait(), 5)
    await asyncio.wait_for(meta_seen.wait(), 5)
    # The meta frame reached the wire while the model's first token was still
    # held back: the flush did not wait for the token.
    assert client.token_sent is False
    client.release.set()
    await asyncio.wait_for(task, 10)
    return state


def test_headers_and_meta_flush_before_the_model_first_token():
    client = LateTokenClient()
    state = asyncio.run(_collect_stream(_app_with_client(client), _payload(), client))

    start = state["start"]
    assert start["status"] == 200
    headers = dict(start["headers"])
    assert b"text/event-stream" in headers[b"content-type"]
    body = b"".join(state["chunks"]).decode("utf-8")
    meta_index = body.index("event: meta")
    delta_index = body.index("event: delta")
    done_index = body.index("event: done")
    assert meta_index < delta_index < done_index
    assert client.token_sent is True


def test_dispatch_chat_runtime_error_maps_to_an_instream_error_frame():
    client = ScriptedClient([ChatRuntimeError(502, "upstream_execution_failed", GENERIC_MESSAGE)])
    app = _app_with_client(client)

    collected = asyncio.run(_collect_simple(app, _payload()))
    assert collected.content_type.startswith("text/event-stream")
    body = collected.body
    assert "event: meta" in body
    error = json.loads(body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])["error"]
    assert error["code"] == "upstream_execution_failed"
    assert error["message"] == GENERIC_MESSAGE
    assert client.closed is True


def test_unexpected_dispatch_exception_never_leaks_raw_detail():
    client = ScriptedClient([RuntimeError(INTERNAL_SENTINEL)])
    app = _app_with_client(client)

    collected = asyncio.run(_collect_simple(app, _payload()))
    body = collected.body
    error = json.loads(body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])["error"]
    assert error["code"] == "upstream_route_error"
    assert error["message"] == GENERIC_MESSAGE
    assert INTERNAL_SENTINEL not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body


def test_empty_upstream_stream_maps_to_an_instream_error_frame():
    client = ScriptedClient([_event(done=True)])
    app = _app_with_client(client)

    collected = asyncio.run(_collect_simple(app, _payload()))
    body = collected.body
    error = json.loads(body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])["error"]
    assert error["code"] == "empty_upstream_answer"
    assert "AI가 표시할 답변을 만들지 못했습니다" in error["message"]


class _Collected:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body
        self.content_type = headers.get(b"content-type", b"").decode("latin-1")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


async def _collect_simple(app, payload):
    """Collect the whole SSE body through the raw ASGI interface."""
    state = {"start": None, "chunks": [], "requested": False}
    done = asyncio.Event()
    body = json.dumps(payload).encode("utf-8")

    async def receive():
        if not state["requested"]:
            state["requested"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await done.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            state["start"] = message
        elif message["type"] == "http.response.body":
            state["chunks"].append(message.get("body", b""))
            if not message.get("more_body"):
                done.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat/stream",
        "raw_path": b"/api/chat/stream",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "headers": [(b"content-type", b"application/json")],
    }
    await asyncio.wait_for(app(scope, receive, send), 10)
    start = state["start"]
    headers = {key.lower(): value for key, value in start["headers"]}
    return _Collected(start["status"], headers, b"".join(state["chunks"]).decode("utf-8"))


def test_stage_timing_line_is_logged_once_without_request_content(caplog):
    client = ScriptedClient([_event("첫째"), _event(done=True)])
    app = _app_with_client(client)

    with caplog.at_level(logging.INFO, logger="padiem_chat.chat_stream_timing"):
        collected = asyncio.run(_collect_simple(app, _payload()))

    lines = [record.getMessage() for record in caplog.records if "chat_stream_ttfb" in record.getMessage()]
    assert len(lines) == 1
    line = lines[0]
    for field in ("validate_ms=", "history_ms=", "grounding_ms=", "lane_ms=", "dispatch_ms=",
                  "first_token_ms=", "first_frame_flush_ms=", "outcome=completed"):
        assert field in line
    assert "안녕" not in line
    assert "첫째" not in line


def test_restore_owner_context_uses_the_prefetched_projection_without_a_second_read():
    from app.chat_routes import _restore_owner_chat_model_messages
    from app.history import HistoryContextIncomplete

    reads: list[str] = []

    class Store:
        async def get_conversation_model_context(self, owner_id, conversation_id, *, product_scope):
            reads.append("model_context")
            return {"id": conversation_id, "messages": [{"role": "assistant", "content": "이전 답"}]}

    messages = asyncio.run(_restore_owner_chat_model_messages(
        Store(), "owner-1", "chat_1", {"id": "chat_1"},
        [{"role": "user", "content": "다음 질문"}],
        owned_context={"id": "chat_1", "messages": [{"role": "assistant", "content": "이전 답"}]},
    ))
    assert reads == [], "the prefetched projection must remove the second read"
    assert [m["role"] for m in messages] == ["assistant", "user"]

    class EmptyStore:
        async def get_conversation_model_context(self, owner_id, conversation_id, *, product_scope):
            reads.append("model_context")
            return None

    reads.clear()
    with pytest.raises(HistoryContextIncomplete):
        asyncio.run(_restore_owner_chat_model_messages(
            EmptyStore(), "owner-1", "chat_1", {"id": "chat_1"},
            [{"role": "user", "content": "다음 질문"}],
        ))
