"""T4 _api_chat_stream_body 2/3 골든 (#7814).

1/3 골든은 그대로 두고, 이번에 옮기는 Custom·드라이브/PC preflight·캘린더
구간의 반환 경로와 정상 SSE 이벤트 순서·대역 호출·저장 행을 새 표에 고정한다.
골든은 리팩터 전 origin/main(3a1c281a0)에서 뽑는다.

재생성은 리팩터 전 main에서만 실행한다:
  PADIEM_REGEN_7814_STREAM_2OF3=1 pytest apps/padiem-chat/tests/test_7814_api_chat_stream_2of3_table.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import chat_routes
from app.app_factory import create_app
from app.byok_client import CustomProviderError
from app.byok_credentials import CustomProviderSelectionError
from app.drive_general_grounding import DriveGroundingError
from app.native_calendar_adapter import NativeCalendarAdapterError
from test_7814_api_chat_stream_table import (
    CID,
    UID,
    _TraceStore,
    _TraceStreamClient,
    _StubAutoGrounding,
    _install as _install_base,
    _json,
    _payload,
    _request,
    _response_row,
    _settings,
    _stream_row,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "test_7814_api_chat_stream_2of3_table_golden.json"
)

CUSTOM = {"provider": "fake-provider", "model": "fake-model"}
DRIVE_SOURCE = {
    "title": "fake source",
    "url": "https://example.test/fake",
    "retrieved_at": "2026-01-01T00:00:00Z",
    "source_type": "google_drive",
}


def _install(monkeypatch, opts, app, events):
    _install_base(monkeypatch, opts, app, events)
    if opts.get("calendar_store"):
        app.state.calendar_store = SimpleNamespace()

    async def drive(request, text):
        events.append({"call": "external.drive", "text": text})
        mode = opts.get("drive")
        if mode == "error":
            return DriveGroundingError("fake_drive_code", "fake drive failure", 503)
        if mode == "context":
            return ("fake drive context", (DRIVE_SOURCE,))
        return (None, ())

    async def complete_custom(request, **kwargs):
        events.append({
            "call": "custom.complete",
            "messages": kwargs.get("messages"),
            "reference_context": kwargs.get("reference_context"),
        })
        mode = opts.get("custom")
        if mode == "selection_error":
            raise CustomProviderSelectionError("fake selection failure")
        if mode == "provider_error":
            raise CustomProviderError(502, "fake_provider_code", "fake provider failure")
        return {"answer": "fake custom answer"}

    async def calendar_result(*args, **kwargs):
        events.append({"call": "calendar.native", "user_text": args[3] if len(args) > 3 else None})
        mode = opts.get("calendar")
        if mode == "error":
            raise NativeCalendarAdapterError("fake_calendar_code", "fake calendar failure", 400)
        if mode == "none":
            return None
        return {"answer": "fake calendar answer"}

    async def reachable(*args, **kwargs):
        events.append({"call": "calendar.reachable"})
        return opts.get("calendar_reachable", False)

    monkeypatch.setattr(chat_routes, "drive_general_grounding", drive)
    monkeypatch.setattr(chat_routes, "_complete_custom_chat", complete_custom)
    monkeypatch.setattr(chat_routes, "try_native_calendar_chat", calendar_result)
    monkeypatch.setattr(chat_routes, "calendar_read_reachable", reachable)


CASES = [
    ("Custom_선택_거부", "error", _json(_payload("custom fake", custom=CUSTOM)), {"custom": "selection_error"}),
    ("Custom_공급자_오류", "error", _json(_payload("custom fake", custom=CUSTOM)), {"custom": "provider_error"}),
    ("드라이브_오류", "error", _json(_payload("fake question")), {"drive": "error"}),
    ("사용량_거부", "error", _json(_payload("fake question")), {"usage": "denied"}),
    ("캘린더_저장소_없음", "error", _json(_payload("내일 오전 9시 회의 일정 등록해줘 fake")), {"calendar_store": False}),
    ("캘린더_어댑터_오류", "error", _json(_payload("내일 오전 9시 회의 일정 등록해줘 fake")), {"calendar_store": True, "calendar": "error"}),
    ("캘린더_결과_없음", "error", _json(_payload("내일 오전 9시 회의 일정 등록해줘 fake")), {"calendar_store": True, "calendar": "none"}),
    ("Custom_성공", "success", _json(_payload("custom fake", custom=CUSTOM)), {}),
    ("캘린더_성공", "success", _json(_payload("내일 오전 9시 회의 일정 등록해줘 fake")), {"calendar_store": True, "calendar": "success", "drive": "context"}),
]


async def _run_case(name, kind, body, opts):
    events = []
    store = _TraceStore(events, opts)
    app = create_app(_settings(opts), history_store=store, project_file_store=store)
    app.state.b14_client = _TraceStreamClient(events)
    app.state.auto_grounding = _StubAutoGrounding(events)
    app.state.calendar_store = None
    if "usage" in opts:
        async def authorize(**kwargs):
            return SimpleNamespace(
                allowed=False,
                code="fake_usage_code",
                user_message="fake usage denial",
                status_code=429,
                retry_after_seconds=7,
            )

        app.state.usage_gate_enforced = True
        app.state.usage_gate = SimpleNamespace(authorize=authorize)
    else:
        app.state.usage_gate_enforced = False
    request = _request(body)
    request.scope["app"] = app

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, opts, app, events)
        response = await chat_routes.api_chat_stream(request)
        if kind == "success":
            chunks = [chunk async for chunk in response.body_iterator]
            return {"case": name, "kind": kind, "response": _stream_row(response, chunks), "calls": events}
    assert hasattr(response, "body"), name
    return {"case": name, "kind": kind, "response": _response_row(response)}


@pytest.mark.asyncio
async def test_api_chat_stream_2of3_table_is_identical_to_golden():
    rows = []
    for name, kind, body, opts in CASES:
        rows.append(json.loads(json.dumps(await _run_case(name, kind, body, dict(opts)), ensure_ascii=False)))

    if os.environ.get("PADIEM_REGEN_7814_STREAM_2OF3") == "1":
        GOLDEN_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert rows == golden
