"""#7841 — a Chat PC dispatch expires with the answer window that asked for it.

The dispatch row is staged on an Engine -> Chat signed call, so the turn's own
remaining budget does not travel as a field. These tests pin the two halves that
keep the behaviour safe without a new queue or executor contract:

* a Chat PC turn shortens the created row's TTL to the answer budget minus the
  time already spent, plus the small claim beat;
* every other caller (no turn scope, no staged run time) keeps the existing
  ten-minute value;
* a row whose short TTL has passed is no longer claimable, while the existing
  result-after-TTL owner decision is untouched.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.pc_dispatch_ttl import (
    PC_DISPATCH_TTL_SLACK_SECONDS,
    chat_pc_dispatch_ttl,
    chat_pc_dispatch_ttl_scope,
    dispatch_ttl_seconds,
)

from _support.mesh_dispatch import CONVERSATION, OWNER, _dispatch_kwargs, fixture


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _staged(store, run_id: str, *, expires_at: str) -> str:
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=run_id, channel="web", action="txt_read",
        title="Chat: short-lived dispatch", status="pending",
        conversation_id=CONVERSATION, workspace_id="ws-1",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id=run_id, expires_at=expires_at),
    ))
    return row["dispatch_id"]


def test_an_unscoped_caller_keeps_the_existing_ten_minute_ttl():
    assert chat_pc_dispatch_ttl_scope() is False
    assert dispatch_ttl_seconds({"updated_at": _iso(datetime.now(timezone.utc))}) is None


def test_a_chat_turn_shortens_the_ttl_to_its_remaining_answer_budget():
    from app.orchestration_routes import ANSWER_BUDGET_MARGIN_MS, DEFAULT_ANSWER_BUDGET_MS

    now = time.time()
    run_row = {"updated_at": _iso(datetime.fromtimestamp(now - 10, tz=timezone.utc))}
    expected = (
        DEFAULT_ANSWER_BUDGET_MS / 1000.0
        - 10
        - ANSWER_BUDGET_MARGIN_MS / 1000.0
        + PC_DISPATCH_TTL_SLACK_SECONDS
    )

    @chat_pc_dispatch_ttl
    async def _turn():
        return dispatch_ttl_seconds(run_row, now=now)

    ttl = asyncio.run(_turn())
    assert ttl == int(expected)
    assert ttl < 600
    # The scope never leaks into the next call.
    assert chat_pc_dispatch_ttl_scope() is False


def test_a_run_whose_window_already_closed_gets_the_one_second_floor():
    run_row = {
        "updated_at": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
    }

    @chat_pc_dispatch_ttl
    async def _turn():
        return dispatch_ttl_seconds(run_row)

    assert asyncio.run(_turn()) == 1


def test_a_run_without_a_usable_stage_time_falls_back_to_the_default():
    @chat_pc_dispatch_ttl
    async def _turn(run_row):
        return dispatch_ttl_seconds(run_row)

    assert asyncio.run(_turn({"updated_at": "not-a-time"})) is None
    assert asyncio.run(_turn({})) is None


def test_the_scope_resets_even_when_the_turn_raises():
    @chat_pc_dispatch_ttl
    async def _turn():
        assert chat_pc_dispatch_ttl_scope() is True
        raise RuntimeError("turn failed")

    with pytest.raises(RuntimeError):
        asyncio.run(_turn())
    assert chat_pc_dispatch_ttl_scope() is False


def test_a_short_ttl_row_is_not_claimable_after_it_expires(tmp_path):
    """The short row is work only while its own answer window is open."""

    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(
        store, "run-short-ttl",
        expires_at=_iso(datetime.now(timezone.utc) - timedelta(seconds=1)),
    )

    assert asyncio.run(store.oldest_pending_oracle_mesh_dispatch()) is None
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id,
        nonce_sha256="a" * 64,
    )) is False


def test_the_confirmation_click_writes_a_fresh_updated_at(tmp_path):
    """A card confirmed minutes later is a *new* turn row, not the old one."""

    store, _bucket = fixture(tmp_path)
    run_id = "run-confirm-later"
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=run_id, channel="web", action="pc_command",
        title="Chat: card", status="waiting_approval",
        conversation_id=CONVERSATION, workspace_id="ws-1",
    ))
    asyncio.run(store._run(
        "UPDATE claw_run_history SET updated_at=? WHERE run_id=? AND user_id=?",
        _iso(datetime.now(timezone.utc) - timedelta(minutes=5)), run_id, OWNER,
    ))

    click = time.time()
    # dispatch_chat_pc_command runs record_claw_run for this turn before the
    # dispatch intent reads the row.
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=run_id, channel="web", action="pc_command",
        title="Chat: card", status="pending",
        conversation_id=CONVERSATION, workspace_id="ws-1",
    ))
    row = asyncio.run(store.get_claw_run(OWNER, run_id))
    assert datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")).timestamp() >= click - 2

    @chat_pc_dispatch_ttl
    async def _turn():
        return dispatch_ttl_seconds(row)

    ttl = asyncio.run(_turn())
    assert ttl is not None and ttl > 30


def test_a_card_confirmed_five_minutes_later_creates_a_live_dispatch_window(monkeypatch):
    """The real signed Chat file route: a stale card row must not become 1s."""

    import test_5015_pc_read_dispatch as harness

    history = harness._History()
    history.run_rows[harness.RUN]["updated_at"] = _iso(
        datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    state = harness._state(monkeypatch, history=history)

    click = time.time()
    # record_claw_run at confirmation refreshes the run the intent will read.
    history.run_rows[harness.RUN]["updated_at"] = _iso(
        datetime.fromtimestamp(click, tz=timezone.utc),
    )
    status, body = harness._dispatch(state, harness._base_payload())

    assert status == 200 and body["ok"] is True
    created = next(iter(history.rows.values()))
    expires = datetime.fromisoformat(
        created["expires_at"].replace("Z", "+00:00"),
    ).timestamp()
    assert 30 < expires - click < 120, (
        "a confirmed card must get its own window, not the card's age or 600s"
    )
