"""#8061 13차: shared setup for the Claw live SSE relay contract tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind, public_orchestration_event,
)
from _support.claw_general_routing import (
    _client, _make_adapter, _make_outcome, _payload,
)

HEADERS = {"X-Padiem-Claw-Live": "p01-events-v1"}
SUBJECT = "sub_" + "9" * 32


def _event(sequence, kind):
    return public_orchestration_event(
        event_id=f"evt_{sequence}", run_id="orch_verified_1",
        trace_id="trace_verified_1", app_id="b54-padiem-claw",
        kind=kind, sequence=sequence,
        timestamp_iso="2026-10-10T00:10:00Z",
        message="password=must-never-leak", metadata={"internal_note": "private"},
    )


def _streaming_adapter(status="completed", error=None):
    adapter = _make_adapter(subject_lane=True)
    adapter._runner = SimpleNamespace(run_stream=lambda *args, **kwargs: None)

    async def execute(run, *, on_event, **kwargs):
        adapter._seen_kwargs = kwargs
        await on_event(_event(1, OrchestrationEventKind.RUN_STARTED))
        if error:
            raise error
        await on_event(_event(2, OrchestrationEventKind.TOOL_STARTED))
        await on_event(_event(3, OrchestrationEventKind.TOOL_COMPLETED))
        if status == "waiting_approval":
            await on_event(_event(4, OrchestrationEventKind.APPROVAL_PAUSED))
        else:
            await on_event(_event(4, OrchestrationEventKind.RUN_COMPLETED))
        return _make_outcome(status=status, answer="검증된 답변" if status=="completed" else None)

    adapter.execute = AsyncMock(side_effect=execute)
    return adapter


def _call(adapter, headers=HEADERS, enabled=True, payload=None):
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new=AsyncMock(return_value=SimpleNamespace(auth_session=SimpleNamespace(subject=SimpleNamespace(subject_id=SUBJECT))))):
        with _client(adapter) as client:
            client.app.state.claw_live_sse_enabled = enabled
            result = client.post("/api/claw/general", json=payload or _payload(), headers=headers)
    return result
