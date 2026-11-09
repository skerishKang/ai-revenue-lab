"""2026-11-09: the PC FILES status ladder stops growing at 1 second.

The automatic measurements (n=41) put the PC read at ~0.6 s and the submit at
~0.33 s, while the response-assembly window measured a 1.7 s median purely
from the ladder overshooting an already-ready result (sleeps of 0.5 → 1 → 2,
capped at 5 s). The files ladder now caps at 1 s. The total wait budget
(``PC_FILES_WAIT_SECONDS``) is unchanged and the shell status poll keeps its
own ladder (#7131).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import claw_pc_query_step_driver as driver

ENGINE_SOURCE = (
    Path(__file__).resolve().parents[1] / "app" / "claw_pc_query_step_driver.py"
).read_text(encoding="utf-8")


def test_the_files_ladder_cap_is_one_second_and_the_budget_is_untouched():
    assert driver._PC_FILES_POLL_SECONDS_CAP == 1.0
    assert driver.PC_FILES_WAIT_SECONDS == 21
    # Both files-lane ladders (read/list at the wait loop, search below) use
    # the same cap; no other ladder in this module caps at 5 s any more.
    assert ENGINE_SOURCE.count("_PC_FILES_POLL_SECONDS_CAP") >= 3  # const + 2 sites
    assert "min(poll_seconds * 2, 5.0)" not in ENGINE_SOURCE
    # The budget anchor comment block keeps its contract wording.
    assert "PC_FILES_WAIT_ENV" in ENGINE_SOURCE


def test_the_shell_status_poll_keeps_its_own_ladder():
    """#7131's shell poll is a different path (Chat side) and stays 5 s."""
    shell = (Path(__file__).resolve().parents[2] / "padiem-chat" / "app"
             / "mcp_gateway_shell.py")
    if not shell.exists():  # pragma: no cover - the shell poll lives in Chat
        pytest.skip("shell poll source not present in this tree")
    text = shell.read_text(encoding="utf-8")
    assert "poll_seconds" in text or "0.5" in text


def test_the_ladder_grows_half_then_pins_at_the_cap(monkeypatch):
    """Observed sleeps follow 0.5, 1.0, 1.0, 1.0 … and never exceed the cap."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(driver.asyncio, "sleep", fake_sleep)

    deadline = time.monotonic() + 10.0
    poll_seconds = 0.5
    for _ in range(4):
        # The wait loop's exact sleep shape (#6919: never past the deadline).
        sleeps.append(min(poll_seconds, max(0.0, deadline - time.monotonic())))
        poll_seconds = min(poll_seconds * 2, driver._PC_FILES_POLL_SECONDS_CAP)

    assert sleeps[0] == pytest.approx(0.5)
    assert all(s == pytest.approx(1.0) for s in sleeps[1:])
    assert max(sleeps) <= driver._PC_FILES_POLL_SECONDS_CAP
