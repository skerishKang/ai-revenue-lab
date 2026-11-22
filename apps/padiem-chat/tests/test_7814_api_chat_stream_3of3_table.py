"""T4 _api_chat_stream_body 3/3 골든 (#7814).

grounding·dispatch 준비와 최종 StreamingResponse 생성이 남긴 반환 경로와
정상 SSE 이벤트 순서·대역 호출을 고정한다. 1/3·2/3 골든 파일은 수정하지 않는다.
골든은 리팩터 전 origin/main(52eb050d2)에서 뽑는다.

재생성은 리팩터 전 main에서만 실행한다:
  PADIEM_REGEN_7814_STREAM_3OF3=1 pytest apps/padiem-chat/tests/test_7814_api_chat_stream_3of3_table.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import chat_routes
from app.app_factory import create_app
from app.grounding import GroundingError
from test_7814_api_chat_stream_table import (
    _TraceStore,
    _TraceStreamClient,
    _json,
    _payload,
    _request,
    _settings,
    _stream_row,
)
from test_7814_api_chat_stream_2of3_table import _install as _install_2of3

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "test_7814_api_chat_stream_3of3_table_golden.json"
)

EVIDENCE = SimpleNamespace(
    id="src-3of3",
    title="검색 근거 제목",
    url="https://example.test/source-3of3",
    snippet="검색 근거 요약",
    retrieved_at="2026-11-17T00:00:00Z",
    provider="fixture-provider",
    source_type="web",
)


class _Grounding:
    def __init__(self, events, mode):
        self.events = events
        self.mode = mode

    async def prepare(self, messages, **kwargs):
        self.events.append({
            "call": "grounding.prepare",
            "messages": messages,
            "skill": None if kwargs.get("skill") is None else kwargs["skill"].id,
            "additional_system_context": kwargs.get("additional_system_context"),
            "util_scope": kwargs.get("util_scope"),
            "explicit_search": kwargs.get("explicit_search"),
        })
        if self.mode == "grounding_error":
            raise GroundingError(502, "fake_grounding_code", "fake grounding notice")
        if self.mode == "web_search":
            prepared = SimpleNamespace(
                context="[웹 검색 근거]\n검색 근거 요약",
                evidence=(EVIDENCE,),
            )
            return SimpleNamespace(prepared=prepared, error=None)
        return SimpleNamespace(prepared=None, error=None)


def _install(monkeypatch, opts, app, events):
    _install_2of3(monkeypatch, opts, app, events)
    mode = opts.get("mode")

    async def guard(*args, **kwargs):
        events.append({"call": "guard"})
        if mode == "guard_error":
            raise RuntimeError("fake guard failure")
        return None

    async def pc_tools(*args, **kwargs):
        events.append({"call": "pc_tools", "model_id": kwargs.get("model_id")})
        if mode == "pc_error":
            raise RuntimeError("fake pc tools failure")
        if mode == "pc_declared":
            return (SimpleNamespace(id="fake.pc.tool"),)
        return ()

    async def connector_tools(*args, **kwargs):
        events.append({"call": "connector_tools", "intent": kwargs.get("intent")})
        if mode == "connector_error":
            raise RuntimeError("fake connector tools failure")
        return ()

    monkeypatch.setattr(chat_routes, "create_guard_from_request", guard)
    monkeypatch.setattr(chat_routes, "_chat_pc_tools_for_turn", pc_tools)
    monkeypatch.setattr(chat_routes, "_chat_connector_tools_for_turn", connector_tools)


CASES = [
    ("기본_SSE", "success", _json(_payload("hello fake")), {}),
    ("웹검색_근거_SSE", "success", _json(_payload("search fake", web_search=True)), {"mode": "web_search"}),
    ("그라운딩_오류_공지", "success", _json(_payload("hello fake")), {"mode": "grounding_error"}),
    ("PC_도구_선언", "success", _json(_payload("hello fake")), {"mode": "pc_declared"}),
    ("커넥터_도구_예외", "exception", _json(_payload("hello fake")), {"mode": "connector_error"}),
    ("가드_예외", "exception", _json(_payload("hello fake")), {"mode": "guard_error"}),
    ("PC도구_예외", "exception", _json(_payload("hello fake")), {"mode": "pc_error"}),
]


async def _run_case(name, kind, body, opts):
    events = []
    store = _TraceStore(events, opts)
    app = create_app(_settings(opts), history_store=store, project_file_store=store)
    app.state.usage_gate_enforced = False
    app.state.calendar_store = None
    app.state.b14_client = _TraceStreamClient(events)
    app.state.auto_grounding = _Grounding(events, opts.get("mode"))
    request = _request(body)
    request.scope["app"] = app

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, opts, app, events)
        try:
            response = await chat_routes.api_chat_stream(request)
        except Exception as exc:
            if kind != "exception":
                raise
            return {
                "case": name, "kind": kind,
                "exception": {"type": type(exc).__name__, "args": list(exc.args)},
                "calls": events,
            }
        if kind == "exception":
            raise AssertionError(name)
        chunks = [chunk async for chunk in response.body_iterator]
        return {
            "case": name, "kind": kind,
            "response": _stream_row(response, chunks),
            "calls": events,
        }


@pytest.mark.asyncio
async def test_api_chat_stream_3of3_table_is_identical_to_golden():
    rows = []
    for name, kind, body, opts in CASES:
        rows.append(json.loads(json.dumps(await _run_case(name, kind, body, dict(opts)), ensure_ascii=False)))

    if os.environ.get("PADIEM_REGEN_7814_STREAM_3OF3") == "1":
        GOLDEN_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert rows == golden
