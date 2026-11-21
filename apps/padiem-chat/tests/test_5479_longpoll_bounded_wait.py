"""#5479: the executor long-poll waits five seconds, on both sides of the wire.

A twenty second wait held one Worker request open while it re-read D1 every
couple of seconds, so concurrent executors piled onto a single event loop —
the shape behind the NoGilError / "Cannot enter into task" burst. The executor
already re-requests as soon as an empty answer comes back, so the ceiling is
now five seconds and a legacy 20 is capped to it as well. The wait is still a
sleep between reads, never a spin.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kagent import local_agent_mesh_concurrency as concurrency

ROOT = Path(__file__).resolve().parents[1]
CHAT_POLL = ROOT / "app/oracle_mesh_read_return_routes.py"
EXECUTOR = ROOT.parent / "korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py"


def test_the_chat_poll_never_holds_a_request_for_more_than_five_seconds() -> None:
    source = CHAT_POLL.read_text(encoding="utf-8")

    assert 'wait_seconds = 5 if wait_header in ("5", "20") else 0' in source
    assert "wait_seconds = 20" not in source, "a twenty second hold is the defect"
    # The wait is a sleep between reads, not a spin, and it is bounded by the
    # deadline it was given.
    assert "await asyncio.sleep(min(2, max(0.01, deadline - time.monotonic())))" in source
    assert "pending = await history_store.oldest_pending_oracle_mesh_dispatch()" in source


def test_the_executor_asks_for_the_short_wait_and_keeps_re_requesting() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")

    assert '**({"X-Oracle-Mesh-Wait": "5"} if path == POLL_PATH else {}),' in source
    assert '"X-Oracle-Mesh-Wait": "20"' not in source
    assert 'self._post(POLL_PATH, payload)' in source


@pytest.mark.parametrize("worker", [False, True], ids=["serial", "concurrent"])
@pytest.mark.parametrize(
    ("requested", "expected"),
    [(-10, 1), (0, 1), (37, 37), (301, 300), (True, 5), (None, 5)],
)
def test_the_executor_bounds_retry_wait_and_polls_again(
    monkeypatch: pytest.MonkeyPatch, worker: bool, requested: object, expected: int,
) -> None:
    # #8212 moved the serial loop and added a worker loop. Exercise both
    # shipped loops with recorded waits: a failed round is bounded, a
    # successful round is not delayed, and each returns to polling.
    events = []
    results = iter([{"ok": False, "wait_seconds": requested}, {"ok": True}])

    def run_once():
        events.append("poll")
        return next(results)

    def wait(seconds):
        events.append(("wait", seconds))

    executor = SimpleNamespace(
        run_once=run_once,
        line_observations=lambda: {"line_blocked_total": 0, "line_cleared_total": 0},
    )
    monkeypatch.setattr(concurrency, "time", SimpleNamespace(sleep=wait, monotonic=lambda: 0.0))
    stop = SimpleNamespace(is_set=lambda: False, wait=wait)

    with pytest.raises(StopIteration):
        if worker:
            concurrency._worker_round(executor, stop, idle=5, clock=lambda: 0.0)
        else:
            concurrency._serial_round(executor, idle=5)

    assert events == ["poll", ("wait", expected), "poll", "poll"]
