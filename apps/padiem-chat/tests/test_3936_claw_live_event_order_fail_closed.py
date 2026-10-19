"""#3936: malformed *Core-owned* P01 event sequences must not mint live success.

Provider-free route-level regressions. Legitimate single-terminal paths are
already pinned in test_3930_b54_live_sse_relay.py and actual production frame
order was captured once under owner authorization. No live model calls here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from padiem_ai_core.orchestration_events import OrchestrationEventKind as K

from test_3930_b54_live_sse_relay import _call, _event, _streaming_adapter
from test_b54_claw_general_p01_routing import _make_outcome


@pytest.mark.parametrize(
    "events",
    [
        ((1, K.RUN_STARTED), (2, K.RUN_COMPLETED), (3, K.RUN_COMPLETED)),
        ((1, K.RUN_STARTED), (2, K.RUN_COMPLETED), (3, K.TOOL_STARTED)),
        ((2, K.RUN_STARTED), (1, K.TOOL_STARTED), (3, K.RUN_COMPLETED)),
        ((1, K.RUN_STARTED), (2, K.TOOL_STARTED), (2, K.RUN_COMPLETED)),
    ],
    ids=[
        "duplicate-completed-terminal",
        "progress-after-completed-terminal",
        "regressing-event-sequence",
        "duplicate-event-sequence",
    ],
)
def test_invalid_source_event_stream_fails_closed_without_answer_or_done(events):
    adapter = _streaming_adapter()

    async def inconsistent_core(run, *, on_event, **kwargs):
        for sequence, kind in events:
            await on_event(_event(sequence, kind))
        return _make_outcome(status="completed", answer="must-not-appear")

    adapter.execute = AsyncMock(side_effect=inconsistent_core)
    response = _call(adapter)

    # Streaming headers may already be sent; a bounded SSE error, never a
    # successful delta/done, is the only trustworthy recovery projection.
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: error") == 1
    assert "event: delta" not in response.text
    assert "event: done" not in response.text
    assert '"kind":"run_completed"' not in response.text
    assert "must-not-appear" not in response.text
    adapter.execute.assert_awaited_once()


def test_repeated_failure_terminal_cannot_be_recast_as_completed_answer():
    adapter = _streaming_adapter()

    async def repeated_failed_core(run, *, on_event, **kwargs):
        await on_event(_event(1, K.RUN_STARTED))
        await on_event(_event(2, K.RUN_FAILED))
        await on_event(_event(3, K.RUN_FAILED))
        return _make_outcome(status="completed", answer="false-completed-answer")

    adapter.execute = AsyncMock(side_effect=repeated_failed_core)
    response = _call(adapter)

    assert response.status_code == 200
    assert response.text.count("event: error") == 1
    assert response.text.count('"kind":"run_failed"') <= 1
    assert "event: done" not in response.text
    assert "event: delta" not in response.text
    assert "false-completed-answer" not in response.text
    adapter.execute.assert_awaited_once()
