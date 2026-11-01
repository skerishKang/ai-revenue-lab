"""#6460 step 3 — a plain-language PC task reaches the Engine loop, or stops first.

The loop itself is the Engine's (capture → choose one action → execute →
capture again). What this file proves is the Chat decision in front of it: the
task is staged as ``desktop_task`` and dispatched with ``desktop_capture``, and
a task that names one of the four exception families is asked about once and
never starts.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from starlette.testclient import TestClient

from app import b54_canonical_session, claw_memory_routes
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT
from test_b54_claw_general_p01_routing import (
    GENERAL_ROUTE_PATH,
    _make_outcome,
    _settings,
)
from test_claw_local_task_result_projection import _open_database

WORKSPACE = "tenant.6460.loop"
OWNER_SUBJECT = "owner-6460-loop"


class _LazyHistory:
    def __init__(self, path):
        self._path = path
        self._store: D1HistoryStore | None = None

    def _resolve(self) -> D1HistoryStore:
        if self._store is None:
            self._store = D1HistoryStore(
                _open_database(self._path, migrate=False)
            )
        return self._store

    def __getattr__(self, name):
        return getattr(self._resolve(), name)


class Adapter:
    subject_identity_lane = True

    def __init__(self, history, owner):
        self.calls = []
        self._history = history
        self._owner = owner

    async def execute(self, run, **kwargs):
        row = await self._history.get_claw_run(self._owner, run.run_id)
        self.calls.append({"run_id": run.run_id, "kwargs": kwargs,
                           "row": dict(row or {})})
        return _make_outcome(answer="메모장에 날짜를 적고 저장했습니다.")


def _app(tmp_path, monkeypatch):
    path = tmp_path / "chat.sqlite3"
    setup = D1HistoryStore(_open_database(path))
    owner = asyncio.run(setup.upsert_google_user(
        OWNER_SUBJECT, "loop-owner@example.test", "owner", "",
    )).id
    setup.db.close()

    async def canonical_session(request):
        return SimpleNamespace(auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id="sub_" + "a" * 32),
            tenant_id=WORKSPACE,
        ))

    monkeypatch.setattr(
        b54_canonical_session, "resolve_current_b54_canonical_session",
        canonical_session,
    )

    async def workspace(request, user_id):
        assert user_id == owner
        return WORKSPACE

    monkeypatch.setattr(
        claw_memory_routes, "_resolve_memory_workspace", workspace,
    )

    history = _LazyHistory(path)
    adapter = Adapter(history, owner)
    settings = _settings()
    app = create_app(
        settings=settings, history_store=history, claw_p01_adapter=adapter,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(settings, owner),
        domain="chat.example.test", path="/",
    )
    return path, owner, adapter, client


def test_a_plain_language_task_runs_the_engine_loop(tmp_path, monkeypatch):
    path, owner, adapter, client = _app(tmp_path, monkeypatch)
    with client:
        response = client.post(GENERAL_ROUTE_PATH, json={
            "messages": [{
                "role": "user",
                "content": "메모장 열어서 오늘 날짜 적고 저장해 줘",
            }],
            "tier": "plus",
        })
    assert response.status_code == 200, response.text
    assert len(adapter.calls) == 1
    call = adapter.calls[0]
    assert call["kwargs"]["desktop_capture"] is True
    assert call["row"]["status"] == "pending"
    assert call["row"]["action"] == "desktop_task"
    verify = D1HistoryStore(_open_database(path, migrate=False))
    try:
        row = asyncio.run(verify.get_claw_run(owner, call["run_id"]))
        conversation = asyncio.run(verify.get_conversation(
            owner, call["row"]["conversation_id"],
            product_scope=PRODUCT_SCOPE_CHAT,
        ))
    finally:
        verify.db.close()
    assert row["status"] == "completed"
    assert [message["role"] for message in conversation["messages"]] == [
        "user", "assistant",
    ]


def test_an_exception_task_is_asked_once_and_starts_nothing(tmp_path, monkeypatch):
    path, owner, adapter, client = _app(tmp_path, monkeypatch)
    with client:
        response = client.post(GENERAL_ROUTE_PATH, json={
            "messages": [{
                "role": "user",
                "content": "메모장 열어서 오늘 날짜 적고 삭제해 줘",
            }],
            "tier": "plus",
        })
    assert response.status_code == 200, response.text
    assert "바로 실행하지 않았습니다" in response.text
    assert adapter.calls == []
    verify = D1HistoryStore(_open_database(path, migrate=False))
    try:
        runs = asyncio.run(verify.list_recent_claw_runs(owner))
    finally:
        verify.db.close()
    assert runs == []
