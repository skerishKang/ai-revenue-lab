"""#6923: a stalled Chat event loop leaves a journal line and arms a stack dump.

On 2026-11-05 15:11:23-15:12:11 KST the com2 Chat process ran nothing for
47 s and the journal held no line from inside the stall. The watchdog's
heartbeat journals how late it woke, and ``faulthandler`` is kept armed so a
longer stall dumps every thread's stack while it lasts.
"""
from __future__ import annotations

import asyncio
import re
import time

import pytest
from starlette.applications import Starlette

from app import loop_stall_watchdog as module
from app.loop_stall_watchdog import LoopStallWatchdog, install, watchdog_enabled

LINE = re.compile(
    r"^\[local\] loop_stall lag_ms=(\d+) tick_ms=(\d+) stalls=(\d+) worst_lag_ms=(\d+)$"
)


class _Recorder:
    def __init__(self, *, arm_raises: BaseException | None = None) -> None:
        self.lines: list[str] = []
        self.arms: list[tuple[tuple, dict]] = []
        self.cancels = 0
        self._arm_raises = arm_raises

    def journal(self, line: str) -> None:
        self.lines.append(line)

    def arm(self, *args, **kwargs):
        if self._arm_raises is not None:
            raise self._arm_raises
        self.arms.append((args, kwargs))

    def cancel(self):
        self.cancels += 1


def _watchdog(recorder: _Recorder, **overrides) -> LoopStallWatchdog:
    options = dict(
        tick_seconds=0.01,
        lag_threshold_seconds=0.05,
        stall_dump_seconds=10.0,
        journal=recorder.journal,
        arm_dump=recorder.arm,
        cancel_dump=recorder.cancel,
    )
    options.update(overrides)
    return LoopStallWatchdog(**options)


async def _run_with_a_block(watchdog: LoopStallWatchdog, *, block_seconds: float) -> None:
    task = asyncio.get_running_loop().create_task(watchdog.run())
    await asyncio.sleep(0.03)          # a few quiet heartbeats
    time.sleep(block_seconds)          # the loop runs nothing meanwhile
    await asyncio.sleep(0.05)          # the late heartbeat gets to report
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_a_blocked_loop_leaves_one_line_with_its_lag():
    recorder = _Recorder()
    watchdog = _watchdog(recorder)

    asyncio.run(_run_with_a_block(watchdog, block_seconds=0.15))

    assert len(recorder.lines) == 1, recorder.lines
    match = LINE.match(recorder.lines[0])
    assert match, recorder.lines[0]
    lag_ms, tick_ms, stalls, worst = (int(group) for group in match.groups())
    assert 100 <= lag_ms < 2_000
    assert tick_ms == 10
    assert stalls == 1 and worst == lag_ms
    assert watchdog.stalls == 1 and watchdog.worst_lag_ms == lag_ms


def test_the_dump_is_armed_every_heartbeat_and_disarmed_on_exit():
    recorder = _Recorder()
    watchdog = _watchdog(recorder)

    asyncio.run(_run_with_a_block(watchdog, block_seconds=0.0))

    assert len(recorder.arms) >= 3
    for args, kwargs in recorder.arms:
        assert args == (10.0,)
        assert kwargs["repeat"] is True
        assert kwargs["exit"] is False
        assert kwargs["file"] is not None
    assert recorder.cancels == 1
    assert watchdog.dump_armed is False


def test_a_quiet_loop_journals_nothing():
    recorder = _Recorder()
    watchdog = _watchdog(recorder)

    asyncio.run(_run_with_a_block(watchdog, block_seconds=0.0))

    assert recorder.lines == []
    assert watchdog.stalls == 0


def test_an_unusable_stderr_skips_only_the_dump():
    recorder = _Recorder(arm_raises=RuntimeError("stderr is closed"))
    watchdog = _watchdog(recorder)

    asyncio.run(_run_with_a_block(watchdog, block_seconds=0.15))

    assert watchdog.dump_armed is False
    assert recorder.cancels == 0
    assert len(recorder.lines) == 1          # the heartbeat still reported the block


def test_a_zero_dump_budget_turns_off_the_dump_but_not_the_heartbeat():
    recorder = _Recorder()
    watchdog = _watchdog(recorder, stall_dump_seconds=0)

    asyncio.run(_run_with_a_block(watchdog, block_seconds=0.15))

    assert recorder.arms == []
    assert recorder.cancels == 0
    assert len(recorder.lines) == 1


def test_the_defaults_fit_the_observed_stall():
    # A 47 s stall is well past the dump budget, and the heartbeat's own cost
    # (one wake-up a second) is negligible.
    assert module.TICK_SECONDS == 1.0
    assert module.LAG_THRESHOLD_SECONDS == 2.0
    assert module.STALL_DUMP_SECONDS == 10.0
    assert module.STALL_DUMP_SECONDS < 47.0


# --- the host wiring ----------------------------------------------------------


def _startup_and_shutdown(app: Starlette):
    return app.router.on_startup[-1], app.router.on_shutdown[-1]


def test_install_starts_with_the_app_and_stops_with_it(capsys):
    app = Starlette()
    recorder = _Recorder()
    before = (len(app.router.on_startup), len(app.router.on_shutdown))

    installed = install(app, env={}, watchdog_factory=lambda: _watchdog(recorder))

    assert installed is True
    assert (len(app.router.on_startup), len(app.router.on_shutdown)) == (before[0] + 1, before[1] + 1)
    start, stop = _startup_and_shutdown(app)

    async def scenario():
        await start()
        first = app.state.loop_stall_watchdog_task
        assert not first.done()
        assert isinstance(app.state.loop_stall_watchdog, LoopStallWatchdog)
        await start()                                   # idempotent on one loop
        assert app.state.loop_stall_watchdog_task is first
        await asyncio.sleep(0.03)
        await stop()
        assert first.done() and first.cancelled()
        assert app.state.loop_stall_watchdog_task is None
        await stop()                                    # a second stop is a no-op

    asyncio.run(scenario())
    assert recorder.cancels == 1
    out = capsys.readouterr().out
    assert "[local] loop_stall_watchdog=on tick_ms=10 lag_threshold_ms=50 stall_dump_s=10" in out


@pytest.mark.parametrize("raw", ["off", "0", "false", "no", " OFF "])
def test_the_env_switch_turns_the_watchdog_off(raw, capsys):
    app = Starlette()
    before = (len(app.router.on_startup), len(app.router.on_shutdown))

    assert install(app, env={module.WATCHDOG_ENV: raw}) is False

    assert (len(app.router.on_startup), len(app.router.on_shutdown)) == before
    assert "[local] loop_stall_watchdog=off" in capsys.readouterr().out


@pytest.mark.parametrize("env, expected", [
    ({}, True),
    ({module.WATCHDOG_ENV: ""}, True),
    ({module.WATCHDOG_ENV: "on"}, True),
    ({module.WATCHDOG_ENV: "1"}, True),
    ({module.WATCHDOG_ENV: "off"}, False),
    ({module.WATCHDOG_ENV: "0"}, False),
])
def test_watchdog_enabled_reads_the_switch(env, expected):
    assert watchdog_enabled(env) is expected
