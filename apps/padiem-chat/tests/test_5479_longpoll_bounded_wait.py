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
    # Nothing answered: the loop sleeps and asks again rather than holding the
    # request open, so the shorter ceiling costs no extra requests while idle.
    assert "time.sleep(max(1, min(wait, 300)))" in source
    assert 'self._post(POLL_PATH, payload)' in source
