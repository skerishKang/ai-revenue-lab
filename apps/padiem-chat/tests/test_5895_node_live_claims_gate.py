"""#5895 — what the server counts as a live claim on one PC.

#6106 clears a console line the agent holds for nothing. The connector's own active
map covers only the host that runs it, and during a failover handover (#5462) the
partner can hold a claim on the same PC: the agent answers that host's `runcommand`
with "already busy" and drops it, so the silence the first host sees belongs to a
real command that is not its own. Clearing it would cut a job short, which standard
rule 1 forbids, so the sweep asks this read first.

These tests run the real `D1HistoryStore` SQL against the committed schema, because
the whole gate is one SQL condition: the same columns the lease already writes —
`state`, `nonce_sha256`, `claimed_until`, `expires_at` — and nothing textual.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from app.history import HistoryError, ORACLE_MESH_CLAIM_LEASE_SECONDS
from test_4139_mesh_original import _dispatch_kwargs, fixture

STALE = "2000-01-01T00:00:00.000Z"
NODE = "node-com1-aaaa@bbbb"
OTHER_NODE = "node-com2-cccc@dddd"


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _staged(store, run_id: str, **overrides) -> str:
    """One pending dispatch of its own run, exactly as the lane stages it."""

    asyncio.run(store.record_claw_run(
        user_id="usr_owner_4139", run_id=run_id, channel="web", action="txt_read",
        title="Claw: live claims", status="pending",
        conversation_id="chat_" + "c" * 32, workspace_id="ws-1",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id=run_id, node_ref=NODE, **overrides)
    ))
    return row["dispatch_id"]


def _claim(store, dispatch_id: str, label: str) -> None:
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce(label),
    )) is True


def _asked(store, node: str = NODE, except_id: str = "") -> int:
    return asyncio.run(store.oracle_mesh_node_live_claims(
        node_ref=node, except_dispatch_id=except_id,
    ))


def test_an_idle_pc_answers_zero_and_a_queued_task_is_not_a_claim(tmp_path):
    """Pending is not busy.

    A dispatch the lane has not handed out yet names no holder, so it cannot be
    evidence that somebody's command is running on that machine right now.
    """
    store, _bucket = fixture(tmp_path)
    assert _asked(store) == 0
    queued = _staged(store, "run-live-queued")
    assert _asked(store) == 0, queued
    _claim(store, queued, "poll-a")
    assert _asked(store) == 1


def test_the_asking_executors_own_claim_is_the_one_claim_it_may_exclude(tmp_path):
    """Without this the gate could never open: the asker's claim is always live.

    The executor renews its own lease every 20 s while a command runs, so a read
    that counted it would answer "busy" for the whole wait and no wedged line could
    ever be cleared. Excluding exactly one id — the one the asker already holds —
    is what leaves "somebody else is working here" as the only true answer.
    """
    store, _bucket = fixture(tmp_path)
    mine = _staged(store, "run-live-mine")
    theirs = _staged(store, "run-live-theirs")
    _claim(store, mine, "poll-mine")
    _claim(store, theirs, "poll-theirs")

    assert _asked(store) == 2
    assert _asked(store, except_id=mine) == 1, "the partner's claim still counts"
    assert _asked(store, except_id=theirs) == 1
    assert _asked(store, except_id="dsp_never_heard_of_it") == 2

    _claim_only = _staged(store, "run-live-alone")
    _claim(store, _claim_only, "poll-alone")
    # Three claims on one PC; excluding any one of them leaves the other two.
    assert _asked(store) == 3
    assert _asked(store, except_id=_claim_only) == 2, "mine and theirs, both live"


def test_a_lease_that_ran_out_stops_being_a_claim(tmp_path):
    """An expired `claimed_until` is the lane's own sign that the holder is gone.

    A dead executor stops renewing, the lease runs out and the work is handed to
    somebody else. From that instant the row must not keep blocking a sweep, or the
    PC this memo is about would stay wedged forever by a host that no longer exists.
    """
    store, _bucket = fixture(tmp_path)
    dead = _staged(store, "run-live-dead")
    _claim(store, dead, "poll-dead")
    assert _asked(store) == 1
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET claimed_until=? WHERE dispatch_id=?",
        STALE, dead,
    ))
    assert _asked(store) == 0


def test_a_claim_on_another_pc_does_not_hold_this_one(tmp_path):
    store, _bucket = fixture(tmp_path)
    here = _staged(store, "run-live-here")
    _claim(store, here, "poll-here")
    assert _asked(store, node=OTHER_NODE) == 0
    assert _asked(store, node=NODE) == 1


def test_a_finished_dispatch_is_no_longer_work_on_the_pc(tmp_path):
    """`received` means the result was accepted: that console is free."""

    store, _bucket = fixture(tmp_path)
    done = _staged(store, "run-live-done")
    _claim(store, done, "poll-done")
    assert _asked(store) == 1
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET state=? WHERE dispatch_id=?", "received", done,
    ))
    assert _asked(store) == 0


def test_a_dispatch_past_its_own_life_is_not_counted(tmp_path):
    store, _bucket = fixture(tmp_path)
    doomed = _staged(store, "run-live-doomed")
    _claim(store, doomed, "poll-doomed")
    assert _asked(store) == 1
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET expires_at=? WHERE dispatch_id=?",
        STALE, doomed,
    ))
    assert _asked(store) == 0


def test_the_read_names_only_a_pc_and_refuses_anything_else(tmp_path):
    """A node reference is the whole address, and an unusable one is refused.

    Nothing here can be pointed at another account's work: the caller names a PC it
    is already standing in front of, and the channel proof in front of the route is
    the deployment secret.
    """
    store, _bucket = fixture(tmp_path)
    for bad in (None, "", "   " * 200, 12, {"node": NODE}):
        with pytest.raises(HistoryError):
            asyncio.run(store.oracle_mesh_node_live_claims(node_ref=bad))
    with pytest.raises(HistoryError):
        asyncio.run(store.oracle_mesh_node_live_claims(
            node_ref=NODE, except_dispatch_id={"not": "text"},
        ))


def test_the_window_the_count_covers_is_the_lease_window(tmp_path):
    """The condition is the lease, so a claim counted here is one being renewed.

    A row the poll is allowed to hand out again is not held by anyone: the same
    comparison the yield uses (`claimed_until` ahead of now) is the one here, and a
    drift between the two would either block every sweep or let one through while a
    partner is still working.
    """
    store, _bucket = fixture(tmp_path)
    live = _staged(store, "run-live-window")
    _claim(store, live, "poll-window")
    row = asyncio.run(store._first(
        "SELECT claimed_until, state, nonce_sha256 FROM oracle_mesh_dispatch "
        "WHERE dispatch_id=?", live,
    ))
    leased = datetime.fromisoformat(row["claimed_until"].replace("Z", "+00:00"))
    moment = datetime.now(timezone.utc)
    assert moment < leased <= moment + timedelta(
        seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS + 5,
    )
    assert row["state"] == "pending" and row["nonce_sha256"]
    assert _asked(store) == 1
    assert asyncio.run(store.renew_oracle_mesh_claim(
        dispatch_id=live, nonce_sha256=_nonce("poll-window"),
    )) is not None
    assert _asked(store) == 1, "a renewal keeps it one claim, not two"
