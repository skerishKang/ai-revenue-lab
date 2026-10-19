import asyncio
from datetime import date

import pytest
from contextlib import contextmanager
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.calendar_store import InMemoryCalendarStore
from app import native_calendar_adapter as adapter
from test_b54_claw_general_p01_routing import (
    _settings,
    _AuthStore,
    SESSION_COOKIE,
    SIGNED_IN_USER_ID,
    create_session_token,
    _make_adapter,
)


class _HistoryStore(_AuthStore):
    async def append_exchange(self, user_id, conversation_id, user_text, answer, product_scope=None):
        return "conv-4745"


@contextmanager
def client_factory():
    history = _HistoryStore()
    calendar = InMemoryCalendarStore()
    app = create_app(
        settings=_settings(),
        history_store=history,
        calendar_store=calendar,
        claw_p01_adapter=_make_adapter(),
    )
    app.state.usage_gate_enforced = False
    c = TestClient(app, base_url="https://chat.example.test")
    c.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    with c:
        yield c


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    async def workspace(_request, uid):
        return "workspace-" + uid

    monkeypatch.setattr(adapter, "_require_owner", lambda request: SIGNED_IN_USER_ID)
    monkeypatch.setattr(adapter, "_resolve_memory_workspace", workspace)


async def _appointments(app):
    owner = SIGNED_IN_USER_ID
    store = app.state.calendar_store
    return await store.list_appointments(
        "workspace-" + owner,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        limit=100,
    )


def test_chat_native_create_json_calendar_store():
    with client_factory() as c:
        resp = c.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "내일 오전 9시 회의 일정 등록해줘"}],
                "timezone": "Asia/Seoul",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "native_calendar" in body or "일정이 등록" in str(body)


def test_chat_native_read_sse():
    with client_factory() as c:
        resp = c.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "이번 주 일정 보여줘"}], "timezone": "Asia/Seoul"},
        )
        assert resp.status_code == 200, resp.text
        assert "text/event-stream" in (resp.headers.get("content-type") or "")
        assert "event:" in resp.text


def test_claw_native_read():
    with client_factory() as c:
        resp = c.post(
            "/api/claw/general",
            json={"messages": [{"role": "user", "content": "이번 주 일정 보여줘"}], "tier": "free", "timezone": "Asia/Seoul"},
        )
        assert resp.status_code == 200, resp.text
        assert "data:" in resp.text


def test_chat_create_then_claw_cross_readback():
    with client_factory() as c:
        created = c.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "내일 오전 9시 회의 일정 등록해줘"}],
                "timezone": "Asia/Seoul",
            },
        )
        assert created.status_code == 200, created.text
        appointments = asyncio.run(_appointments(c.app))
        assert appointments, appointments
        assert any(item.title == "회의" for item in appointments)

        read_resp = c.post(
            "/api/claw/general",
            json={"messages": [{"role": "user", "content": "이번 주 일정 보여줘"}], "tier": "free", "timezone": "Asia/Seoul"},
        )
        assert read_resp.status_code == 200, read_resp.text
        assert "data:" in read_resp.text


def test_claw_create_then_chat_cross_readback():
    with client_factory() as c:
        created = c.post(
            "/api/claw/general",
            json={
                "messages": [{"role": "user", "content": "내일 오전 9시 회의 일정 등록해줘"}],
                "tier": "free",
                "timezone": "Asia/Seoul",
            },
        )
        assert created.status_code == 200, created.text
        appointments = asyncio.run(_appointments(c.app))
        assert any(item.title == "회의" for item in appointments)

        read_resp = c.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "이번 주 일정 보여줘"}], "timezone": "Asia/Seoul"},
        )
        assert read_resp.status_code == 200, read_resp.text
        assert "text/event-stream" in (read_resp.headers.get("content-type") or "")


def test_duplicate_chat_create_replays_one():
    with client_factory() as c:
        payload = {
            "messages": [{"role": "user", "content": "내일 오전 9시 회의 일정 등록해줘"}],
            "timezone": "Asia/Seoul",
        }
        first = c.post("/api/chat", json=payload)
        second = c.post("/api/chat", json=payload)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        appointments = asyncio.run(_appointments(c.app))
        assert len(appointments) == 1, len(appointments)

def test_distinct_client_turn_ids_allow_distinct_identical_chat_creates():
    with client_factory() as c:
        base = {
            "messages": [{"role": "user", "content": "내일 오전 9시 회의 일정 등록해줘"}],
            "timezone": "Asia/Seoul",
        }
        first = c.post("/api/chat", json={**base, "calendar_turn_id": "test-turn-1"})
        retry = c.post("/api/chat", json={**base, "calendar_turn_id": "test-turn-1"})
        distinct = c.post("/api/chat", json={**base, "calendar_turn_id": "test-turn-2"})
        assert first.status_code == 200, first.text
        assert retry.status_code == 200, retry.text
        assert distinct.status_code == 200, distinct.text
        saved = asyncio.run(_appointments(c.app))
        assert len(saved) == 2, len(saved)
