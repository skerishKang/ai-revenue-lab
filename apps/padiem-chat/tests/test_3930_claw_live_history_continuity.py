"""#3930/#4072: live Claw SSE must preserve the same owner history as completed mode.

Uses the real Starlette route, synthetic adapter events, synthetic signed owner
and in-memory history only. No model, Engine, Cloudflare or D1 mutation.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_b54_claw_general_p01_routing as base
from test_3930_b54_live_sse_relay import HEADERS, SUBJECT, _streaming_adapter
from test_4072_claw_general_history_projection import _ClawThreadStore, owner_client


def _live(store, *, status="completed", payload=None):
    adapter = _streaming_adapter(status=status)
    canonical_session = SimpleNamespace(auth_session=SimpleNamespace(
        subject=SimpleNamespace(subject_id=SUBJECT),
        tenant_id="tenant_claw_live_history",
    ))
    with patch(
        "app.b54_canonical_session.resolve_current_b54_canonical_session",
        new=AsyncMock(return_value=canonical_session),
    ):
        with owner_client(store, adapter) as client:
            client.app.state.claw_live_sse_enabled = True
            result = client.post(
                base.GENERAL_ROUTE_PATH, json=payload or base._payload(),
                headers=HEADERS,
            )
    adapter.execute.assert_awaited_once()
    return result


def _done_payload(response):
    frames = response.text.split("\n\n")
    done = [frame for frame in frames if frame.startswith("event: done\n")]
    assert len(done) == 1, response.text
    return json.loads(done[0].split("data: ", 1)[1])


def test_live_sse_completed_run_is_saved_and_reopened_with_server_thread():
    store = _ClawThreadStore()
    result = _live(store)
    assert result.status_code == 200
    assert result.text.count("event: done") == 1
    assert result.text.count('"kind":"run_completed"') == 1
    assert _done_payload(result) == {
        "done": True, "conversation_id": store.THREAD_ID,
    }
    assert len(store.saved[store.THREAD_ID]["messages"]) == 2
    assert store.saved[store.THREAD_ID]["messages"][0]["role"] == "user"
    assert store.saved[store.THREAD_ID]["messages"][1]["role"] == "assistant"
    assert len(store.calls) == 1
    assert store.calls[0]["status"] == "completed"
    assert store.calls[0]["conversation_id"] == store.THREAD_ID
    assert store.calls[0]["workspace_id"] == "tenant_claw_live_history"


def test_live_sse_followup_uses_same_owner_thread_not_a_forged_browser_thread():
    store = _ClawThreadStore()
    store.saved[store.THREAD_ID] = {
        "id": store.THREAD_ID, "project_id": None,
        "messages": [
            {"role": "user", "content": "previous-owner-only-context"},
            {"role": "assistant", "content": "previous-verified-answer"},
        ],
    }
    response = _live(store, payload=base._payload(
        conversation_id=store.THREAD_ID,
        messages=[{"role": "user", "content": "second-user-request"}],
    ))
    assert response.status_code == 200
    assert _done_payload(response)["conversation_id"] == store.THREAD_ID
    assert len(store.saved[store.THREAD_ID]["messages"]) == 4
    assert store.saved[store.THREAD_ID]["messages"][-2]["content"] == "second-user-request"
    assert store.calls[0]["conversation_id"] == store.THREAD_ID


def test_live_history_write_failure_does_not_erase_completed_answer_or_mint_thread():
    store = _ClawThreadStore(fail_write=True)
    response = _live(store)
    assert response.status_code == 200
    assert "event: delta" in response.text
    assert _done_payload(response) == {"done": True}
    assert len(store.calls) == 1
    assert store.calls[0]["conversation_id"] is None


def test_live_approval_pause_never_persists_a_fake_completed_run():
    store = _ClawThreadStore()
    response = _live(store, status="waiting_approval")
    assert response.status_code == 200
    assert "event: done" not in response.text
    assert "claw_general_approval_required" in response.text
    assert store.calls == []
    assert store.saved == {}
