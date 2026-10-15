"""Native PADIEM Calendar shared adapter tests (#4745)."""

from __future__ import annotations

import asyncio

import app.native_calendar_adapter as adapter
from app.calendar_store import InMemoryCalendarStore


async def _execute(store, uid, plan, *, turn_key=None):
    request = type("Req", (), {"app": type("App", (), {"state": None})()})()
    # Monkeypatched module-level auth/workspace helpers are used instead.
    return await adapter.execute_native_calendar_plan(
        request,
        store,
        uid,
        plan,
        turn_key=turn_key,
    )


def test_native_calendar_read_and_scoped_create(monkeypatch):
    store = InMemoryCalendarStore()
    async def workspace(_request, uid):
        return "workspace_" + uid
    monkeypatch.setattr(adapter, "_require_owner", lambda request: "alice")
    monkeypatch.setattr(adapter, "_resolve_memory_workspace", workspace)

    # Default 401 if auth missing.
    # Chat-style plan claims no authority identifiers.
    plan = {
        "version": adapter.NATIVE_CALENDAR_TOOL_VERSION,
        "op": "create_appointment",
        "args": {
            "appointment_type": "timed",
            "title": "회의",
            "date": "2026-10-23",
            "start_at": "2026-10-23T15:00:00+09:00",
            "end_at": "2026-10-23T16:00:00+09:00",
            "timezone": "Asia/Seoul",
        },
    }
    result = asyncio.run(_execute(store, "alice", plan, turn_key="turn-1"))
    assert result["ok"] is True
    appointment = result["appointment"]
    assert appointment["title"] == "회의"
    assert appointment["calendar_item_id"].startswith("item_apt_apt_")

    # Same turn/payload replays one record.
    replay = asyncio.run(_execute(store, "alice", plan, turn_key="turn-1"))
    assert replay["replayed"] is True
    assert replay["appointment"]["calendar_item_id"] == appointment["calendar_item_id"]

    read_plan = {
        "version": adapter.NATIVE_CALENDAR_TOOL_VERSION,
        "op": "read",
        "args": {"start_date": "2026-10-23", "end_date": "2026-10-23", "timezone": "Asia/Seoul"},
    }
    read = asyncio.run(_execute(store, "alice", read_plan))
    assert read["items"] and read["items"][0]["title"] == "회의"
    assert read["empty_native_calendar"] is False


def test_native_calendar_mismatched_duplicate_returns_conflict(monkeypatch):
    store = InMemoryCalendarStore()
    async def workspace(_request, uid):
        return "workspace_" + uid
    monkeypatch.setattr(adapter, "_require_owner", lambda request: "alice")
    monkeypatch.setattr(adapter, "_resolve_memory_workspace", workspace)
    base = {
        "version": adapter.NATIVE_CALENDAR_TOOL_VERSION,
        "op": "create_appointment",
        "args": {
            "appointment_type": "date_only",
            "title": "Visit",
            "date": "2026-10-23",
        },
    }
    asyncio.run(_execute(store, "alice", base, turn_key="turn-2"))
    changed = {
        "version": adapter.NATIVE_CALENDAR_TOOL_VERSION,
        "op": "create_appointment",
        "args": {
            "appointment_type": "date_only",
            "title": "Visit changed",
            "date": "2026-10-23",
        },
    }
    try:
        asyncio.run(_execute(store, "alice", changed, turn_key="turn-2"))
        raised = False
    except adapter.NativeCalendarAdapterError as exc:
        raised = True
        assert exc.code == "conflict"
        assert exc.status_code == 409
    assert raised


def test_native_calendar_rejects_accessor_override(monkeypatch):
    store = InMemoryCalendarStore()
    try:
        adapter.parse_native_calendar_plan({"version": "native-calendar-tool.v1", "op": "read", "args": {}})
    except adapter.NativeCalendarAdapterError:
        pass
    result = None
    async def _workspace(_request, uid):
        return "workspace_" + uid
    monkeypatch.setattr(adapter, "_require_owner", lambda request: "alice")
    monkeypatch.setattr(adapter, "_resolve_memory_workspace", _workspace)
    try:
        asyncio.run(adapter.execute_native_calendar_plan(
            type("Req", (), {})(), store, "alice", {
                "version": adapter.NATIVE_CALENDAR_TOOL_VERSION,
                "op": "create_appointment",
                "args": {"title": "x", "date": "2026-10-23", "workspace_id": "workspace_bob"},
            },
            turn_key="t",
        ))
    except adapter.NativeCalendarAdapterError as exc:
        assert exc.code == "invalid_or_ambiguous"


def test_native_calendar_workspace_missing_is_unavailable(monkeypatch):
    store = InMemoryCalendarStore()
    async def workspace(_request, uid):
        return None
    monkeypatch.setattr(adapter, "_require_owner", lambda request: "alice")
    monkeypatch.setattr(adapter, "_resolve_memory_workspace", workspace)
    plan = {
        "version": adapter.NATIVE_CALENDAR_TOOL_VERSION,
        "op": "read",
        "args": {"start_date": "2026-10-23", "end_date": "2026-10-23", "timezone": "Asia/Seoul"},
    }
    try:
        asyncio.run(adapter.execute_native_calendar_plan(
            type("Req", (), {})(), store, "alice", plan
        ))
        raised = False
    except adapter.NativeCalendarAdapterError as exc:
        raised = True
        assert exc.code == "unavailable"
        assert exc.status_code == 503
    assert raised


def test_native_calendar_read_rejects_browser_authority_keys(monkeypatch):
    store = InMemoryCalendarStore()
    async def workspace(_request, uid):
        return "workspace_" + uid
    monkeypatch.setattr(adapter, "_require_owner", lambda request: "alice")
    monkeypatch.setattr(adapter, "_resolve_memory_workspace", workspace)
    plan = {
        "version": adapter.NATIVE_CALENDAR_TOOL_VERSION,
        "op": "read",
        "args": {"start_date": "2026-10-23", "end_date": "2026-10-23", "timezone": "Asia/Seoul", "workspace_id": "foreign"},
    }
    try:
        asyncio.run(adapter.execute_native_calendar_plan(
            type("Req", (), {})(), store, "alice", plan
        ))
        raised = False
    except adapter.NativeCalendarAdapterError as exc:
        raised = True
        assert exc.code == "invalid_or_ambiguous"
    assert raised
