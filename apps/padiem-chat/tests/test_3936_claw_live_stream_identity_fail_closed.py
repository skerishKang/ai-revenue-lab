"""#3936: one browser live P01 stream must retain one Core run/trace/app identity.

Source-only, provider-free; real signed Starlette route using a synthetic
canonical Core event adapter. Existing successful SSE and approval/cancel
contracts stay unchanged. No production/model execution is permitted here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind as K,
    public_orchestration_event,
)

from test_3930_b54_live_sse_relay import _call, _streaming_adapter
from test_b54_claw_general_p01_routing import _make_outcome


RUN = "orch_verified_1"
TRACE = "trace_verified_1"
APP = "b54-padiem-claw"


def _event(
    sequence: int, kind: K, *, run_id: str = RUN, trace_id: str = TRACE,
    app_id: str = APP, event_id: str | None = None,
):
    return public_orchestration_event(
        event_id=event_id or f"evt_{sequence}",
        run_id=run_id,
        trace_id=trace_id,
        app_id=app_id,
        kind=kind,
        sequence=sequence,
        timestamp_iso="2026-10-14T00:00:00Z",
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"run_id": "another_verified_run"},
        {"trace_id": "another_verified_trace"},
        {"app_id": "another_p01_app"},
        {"event_id": "evt_1"},
    ],
    ids=["different-run", "different-trace", "different-app", "replayed-event-id"],
)
def test_mixed_stream_identity_refuses_verified_completion(changed):
    adapter = _streaming_adapter()

    async def mixed_core(run, *, on_event, **kwargs):
        await on_event(_event(1, K.RUN_STARTED))
        await on_event(_event(2, K.CONTEXT_PREPARED, **changed))
        await on_event(_event(3, K.RUN_COMPLETED))
        return _make_outcome(status="completed", answer="not-an-authorized-answer")

    adapter.execute = AsyncMock(side_effect=mixed_core)
    response = _call(adapter)

    assert response.status_code == 200  # SSE headers may already be sent.
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: error") == 1
    assert response.text.count("event: p01_event") == 1  # first verified start
    assert "event: delta" not in response.text
    assert "event: done" not in response.text
    assert '"kind":"run_completed"' not in response.text
    assert "not-an-authorized-answer" not in response.text
    adapter.execute.assert_awaited_once()


def test_stable_identity_and_unique_event_ids_allow_normal_success():
    adapter = _streaming_adapter()

    async def canonical_core(run, *, on_event, **kwargs):
        await on_event(_event(1, K.RUN_STARTED))
        await on_event(_event(2, K.CONTEXT_PREPARED))
        await on_event(_event(3, K.RUN_COMPLETED))
        return _make_outcome(status="completed", answer="verified-success")

    adapter.execute = AsyncMock(side_effect=canonical_core)
    response = _call(adapter)

    assert response.status_code == 200
    assert response.text.count("event: p01_event") == 3
    assert response.text.count("event: delta") == 1
    assert response.text.count("event: done") == 1
    assert response.text.count('"kind":"run_completed"') == 1
    assert "verified-success" in response.text
    adapter.execute.assert_awaited_once()
