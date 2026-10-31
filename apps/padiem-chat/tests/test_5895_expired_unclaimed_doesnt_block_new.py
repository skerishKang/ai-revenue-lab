"""#5895 — a stale unclaimed dispatch never blocks a new one, and an owner's stop clears it.

A PC that is off never claims: the row staged for the last command stays
``pending`` with no nonce until its own ``expires_at`` has passed. That row must
not be the queue's head forever. Once the TTL has run out, the next command is
the oldest claimable work and goes through whole — claim, lease, nonce proof —
while the dead row sits untouched for the poll route's own reconciliation. The
owner's stop is the immediate way out: it clears the unclaimed row from the
yield the same instant, without waiting for the TTL, and the user's screen keeps
showing the wait (``resumeUnfinishedPcRun`` → ``onPending: showWait``) while the
device list says ``오프라인`` for the PC that is off.

These tests run the real ``D1HistoryStore`` SQL against the real committed
schema (the 047→074 replay), because the contract is the shared WHERE clause of
the yield and the claim, plus one conditional cancel UPDATE. Nothing executes on
a PC here.

Owner decision 2026-10-28 (①) is pinned too: the dispatch TTL no longer expires
a result — a submission that still names its claim nonce lands even after
``expires_at``, and a foreign nonce is still refused.
"""
from __future__ import annotations

import asyncio
import hashlib

from test_4139_mesh_original import CONVERSATION, OWNER, _dispatch_kwargs, fixture

EXPIRED = "2000-01-01T00:00:00.000Z"


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _staged(store, run_id: str) -> str:
    """One pending dispatch of its own run, exactly as the lane stages it."""

    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=run_id, channel="web", action="txt_read",
        title="Claw: stale row", status="pending", conversation_id=CONVERSATION,
        workspace_id="ws-1",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id=run_id)
    ))
    return row["dispatch_id"]


def _backdate(store, dispatch_id: str) -> None:
    """Make this row deterministically the oldest, whatever the clock did."""

    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET created_at=? WHERE dispatch_id=?",
        EXPIRED, dispatch_id,
    ))


def _expire(store, dispatch_id: str, with_lease: bool = False) -> None:
    """Age a row out of its TTL.

    ``with_lease`` also runs the claim's lease out — the shape of a row whose
    executor kept renewing (#5997) and then died. Without it the row keeps the
    never-claimed shape: no nonce, no lease (the PC was off and nobody polled).
    """

    if with_lease:
        asyncio.run(store._run(
            "UPDATE oracle_mesh_dispatch SET expires_at=?, claimed_until=? "
            "WHERE dispatch_id=?",
            EXPIRED, EXPIRED, dispatch_id,
        ))
    else:
        asyncio.run(store._run(
            "UPDATE oracle_mesh_dispatch SET expires_at=? WHERE dispatch_id=?",
            EXPIRED, dispatch_id,
        ))


def _row(store, dispatch_id: str, columns: str = "state, nonce_sha256, termination") -> dict:
    return asyncio.run(store._first(
        f"SELECT {columns} FROM oracle_mesh_dispatch WHERE dispatch_id=?", dispatch_id,
    ))


def test_an_expired_unclaimed_row_does_not_block_a_new_dispatch(tmp_path):
    store, _bucket = fixture(tmp_path)
    old = _staged(store, "run-old-blocker")
    new = _staged(store, "run-new-immediate")

    # While the off-PC's row is inside its TTL it is the head of the queue:
    # the yield hands out one row at a time, oldest first.
    _backdate(store, old)
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == old

    # The TTL runs out with no claim ever taken. The row stops being work the
    # lane may hand out, and the next command becomes the oldest claimable.
    _expire(store, old)
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == new

    nonce = _nonce("poll-new")
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=new, nonce_sha256=nonce,
    )) is True
    accepted = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=new, nonce="poll-new",
    ))
    assert accepted is not None and accepted["claim"] == "first"

    # The new command went through whole; nothing is left to hand out.
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    # The stale row sits untouched — still pending, never claimed, never
    # handed out a second time — until its own reconciliation clears it.
    assert _row(store, old) == {
        "state": "pending", "nonce_sha256": None, "termination": None,
    }


def test_the_owner_cancel_clears_stale_work_from_the_queue(tmp_path):
    store, _bucket = fixture(tmp_path)
    old = _staged(store, "run-cancel-me")
    new = _staged(store, "run-after-cancel")
    _backdate(store, old)

    # The stale row is the head of the queue: the user's screen shows this run
    # waiting while nobody can claim it.
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == old

    # The owner stops that run. One conditional update clears the unclaimed
    # row from the yield the same instant — no TTL wait.
    assert asyncio.run(store.cancel_oracle_mesh_dispatches_for_run(
        user_id=OWNER, run_id="run-cancel-me",
    )) == 1
    assert _row(store, old) == {
        "state": "failed", "nonce_sha256": None, "termination": "cancelled",
    }

    # The next command is handed out immediately, and it goes through whole.
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == new
    nonce = _nonce("poll-after")
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=new, nonce_sha256=nonce,
    )) is True
    accepted = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=new, nonce="poll-after",
    ))
    assert accepted is not None and accepted["claim"] == "first"
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None

    # A second stop of the same run finds nothing: the clear is not repeated.
    assert asyncio.run(store.cancel_oracle_mesh_dispatches_for_run(
        user_id=OWNER, run_id="run-cancel-me",
    )) == 0


def test_a_result_landing_after_the_dispatch_ttl_is_still_accepted(tmp_path):
    """① — the TTL does not expire a result; the nonce still gates it."""

    store, _bucket = fixture(tmp_path)
    late = _staged(store, "run-late-result")
    other = _staged(store, "run-foreign-nonce")

    # Two executors hold their claims; then both rows run past their TTL and
    # their lease — a run that kept renewing (#5997) and finished late.
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=late, nonce_sha256=_nonce("poll-late"),
    )) is True
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=other, nonce_sha256=_nonce("poll-other"),
    )) is True
    _expire(store, late, with_lease=True)
    _expire(store, other, with_lease=True)

    # The late submission still names its own nonce: accepted after the TTL.
    accepted = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=late, nonce="poll-late",
    ))
    assert accepted is not None and accepted["claim"] == "first"
    assert accepted["state"] == "received"

    # The nonce gate is untouched: a foreign nonce is refused even though the
    # TTL is gone, while the row's own holder still lands its result.
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=other, nonce="poll-late",
    )) is None
    accepted_other = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=other, nonce="poll-other",
    ))
    assert accepted_other is not None and accepted_other["claim"] == "first"
