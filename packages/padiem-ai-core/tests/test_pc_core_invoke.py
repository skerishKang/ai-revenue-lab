"""Read-only observer: no execution deadlines, cancellation or value logging."""
import asyncio
import pytest
from padiem_ai_core import _pc_core_invoke as diag

TOOL = "claw.pc.query_drives"


def test_observer_waits_30_seconds_and_only_observes(monkeypatch, capsys):
    async def scenario():
        released = asyncio.Event()
        entered = asyncio.Event()
        async def sleep(seconds):
            assert seconds == 30.0
            entered.set()
            await released.wait()
        monkeypatch.setattr(diag, "_sleep", sleep)
        with diag.pc_core_stage("handler_wait_for", TOOL, timeout=None):
            await entered.wait()
            released.set()
            await asyncio.sleep(0)
            assert "state=still_waiting timeout=None" in capsys.readouterr().out
        await asyncio.sleep(0)
        assert "state=done timeout=None" in capsys.readouterr().out
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError])
def test_observer_preserves_exception_and_cleans_up(monkeypatch, capsys, failure):
    async def scenario():
        before = asyncio.all_tasks()
        expected = failure("private-value")
        with pytest.raises(failure) as caught:
            with diag.pc_core_stage("run_guard", TOOL, guard_injected=True):
                await asyncio.sleep(0)
                raise expected
        assert caught.value is expected
        await asyncio.sleep(0)
        assert asyncio.all_tasks() == before
        output = capsys.readouterr().out
        assert "state=done guard_injected=true" in output
        assert "private-value" not in output
        assert "still_waiting" not in output
    asyncio.run(scenario())


def test_logs_allow_only_closed_fields(capsys):
    diag.pc_core_log("decision", TOOL, "enter", prompt="private", guard_injected=True)
    diag.pc_core_log("decision", "private", "enter")
    assert capsys.readouterr().out == (
        "pc_core_invoke stage=decision tool=claw.pc.query_drives state=enter guard_injected=true\n")
