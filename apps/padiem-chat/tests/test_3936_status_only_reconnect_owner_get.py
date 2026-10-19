"""#3936: a Claw stream disconnect/reload recovers via owner GETs, not another model POST.

This is a provider-free, authenticated Starlette route test using saved run rows.
It does NOT claim a physical disconnected Production run was reproduced.
The run-history read must preserve the existing terminal/pause truth across
separate browser clients and reject account-switch/caller-header authority.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from test_b54_claw_session_projection import (
    OTHER_USER_ID,
    OWNED_CONVERSATION_ID,
    SIGNED_IN_USER_ID,
    _SessionHistoryStore,
    _google_settings,
    _run_row,
)


ORIGIN = "https://chat.example.test"
HISTORY_URL = "/api/claw/runs?limit=10"
OWNER_RUN = "run_" + "a" * 24
FOREIGN_RUN = "run_" + "b" * 24


def _setup():
    rows = {
        OWNER_RUN: _run_row(
            run_id=OWNER_RUN,
            user_id=SIGNED_IN_USER_ID,
            status="completed",
            result_summary="bounded previously saved answer",
            conversation_id=OWNED_CONVERSATION_ID,
        ),
        FOREIGN_RUN: _run_row(
            run_id=FOREIGN_RUN,
            user_id=OTHER_USER_ID,
            status="waiting_approval",
            result_summary=None,
            conversation_id=None,
        ),
    }
    store = _SessionHistoryStore(rows=rows)
    adapter = MagicMock()
    adapter.execute = AsyncMock(side_effect=AssertionError("GET must never invoke P01"))
    settings = _google_settings()
    app = create_app(settings=settings, history_store=store, claw_p01_adapter=adapter)
    # This regression is scoped to Claw model history, not Local Runner
    # projection/reconciliation; no out-of-band result writes are necessary.
    app.state.local_task_result_source = None
    return app, settings, store, adapter


def _login(client, settings, user_id):
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, user_id),
        domain="chat.example.test",
        path="/",
    )


def test_saved_completed_run_reconnect_is_get_only_across_browser_reload():
    app, settings, store, adapter = _setup()
    results = []
    # Two fresh browser clients simulate returning after losing the old
    # streaming connection. Only GETs are issued; no replay/POST is possible.
    for _ in range(2):
        with TestClient(app, base_url=ORIGIN) as client:
            _login(client, settings, SIGNED_IN_USER_ID)
            response = client.get(HISTORY_URL)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")
            assert "no-store" in response.headers["cache-control"]
            results.append(response.json()["runs"])

    assert results[0] == results[1]
    assert len(results[0]) == 1
    saved = results[0][0]
    assert saved["run_id"] == OWNER_RUN
    assert saved["status"] == "completed"
    assert saved["session"] == {"conversation_id": OWNED_CONVERSATION_ID}
    assert saved["result_summary"] == "bounded previously saved answer"
    assert "user_id" not in saved
    assert store.record_calls == []
    adapter.execute.assert_not_awaited()


def test_get_only_recovery_rechecks_owner_after_account_switch_and_signout():
    app, settings, store, adapter = _setup()
    with TestClient(app, base_url=ORIGIN) as client:
        _login(client, settings, SIGNED_IN_USER_ID)
        first = client.get(
            HISTORY_URL,
            headers={"x-padiem-user-id": OTHER_USER_ID, "x-padiem-tenant": "forged"},
        )
        assert first.status_code == 200
        assert [r["run_id"] for r in first.json()["runs"]] == [OWNER_RUN]
        assert FOREIGN_RUN not in first.text

        # A new signed session changes the authoritative owner, regardless
        # of any browser-held run identifier from the previous account.
        _login(client, settings, OTHER_USER_ID)
        switched = client.get(
            HISTORY_URL,
            headers={"x-padiem-user-id": SIGNED_IN_USER_ID},
        )
        assert switched.status_code == 200
        assert [r["run_id"] for r in switched.json()["runs"]] == [FOREIGN_RUN]
        assert switched.json()["runs"][0]["status"] == "waiting_approval"
        assert OWNER_RUN not in switched.text
        assert OWNED_CONVERSATION_ID not in switched.text

        client.cookies.clear()
        signed_out = client.get(HISTORY_URL)
        assert signed_out.status_code == 401
        assert OWNER_RUN not in signed_out.text
        assert FOREIGN_RUN not in signed_out.text

    assert store.record_calls == []
    adapter.execute.assert_not_awaited()
