"""#5895 — an executor claim is a lease, so a lost response is not lost work.

The yield handed out only rows whose `nonce_sha256` was NULL, and the claim wrote
that nonce before the HTTP response was produced. A claim whose response died on
the way to the executor therefore named a holder that never existed: the dispatch
was never offered again, no submission could ever match it, and the PC task sat in
the table until its own expiry.

These tests run the real `D1HistoryStore` SQL against the real committed schema
(the 047→074 replay), because the whole fix is one SQL condition. The executor is
not involved and nothing here re-executes a PC command: a re-claim re-rolls the
nonce, and the nonce comparison that already existed decides who may attach a
result.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.history import D1HistoryStore, ORACLE_MESH_CLAIM_LEASE_SECONDS
from test_4139_mesh_original import _dispatch_kwargs, fixture

EXPIRED = "2000-01-01T00:00:00.000Z"


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _staged(store, run_id: str, **overrides) -> str:
    """One pending dispatch of its own run, exactly as the lane stages it."""

    asyncio.run(store.record_claw_run(
        user_id="usr_owner_4139", run_id=run_id, channel="web", action="txt_read",
        title="Claw: lease", status="pending", conversation_id="chat_" + "c" * 32,
        workspace_id="ws-1",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id=run_id, **overrides)
    ))
    return row["dispatch_id"]


def _row(store, dispatch_id: str, columns: str = "*") -> dict:
    return asyncio.run(store._first(
        f"SELECT {columns} FROM oracle_mesh_dispatch WHERE dispatch_id=?", dispatch_id,
    ))


def _expire(store, dispatch_id: str) -> None:
    """Age the lease out. The instant itself is not the contract; the condition is."""

    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET claimed_until=? WHERE dispatch_id=?",
        EXPIRED, dispatch_id,
    ))


def test_a_claim_whose_response_was_lost_is_handed_out_again(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lease-1")

    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == dispatch_id
    first = _nonce("poll-one")
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=first,
    )) is True
    # The claim is held: while the lease runs, nobody else can be handed this work.
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None

    # The response never reached the executor. Nothing executed and nothing can
    # submit, so the only way this dispatch returns to the lane is the lease.
    _expire(store, dispatch_id)
    again = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert again is not None and again["dispatch_id"] == dispatch_id
    assert again["state"] == "pending"

    second = _nonce("poll-two")
    assert second != first
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=second,
    )) is True
    stored = _row(store, dispatch_id, "nonce_sha256, state, expires_at, claimed_until")
    assert stored["nonce_sha256"] == second
    assert stored["state"] == "pending"
    # Redelivery does not extend or shorten the dispatch's own life.
    assert stored["expires_at"] == handed["expires_at"]
    # The claim itself records the lease: one round of the named timer ahead of
    # now. A claim that wrote no lease would strand this dispatch again.
    leased = datetime.fromisoformat(stored["claimed_until"].replace("Z", "+00:00"))
    moment = datetime.now(timezone.utc)
    assert moment < leased <= moment + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS + 5)
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None


def test_exactly_one_claim_wins_one_round(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lease-2")
    winner, loser = _nonce("poll-winner"), _nonce("poll-loser")

    async def race():
        return await asyncio.gather(
            store.claim_oracle_mesh_dispatch(dispatch_id=dispatch_id, nonce_sha256=winner),
            store.claim_oracle_mesh_dispatch(dispatch_id=dispatch_id, nonce_sha256=loser),
        )

    assert sorted(asyncio.run(race())) == [False, True]
    assert _row(store, dispatch_id, "nonce_sha256")["nonce_sha256"] == winner

    # The next round is a new round: once the lease has run out, one poll wins it.
    _expire(store, dispatch_id)

    async def second_round():
        return await asyncio.gather(
            store.claim_oracle_mesh_dispatch(dispatch_id=dispatch_id, nonce_sha256=_nonce("round2-a")),
            store.claim_oracle_mesh_dispatch(dispatch_id=dispatch_id, nonce_sha256=_nonce("round2-b")),
        )

    assert sorted(asyncio.run(second_round())) == [False, True]


def test_a_submission_with_the_superseded_nonce_is_refused(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lease-3")
    stale, fresh = _nonce("poll-stale"), _nonce("poll-fresh")
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=stale,
    )) is True
    _expire(store, dispatch_id)
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=fresh,
    )) is True

    # The holder that never got its response cannot attach a result any more, and
    # the dispatch is still pending for the holder that did.
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="poll-stale",
    )) is None
    assert _row(store, dispatch_id, "state, result_sha256") == {
        "state": "pending", "result_sha256": None,
    }
    accepted = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="poll-fresh",
    ))
    assert accepted is not None and accepted["claim"] == "first"
    assert accepted["state"] == "received"
    # One result per dispatch: the superseded submission stays refused afterwards.
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="poll-stale",
    )) is None


def test_the_normal_path_is_unchanged(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lease-4")

    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == dispatch_id and handed["state"] == "pending"
    nonce = _nonce("poll-normal")
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=nonce,
    )) is True
    accepted = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="poll-normal",
    ))
    assert accepted is not None and accepted["claim"] == "first"
    assert accepted["run_id"] == "run-lease-4"
    # A dispatch that answered is no longer anybody's work.
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None


def test_a_claim_taken_before_the_lease_column_is_never_re_handed(tmp_path):
    """A mixed fleet fails closed: no lease recorded means no redelivery.

    A row claimed by a Worker revision that predates 074 has a nonce and no
    lease instant. Re-handing it could duplicate an execution that is already
    under way, so it stays exactly as the old code left it — delayed, not
    doubled.
    """

    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lease-5")
    asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("poll-legacy"),
    ))
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET claimed_until=NULL WHERE dispatch_id=?",
        dispatch_id,
    ))
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("poll-legacy-two"),
    )) is False


def test_the_lease_is_one_delivery_timer_and_not_a_workload_limit() -> None:
    """One named constant, and no new bound anywhere else on the row."""

    assert isinstance(ORACLE_MESH_CLAIM_LEASE_SECONDS, int)
    assert ORACLE_MESH_CLAIM_LEASE_SECONDS > 0

    yield_sql = inspect.getsource(D1HistoryStore.oldest_pending_oracle_mesh_dispatch)
    claim_sql = inspect.getsource(D1HistoryStore.claim_oracle_mesh_dispatch)
    # The yield and the claim decide with the SAME condition, so a round has one
    # winner by construction instead of by two documents that can drift apart.
    condition = "(nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=?))"
    assert condition in yield_sql
    assert condition in claim_sql
    # The lease is the only thing the claim writes; the deadline that ends a
    # dispatch is still the `expires_at` the poll route stamped.
    assert "SET nonce_sha256=?, claimed_until=?" in claim_sql
    assert "expires_at>?" in claim_sql and "SET expires_at" not in claim_sql
    assert claim_sql.count("ORACLE_MESH_CLAIM_LEASE_SECONDS") == 1

    migration = (
        Path(inspect.getfile(D1HistoryStore)).resolve().parents[1]
        / "migrations" / "074_oracle_mesh_dispatch_claim_lease.sql"
    ).read_text(encoding="utf-8")
    statements = [line for line in migration.splitlines() if line.strip() and not line.startswith("--")]
    assert statements == ["ALTER TABLE oracle_mesh_dispatch ADD COLUMN claimed_until TEXT;"]


def test_a_re_staged_dispatch_starts_unclaimed_again(tmp_path):
    """The reset that re-stages an expired dispatch also drops its lease."""

    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lease-6", kind="read", command_text=None)
    asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("poll-reset"),
    ))
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET expires_at=? WHERE dispatch_id=?",
        EXPIRED, dispatch_id,
    ))
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id="run-lease-6", kind="read", command_text=None)
    ))
    assert row["dispatch_id"] == dispatch_id and row["state"] == "pending"
    fresh = _row(store, dispatch_id, "nonce_sha256, claimed_until, state, expires_at")
    assert fresh["nonce_sha256"] is None and fresh["claimed_until"] is None
    assert fresh["state"] == "pending"
    assert fresh["expires_at"] > EXPIRED


def test_the_lease_does_not_widen_what_a_poll_may_return(tmp_path):
    """An expired dispatch is still expired, lease or no lease."""

    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lease-7")
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET claimed_until=?, expires_at=? WHERE dispatch_id=?",
        EXPIRED, EXPIRED, dispatch_id,
    ))
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("poll-dead"),
    )) is False
