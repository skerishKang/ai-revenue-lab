"""#6919 — the PC file step's first wait counts from the call, not from the dispatch.

The Chat gateway cuts the call that carries this handler at 30 s, and the
Engine's admission and receipt live inside that same 30 s. Counting the first
wait from the dispatch let a slow context read plus a slow admission push the
whole call to 33 s, so the gateway answered ``pc_dispatch_failed`` while the
PC had in fact finished. The budget now starts when the handler is entered.
"""

from __future__ import annotations

import asyncio
import time
import types

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_FILES_WAIT_SECONDS,
    PC_LIST_FILES_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    _make_pc_file_handler,
)

import pytest

RUN_ID = "run_261105_anchor"
SUBJECT = "sub_" + "9" * 32
PRODUCT = "padiem-chat"
DEVICE = "pc-com2"
DISPATCH_ID = "dsp_" + "c" * 32


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


class _Clock:
    """A monotonic clock the fake Engine calls advance by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def _install(monkeypatch, clock: _Clock, *, kind: str, dispatch_cost: float, poll_cost: float) -> list[str]:
    modes: list[str] = []

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        modes.append(mode)
        if mode == "dispatch":
            clock.now += dispatch_cost
            return {"dispatch": {"run_id": RUN_ID, "kind": kind,
                                 "dispatch_id": DISPATCH_ID}}
        if mode == "command_status":
            clock.now += poll_cost
            return {"dispatch": {"dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                                 "kind": kind, "state": "pending",
                                 "termination": "no_exit_code", "exit_code": None}}
        raise AssertionError("unexpected mode " + str(mode))

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setattr(driver, "time", types.SimpleNamespace(monotonic=clock.monotonic, time=time.time))
    return modes


def _handler(op: str, tool_id: str):
    return _make_pc_file_handler(
        tool_id=tool_id, op=op, service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
    )


@pytest.mark.parametrize("op, tool_id, path", [
    ("list", PC_LIST_FILES_TOOL_ID, "."),
    ("read", PC_READ_FILE_TOOL_ID, "notes.txt"),
])
def test_a_slow_dispatch_spends_the_first_wait_too(monkeypatch, op, tool_id, path):
    # The budget is 5 s and the dispatch alone takes 6 s: the budget is spent
    # before the first poll, so one poll that says "pending" hands the job back.
    clock = _Clock()
    modes = _install(monkeypatch, clock, kind="read" if op == "read" else "command",
                     dispatch_cost=6.0, poll_cost=1.0)
    monkeypatch.setattr(driver, "_pc_files_wait_seconds", lambda: 5.0)

    result = asyncio.run(_handler(op, tool_id)({"path": path}))

    assert result["status"] == "running"
    assert result["job_id"] == DISPATCH_ID
    # Counted from the dispatch, the handler would have kept polling for
    # another five seconds; counted from the call, it answers at once.
    assert modes == ["dispatch", "command_status"]


def test_a_fast_dispatch_still_polls_through_the_remaining_budget(monkeypatch):
    # 1 s dispatch, 1 s per poll, 5 s budget: polls at 2, 3, 4, 5 s elapsed,
    # and the one that reaches the deadline is the last.
    clock = _Clock()
    modes = _install(monkeypatch, clock, kind="command", dispatch_cost=1.0, poll_cost=1.0)
    monkeypatch.setattr(driver, "_pc_files_wait_seconds", lambda: 5.0)

    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    assert result["status"] == "running"
    assert modes == ["dispatch"] + ["command_status"] * 4


def test_the_default_budget_leaves_room_for_admission_and_receipt():
    # Both ceilings are 30 s: the Chat gateway's cut of the Engine call and the
    # connector client's cut of the whole /api/mcp request. Re-measured on
    # 2026-11-07 from com2 journals (p90 of the fixed costs around one
    # first-round read): Chat /api/mcp identity 0.0 s (160 POST lines, 24 h,
    # cached binding), Engine admission 1.8 s (warmer-era engine_timing
    # 1.39–1.47 s; observed steady-state bound), receipt 0.7 s (recent
    # engine_timing receipts 0.35–0.70 s), Chat's own context+dispatch work
    # 0.6 s (12 first-round reads), and the loop's overshoot (one poll plus
    # the result pickup) 2.0 s. The sum must stay clear of 30 s by a margin
    # wider than the day's measurement noise.
    ceiling = 30.0
    observed_overhead = 1.8 + 0.7 + 0.6 + 2.0
    assert PC_FILES_WAIT_SECONDS + observed_overhead <= ceiling - 3.0



def test_status_poll_interval_grows_and_caps_at_five_seconds(monkeypatch):
    """대표 결정(2026-11-07): the status polls start fast and grow
    (0.5 → 1 → 2 → 4, capped at 5 s) so a pending PC stop hammering the host
    while the wait budget runs. The total wait budget is unchanged."""

    sleeps: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    clock = _Clock()
    modes: list[str] = []

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        modes.append(mode)
        if mode == "dispatch":
            clock.now += 1.0
            return {"dispatch": {"run_id": RUN_ID, "kind": "command",
                                 "dispatch_id": DISPATCH_ID}}
        clock.now += 1.0
        return {"dispatch": {"dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                             "kind": "command", "state": "pending",
                             "termination": "no_exit_code", "exit_code": None}}

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", recording_sleep)
    monkeypatch.setattr(driver, "time", types.SimpleNamespace(monotonic=clock.monotonic, time=time.time))
    monkeypatch.setattr(driver, "_pc_files_wait_seconds", lambda: 21.0)

    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    assert result["status"] == "running"
    assert modes[0] == "dispatch"
    # The first wait is 0.5 s and the interval grows 2× up to the 5 s cap.
    assert sleeps[:4] == [0.5, 1.0, 2.0, 4.0]
    assert max(sleeps) <= 5.0
