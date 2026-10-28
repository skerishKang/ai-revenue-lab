"""#5895 — stopping PC work releases the queue, and reaches work already in hand.

`/api/pc/find` is spread over folders so one sweep cannot hold a PC, and
`/api/pc/cancel` takes back the folders the PC has not started looking in. A folder the
PC is already inside is not failed either: it carries the stop in the column that
already records how a command ended, the executor reads that through the same channel
secret it polls with, and its result still lands. Both rules come down to one SQL
condition, so this runs the real `D1HistoryStore` against the real
committed schema (the 047→074 replay) — the same ground the claim-lease test stands on.
No executor is involved and no PC command is executed here: what is proved is which row
the poll hands out, and that a stopped row can never be claimed or answered later.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect

from app.history import D1HistoryStore
from test_4139_mesh_original import _dispatch_kwargs, fixture

OWNER = "usr_owner_4139"
FOREIGN = "usr_foreign_4139"
CONVERSATION = "chat_" + "c" * 32
SWEEP_RUN = "chat_pcq_" + "a" * 32
LISTING_RUN = "chat_pcq_" + "b" * 32
FOREIGN_RUN = "chat_pcq_" + "f" * 32


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _stage(store, run_id: str, *, user_id: str = OWNER, command: str = "Get-ChildItem x"):
    """One pending dispatch of its own run, exactly as the lane stages it."""

    tail = run_id[-4:]
    asyncio.run(store.record_claw_run(
        user_id=user_id, run_id=run_id, channel="web", action="pc_files_query",
        title="PC 파일: 찾기", status="pending", conversation_id=CONVERSATION,
        workspace_id="ws-1",
    ))
    # The trusted file lane correlates a call by one reference used both ways, so
    # a staged row here is shaped exactly like one staged there.
    call_ref = "call-" + tail
    row = asyncio.run(store.create_oracle_mesh_dispatch(**_dispatch_kwargs(
        run_id=run_id, user_id=user_id, command_text=command,
        tool_call_ref=call_ref, tool_request_ref=call_ref,
        request_id="r-" + tail, revision_ref="rev-" + tail,
    )))
    return row["dispatch_id"]


def _row(store, dispatch_id: str) -> dict:
    return asyncio.run(store._first(
        "SELECT state, termination, nonce_sha256, expires_at FROM oracle_mesh_dispatch "
        "WHERE dispatch_id=?", dispatch_id,
    ))


def _stopped(store, run_id: str, *, user_id: str = OWNER) -> int:
    return asyncio.run(store.cancel_oracle_mesh_dispatches_for_run(
        user_id=user_id, run_id=run_id,
    ))


def test_a_cancelled_folder_is_never_handed_out_and_the_next_one_is(tmp_path):
    store, _bucket = fixture(tmp_path)
    swept = _stage(store, SWEEP_RUN,
                   command="Get-ChildItem -LiteralPath 'C:/Windows' -Recurse")
    listing = _stage(store, LISTING_RUN,
                     command="Get-ChildItem -LiteralPath 'C:/Users/qa' -Force")

    # The queue is arrival-ordered, so the long sweep is what the PC would do next.
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch())["dispatch_id"] == swept
    assert _stopped(store, SWEEP_RUN) == 1

    # The listing the owner asked for is served straight away. This is the whole
    # point: stopping the long job must not mean waiting for it.
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["dispatch_id"] == listing and handed["state"] == "pending"
    stopped = _row(store, swept)
    assert stopped["state"] == "failed" and stopped["termination"] == "cancelled"
    # The dispatch's own life is untouched — only its place in the queue went away.
    assert stopped["expires_at"]


def test_a_cancelled_folder_cannot_be_claimed_afterwards(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _stage(store, SWEEP_RUN)
    assert _stopped(store, SWEEP_RUN) == 1
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("after-the-stop"),
    )) is False


def test_a_stop_reaches_the_folder_the_pc_is_already_in(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _stage(store, SWEEP_RUN)
    # The lane hands out a hash of the nonce it generated and accepts the submission
    # that presents the nonce itself, so the two are kept apart here as they are
    # apart in the lane.
    presented = "poll-one"
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce(presented),
    )) is True

    # The owner pressed 그만 while the PC held this folder. The row is not failed:
    # it keeps its claim and its pending state, and carries the stop in the column
    # that already records how a command ended, so the executor can read the stop and
    # the result it still owes lands through the nonce gate it already holds.
    assert _stopped(store, SWEEP_RUN) == 1
    row = _row(store, dispatch_id)
    assert row["state"] == "pending" and row["termination"] == "cancelled"
    assert asyncio.run(store.oracle_mesh_dispatch_cancellation(dispatch_id=dispatch_id)) is True
    consumed = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce=presented,
    ))
    assert consumed is not None and consumed["claim"] == "first"


def test_an_unstopped_or_unreadable_dispatch_is_not_a_stop(tmp_path):
    """Only the owner's own recorded stop answers yes - never a read that failed."""
    store, _bucket = fixture(tmp_path)
    queued = _stage(store, SWEEP_RUN)
    other = _stage(store, LISTING_RUN)

    assert asyncio.run(store.oracle_mesh_dispatch_cancellation(dispatch_id=other)) is False
    assert asyncio.run(store.oracle_mesh_dispatch_cancellation(dispatch_id=queued)) is False
    # An id this account never staged is not addressable at all: the answer is no.
    assert asyncio.run(
        store.oracle_mesh_dispatch_cancellation(dispatch_id="dsp_not_a_real_dispatch")
    ) is False
    assert _stopped(store, SWEEP_RUN) == 1
    # Work that never reached a PC is ended on the spot, so there is nothing for an
    # executor to read: the flag exists only for the row whose command is running.
    assert _row(store, queued)["state"] == "failed"
    assert asyncio.run(store.oracle_mesh_dispatch_cancellation(dispatch_id=queued)) is False
    assert asyncio.run(store.oracle_mesh_dispatch_cancellation(dispatch_id=other)) is False


def test_a_stop_touches_no_other_run_and_no_other_account(tmp_path):
    store, _bucket = fixture(tmp_path)
    stopped = _stage(store, SWEEP_RUN)
    other_run = _stage(store, LISTING_RUN)
    foreign = _stage(store, FOREIGN_RUN, user_id=FOREIGN, command="Get-ChildItem 'D:/남의 것'")

    assert _stopped(store, SWEEP_RUN) == 1
    assert _row(store, stopped)["state"] == "failed"
    # This account's next search and another account's folder both stay queued.
    assert _row(store, other_run)["state"] == "pending"
    assert _row(store, foreign)["state"] == "pending"
    assert _stopped(store, FOREIGN_RUN) == 0
    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch())["dispatch_id"] == other_run


def test_the_stop_is_two_conditional_statements_naming_no_second_authority():
    source = inspect.getsource(D1HistoryStore.cancel_oracle_mesh_dispatches_for_run)
    # Queued work is taken out of the poll's own condition (pending, no nonce); work
    # already in hand is only flagged, in the column that already ends a command, so
    # the executor's owed submission still lands through its nonce gate.
    assert "state=?" in source and "nonce_sha256 IS NULL" in source
    assert "nonce_sha256 IS NOT NULL" in source
    assert "user_id=? AND run_id=?" in source
    for forbidden in ("UPDATE claw_run_history", "DELETE FROM", "DROP", "expires_at=?"):
        assert forbidden not in source, forbidden
    # No second table and no new column: the row's own end is the record of the stop.
    assert "oracle_mesh_dispatch SET state=?, termination=?" in source
    assert "oracle_mesh_dispatch SET termination=? " in source
