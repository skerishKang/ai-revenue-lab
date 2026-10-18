"""#5015 live SSE must settle a staged run on every answer-less terminal.

Reproduction of the production shape seen on 2026-10-18: the turn
"내 PC 드라이브 목록 알려줘" is resolved by the real
``_requested_natural_pc_query`` resolver to a ``Get-PSDrive`` query, so the
run is staged as ``pending`` before dispatch. The P01/Engine stream then
ended without a verified answer, and nothing ever moved the run out of
``pending`` — no answer, no terminal state, forever.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

from app.claw_general_routes import _requested_natural_pc_query
from test_3930_b54_live_sse_relay import _streaming_adapter
from test_b54_claw_general_p01_routing import _client, _payload

PC_DRIVE_TEXT = "내 PC 드라이브 목록 알려줘"


def test_real_resolver_sends_this_turn_to_the_pc_drive_engine_lane():
    """Guard: the fixture really is the pc_drive_query path, not ordinary chat."""
    matched, command = _requested_natural_pc_query(PC_DRIVE_TEXT)
    assert matched is True
    assert "Get-PSDrive" in command


def _tracking_store():
    store = MagicMock()
    store.rows = {}
    store.calls = []

    async def record_txt_pending_run(*, user_id, run_id, workspace_id,
                                     user_text, conversation_id):
        store.rows[run_id] = {
            "run_id": run_id, "user_id": user_id, "status": "pending",
            "conversation_id": conversation_id, "workspace_id": workspace_id,
        }
        # Production staged a run bound to a real owner conversation, e.g.
        # chat_71d3e8e4af84402ba8379b68ca79d1f5 for the 2026-10-18 turn.
        return conversation_id or ("chat_" + "b" * 32)

    async def update_claw_run_status(user_id, run_id, status, result_summary=None):
        store.calls.append((user_id, run_id, status))
        if run_id in store.rows:
            store.rows[run_id]["status"] = status
            return True
        return False

    store.record_txt_pending_run = record_txt_pending_run
    store.update_claw_run_status = update_claw_run_status
    return store


OWNER = "usr_owner_1"


def _drive_call(adapter, store, *, enabled=True):
    payload = _payload(messages=[{"role": "user", "content": PC_DRIVE_TEXT}])
    with patch("app.claw_general_routes.auth_ready", lambda r: True), \
         patch("app.claw_general_routes.current_user_id", lambda r: OWNER), \
         patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new=AsyncMock(return_value=SimpleNamespace(
                   auth_session=SimpleNamespace(
                       subject=SimpleNamespace(subject_id="sub_" + "9" * 32))))):
        # Drive grounding is an external service and is not what is under test
        # here; the lane under test is staging -> Engine -> signed callback.
        with patch("app.claw_general_routes.drive_general_grounding",
                   new=AsyncMock(return_value=("drive ground", ()))):
            with _client(adapter) as client:
                client.app.state.history_store = store
                client.app.state.claw_live_sse_enabled = enabled
                return client.post(
                    "/api/claw/general", json=payload,
                    headers={"X-Padiem-Claw-Live": "p01-events-v1"},
                )


def test_verified_completion_still_records_and_does_not_double_settle():
    store = _tracking_store()
    adapter = _streaming_adapter(status="completed")
    response = _drive_call(adapter, store)
    assert response.status_code == 200
    assert "event: done" in response.text
    assert [r["status"] for r in store.rows.values()] == ["pending"], (
        "a verified answer is owned by on_completed, not by the settle hook"
    )


def test_engine_failure_settles_the_staged_run_instead_of_stranding_it():
    """The regression: this is what left run_b0e18336... pending forever."""
    store = _tracking_store()
    adapter = _streaming_adapter(status="failed")
    response = _drive_call(adapter, store)
    assert response.status_code == 200, response.text
    assert "event: error" in response.text
    assert store.rows, "the pc_drive turn must have staged a run"
    assert [r["status"] for r in store.rows.values()] == ["failed"], (
        "a staged run with no verified answer must not stay pending; "
        f"update_claw_run_status calls={store.calls}"
    )


def test_approval_pause_settles_the_staged_run():
    store = _tracking_store()
    adapter = _streaming_adapter(status="waiting_approval")
    response = _drive_call(adapter, store)
    assert "event: error" in response.text
    assert [r["status"] for r in store.rows.values()] == ["failed"]


def test_settle_hook_failure_never_breaks_the_user_facing_stream():
    """History settling is best-effort; the stream must still be readable."""
    store = _tracking_store()

    async def explode(user_id, run_id, status, result_summary=None):
        raise RuntimeError("d1 unavailable")
    store.update_claw_run_status = explode

    adapter = _streaming_adapter(status="failed")
    response = _drive_call(adapter, store)
    assert response.status_code == 200
    assert "event: error" in response.text