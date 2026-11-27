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
CHAT_POLL = ROOT / "app/oracle_mesh_poll.py"
EXECUTOR = ROOT.parent / "korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py"
# #8212 moved the service loop (the bounded wait between asks) into its own
# module; the contract pins the loop wherever the executor runs it.
SERVICE_LOOP = ROOT.parent / "korean-ai-code-agent/src/kagent/local_agent_mesh_concurrency.py"


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
    # #8212: both the serial loop and the opt-in worker pool live in the
    # concurrency module and keep the same bounded wait.
    service_loop = SERVICE_LOOP.read_text(encoding="utf-8")
    assert "time.sleep(max(1, min(wait, 300)))" in service_loop
    assert "stop.wait(max(1, min(wait, 300)))" in service_loop
    assert 'self._post(POLL_PATH, payload)' in source


def test_actual_poll_wait_and_cancel_contract(monkeypatch):
    import asyncio
    import json
    import time
    from types import SimpleNamespace
    from app import oracle_mesh_poll as poll, oracle_mesh_read_return_routes as routes
    from _support.mesh_online_projection import _PollRequest, _poll_state, _PresenceStore, POLL_SECRET

    assert routes.oracle_mesh_read_poll is poll.oracle_mesh_read_poll
    for header, expected in [(None, []), ("5", [2, 2, 1]), ("20", [2, 2, 1]), ("999", [])]:
        async def run():
            elapsed = [0.0]
            sleeps = []
            reads = []
            async def sleep(seconds):
                sleeps.append(seconds)
                elapsed[0] += seconds
            async def read():
                reads.append(elapsed[0])
                return None
            async def claim(**kwargs):
                raise AssertionError("empty queue must not be claimed")
            state = _poll_state(_PresenceStore())
            state.history_store = SimpleNamespace(oldest_pending_oracle_mesh_dispatch=read, claim_oracle_mesh_dispatch=claim)
            request = _PollRequest({}, state, secret=POLL_SECRET)
            if header is not None:
                request.headers["x-oracle-mesh-wait"] = header
            with monkeypatch.context() as m:
                m.setattr(time, "monotonic", lambda: elapsed[0])
                m.setattr(asyncio, "sleep", sleep)
                response = await poll.oracle_mesh_read_poll(request)
                assert response.status_code == 200
                assert json.loads(response.body) == {"ok": True, "dispatch": None}
                assert sleeps == expected
                assert len(reads) == len(expected) + 1
                assert elapsed[0] == sum(expected)
        asyncio.run(run())

    async def cancel_during_wait():
        state = _poll_state(_PresenceStore())
        request = _PollRequest({}, state, secret=POLL_SECRET)
        request.headers["x-oracle-mesh-wait"] = "20"
        reads = []
        async def read():
            reads.append(True)
            return None
        async def stop(seconds):
            assert 0 < seconds <= 2
            raise asyncio.CancelledError
        async def claim(**kwargs):
            raise AssertionError("cancelled poll must not claim")
        state.history_store = SimpleNamespace(oldest_pending_oracle_mesh_dispatch=read, claim_oracle_mesh_dispatch=claim)
        import pytest
        with monkeypatch.context() as m:
            m.setattr(asyncio, "sleep", stop)
            with pytest.raises(asyncio.CancelledError):
                await poll.oracle_mesh_read_poll(request)
        assert reads == [True]
    asyncio.run(cancel_during_wait())
