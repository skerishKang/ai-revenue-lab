"""#7562 — a run-out lease never hands out again what may already have run.

A lease that ran out proves only that no renewal arrived. The executor may have
restarted mid-command, or its renewal may have been held up: the PC may already
have done the work. Handing the row out again ran it a second time, the first
result was refused under the rotated nonce, and the conversation kept only the
second answer (for a delete: "대상 없음").

These tests drive the real ``D1HistoryStore`` SQL against the committed schema:

* a ``command`` (shell, and every file write/move/delete/edit, which travel as
  commands) and a ``desktop`` input are settled as ``failed`` /
  ``termination='no_reply'`` instead of being handed out again;
* a ``read`` is still re-delivered under a rotated nonce, exactly as before;
* a row the owner stopped is never handed out again, whatever its kind;
* the settlement never touches a claim that is still alive.
"""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from test_4139_mesh_original import _dispatch_kwargs, fixture

EXPIRED = "2000-01-01T00:00:00.000Z"
LATER = "2099-01-01T00:00:00.000Z"
OWNER = "usr_owner_4139"

SIDE_EFFECTS = {
    "command": {"kind": "command", "command_text": "Remove-Item -LiteralPath 'C:/a.txt'"},
    "desktop": {"kind": "desktop", "command_text": "desktop:type\nhello"},
}
READ = {"kind": "read", "command_text": None}


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _staged(store, run_id: str, **overrides) -> str:
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=run_id, channel="web", action="txt_read",
        title="Claw: lease", status="pending", conversation_id="chat_" + "c" * 32,
        workspace_id="ws-1",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id=run_id, **overrides)
    ))
    return row["dispatch_id"]


def _claimed(store, run_id: str, label: str, **overrides) -> str:
    dispatch_id = _staged(store, run_id, **overrides)
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == dispatch_id
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce(label),
    )) is True
    return dispatch_id


def _lease(store, dispatch_id: str, instant: str) -> None:
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET claimed_until=? WHERE dispatch_id=?",
        instant, dispatch_id,
    ))


def _row(store, dispatch_id: str) -> dict:
    return asyncio.run(store._first(
        "SELECT state, termination, nonce_sha256 FROM oracle_mesh_dispatch "
        "WHERE dispatch_id=?", dispatch_id,
    ))


@pytest.mark.parametrize("name", sorted(SIDE_EFFECTS))
def test_a_row_that_changes_the_pc_is_not_handed_out_twice(tmp_path, name):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _claimed(store, "run-7562-" + name, "first", **SIDE_EFFECTS[name])

    # The executor took it and then went silent: restarted mid-command, or its
    # renewal was held up past the lease.
    _lease(store, dispatch_id, EXPIRED)

    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("second"),
    )) is False
    # Ended as "the PC sent no result" — never a silent second run, never a
    # row that waits for a delivery that cannot come.
    assert _row(store, dispatch_id) == {
        "state": "failed", "termination": "no_reply", "nonce_sha256": _nonce("first"),
    }
    # A settled claim cannot be renewed back to life, and a late submission
    # under the first nonce does not attach to it.
    assert asyncio.run(store.renew_oracle_mesh_claim(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("first"),
    )) is None
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="first",
    )) is None


def test_a_read_is_still_handed_out_again_under_a_rotated_nonce(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _claimed(store, "run-7562-read", "first", **READ)
    _lease(store, dispatch_id, EXPIRED)

    again = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert again is not None and again["dispatch_id"] == dispatch_id
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("second"),
    )) is True
    assert _row(store, dispatch_id) == {
        "state": "pending", "termination": None, "nonce_sha256": _nonce("second"),
    }


@pytest.mark.parametrize("overrides", [READ, SIDE_EFFECTS["command"]],
                         ids=["read", "command"])
def test_a_row_the_owner_stopped_is_never_handed_out_again(tmp_path, overrides):
    store, _bucket = fixture(tmp_path)
    run_id = "run-7562-stop-" + overrides["kind"]
    dispatch_id = _claimed(store, run_id, "first", **overrides)
    assert asyncio.run(store.cancel_oracle_mesh_dispatches_for_run(
        user_id=OWNER, run_id=run_id,
    )) == 1
    # While the executor still holds the lease it reads the stop and lands its
    # own result: the row stays pending and submittable, as before.
    assert _row(store, dispatch_id)["state"] == "pending"
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None

    # The executor never came back. The stop is final; nothing is re-delivered.
    _lease(store, dispatch_id, EXPIRED)
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("second"),
    )) is False
    assert _row(store, dispatch_id) == {
        "state": "failed", "termination": "cancelled", "nonce_sha256": _nonce("first"),
    }


@pytest.mark.parametrize("name", sorted(SIDE_EFFECTS))
def test_a_live_claim_is_never_settled(tmp_path, name):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _claimed(store, "run-7562-live-" + name, "first", **SIDE_EFFECTS[name])
    # The lease is still running: the poll settles nothing and the executor's
    # result lands normally.
    _lease(store, dispatch_id, LATER)
    assert asyncio.run(store.settle_unredeliverable_oracle_mesh_claims()) == 0
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    accepted = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="first",
    ))
    assert accepted is not None and accepted["claim"] == "first"


def test_settlement_reaches_only_the_rows_that_ran_out(tmp_path):
    store, _bucket = fixture(tmp_path)
    ran_out = _claimed(store, "run-7562-a", "a", **SIDE_EFFECTS["command"])
    live = _claimed(store, "run-7562-b", "b", **SIDE_EFFECTS["command"])
    queued = _staged(store, "run-7562-c", **SIDE_EFFECTS["command"])
    _lease(store, ran_out, EXPIRED)

    assert asyncio.run(store.settle_unredeliverable_oracle_mesh_claims()) == 1
    assert _row(store, ran_out)["state"] == "failed"
    assert _row(store, live)["state"] == "pending"
    # Never-claimed work is untouched and is the next thing handed out.
    assert _row(store, queued) == {"state": "pending", "termination": None, "nonce_sha256": None}
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch())["dispatch_id"] == queued
