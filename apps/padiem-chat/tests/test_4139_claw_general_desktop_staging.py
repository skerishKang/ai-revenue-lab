"""#4139 model-driven desktop runs stage an owner run before Engine dispatch.

The signed internal desktop route resolves the target conversation, workspace
and owner session from the run row, so a run that only materializes after the
answer exists can never reach the PC. This drives the real Starlette route over
the real D1 history store and proves:

- the run row is ``pending`` with a conversation at the moment Engine runs;
- the verified answer lands once, in that same conversation, without
  re-inserting the owner turn.
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

WORKSPACE = "tenant.4139.staging"
OWNER_SUBJECT = "owner-4139-staging"


class _LazyHistory:
    """Open the real D1 store on the app's own event-loop thread."""

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


def test_general_desktop_request_stages_the_run_before_engine_dispatch(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "chat.sqlite3"
    setup = D1HistoryStore(_open_database(path))
    owner = asyncio.run(setup.upsert_google_user(
        OWNER_SUBJECT, "claw-owner@example.test", "owner", "",
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
    dispatched: dict = {}

    class Adapter:
        subject_identity_lane = True

        async def execute(self, run, **kwargs):
            row = await history.get_claw_run(owner, run.run_id)
            dispatched.update({
                "run_id": run.run_id,
                "kwargs": kwargs,
                "status_at_dispatch": (row or {}).get("status"),
                "conversation_at_dispatch": (row or {}).get("conversation_id"),
                "workspace_at_dispatch": (row or {}).get("workspace_id"),
            })
            if not (row and row.get("conversation_id")):
                raise RuntimeError(
                    "signed desktop route would refuse this run before capture"
                )
            return _make_outcome(
                answer="메모장에 PADIEM-CLAW-4139-GUI-E2E-OK 를 입력했습니다."
            )

    settings = _settings()
    app = create_app(
        settings=settings, history_store=history, claw_p01_adapter=Adapter(),
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(settings, owner),
        domain="chat.example.test", path="/",
    )
    with client:
        response = client.post(GENERAL_ROUTE_PATH, json={
            "messages": [{
                "role": "user",
                "content": "내 PC 화면을 캡처해서 확인해 주세요.",
            }],
            "tier": "plus",
        })

    assert response.status_code == 200, response.text
    assert dispatched["status_at_dispatch"] == "pending"
    assert dispatched["conversation_at_dispatch"]
    assert dispatched["workspace_at_dispatch"] == WORKSPACE
    assert dispatched["kwargs"]["desktop_capture"] is True
    assert dispatched["kwargs"]["subject_id"].startswith("sub_")

    verify = D1HistoryStore(_open_database(path, migrate=False))
    try:
        row = asyncio.run(verify.get_claw_run(owner, dispatched["run_id"]))
        conversation = asyncio.run(verify.get_conversation(
            owner, dispatched["conversation_at_dispatch"],
            product_scope=PRODUCT_SCOPE_CHAT,
        ))
    finally:
        verify.db.close()

    assert row is not None
    assert row["status"] == "completed"
    assert row["workspace_id"] == WORKSPACE
    assert row["conversation_id"] == dispatched["conversation_at_dispatch"]
    assert [message["role"] for message in conversation["messages"]] == [
        "user", "assistant",
    ]
    assert (
        "PADIEM-CLAW-4139-GUI-E2E-OK"
        in conversation["messages"][1]["content"]
    )
    assert dispatched["conversation_at_dispatch"] in response.text
