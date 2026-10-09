"""#3930 live relay: explicit server gate + real Core events only."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind, public_orchestration_event,
)
from kagent.p01_adapter import P01AdapterError, P01DispatchClass

from test_b54_claw_general_p01_routing import (
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


def test_live_disabled_denies_without_dispatch_and_no_auto_fallback():
    adapter = _streaming_adapter()
    response = _call(adapter, enabled=False)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "claw_live_stream_unavailable"
    adapter.execute.assert_not_awaited()


def test_live_only_allowed_with_canonical_stream_runner():
    adapter = _streaming_adapter()
    adapter._runner = None
    response = _call(adapter)
    assert response.status_code == 503
    adapter.execute.assert_not_awaited()


def test_enabled_live_sse_events_before_delta_done_and_no_sensitive_payload():
    adapter = _streaming_adapter()
    response = _call(adapter)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert response.text.count("event: p01_event") == 4
    assert response.text.count("event: delta") == 1
    assert response.text.count("event: done") == 1
    assert response.text.index("event: p01_event") < response.text.index("event: delta")
    assert '"delivery":"live"' in response.text
    assert "must-never-leak" not in response.text
    assert "internal_note" not in response.text
    assert "read_ack" not in response.text
    adapter.execute.assert_awaited_once()


def test_live_passes_explicit_tier_subject_and_user_model_only_once():
    adapter = _streaming_adapter()
    _call(adapter)
    assert adapter._seen_kwargs["product_tier"] is not None
    assert adapter._seen_kwargs["subject_id"] == SUBJECT
    assert "selected_model_id" not in adapter._seen_kwargs


def test_engine_failure_emits_error_not_done_and_never_b14_fallback():
    adapter = _streaming_adapter(error=P01AdapterError(
        "p01_engine_stream_failed", "internal",
        dispatch_class=P01DispatchClass.UNKNOWN,
    ))
    result = _call(adapter)
    assert result.status_code == 200  # Headers already sent when transport fails.
    assert "event: error" in result.text
    assert "event: done" not in result.text
    assert "검증된 답변" not in result.text
    assert "internal" not in result.text


def test_completed_event_never_visible_if_final_answer_is_missing():
    adapter = _streaming_adapter()
    async def unusable(run, *, on_event, **kwargs):
        await on_event(_event(1, OrchestrationEventKind.RUN_STARTED))
        await on_event(_event(2, OrchestrationEventKind.RUN_COMPLETED))
        return _make_outcome(status="completed", answer=None)
    adapter.execute = AsyncMock(side_effect=unusable)
    result = _call(adapter)
    assert result.status_code == 200
    assert "event: error" in result.text
    assert "event: done" not in result.text
    assert '"kind":"run_completed"' not in result.text


def test_approval_pause_is_error_without_browser_authority():
    result = _call(_streaming_adapter(status="waiting_approval"))
    assert result.status_code == 200
    assert "event: error" in result.text
    assert "claw_general_approval_required" in result.text
    assert "event: done" not in result.text
    assert "continuation_ref" not in result.text


def test_legacy_default_route_remains_unchanged_even_when_server_live_enabled():
    adapter = _make_adapter()
    with _client(adapter) as client:
        client.app.state.claw_live_sse_enabled = True
        response = client.post("/api/claw/general", json=_payload())
    assert response.status_code == 200
    assert "event: done" in response.text
    assert "delivery\":\"live" not in response.text
    adapter.execute.assert_awaited_once()


def test_evidence_mode_not_mixed_with_live_run():
    adapter = _streaming_adapter()
    result = _call(adapter, headers={
        **HEADERS, "X-Padiem-Claw-Evidence": "one-shot",
    })
    assert result.status_code == 422
    adapter.execute.assert_not_awaited()

def test_browser_disconnection_cancels_live_p01_run():
    from app.claw_live_events import live_claw_sse

    class HangingAdapter:
        def __init__(self):
            self.cancelled = False
        async def execute(self, run, *, on_event, **kwargs):
            try:
                await on_event(_event(1, OrchestrationEventKind.RUN_STARTED))
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def verify():
        adapter = HangingAdapter()
        response = live_claw_sse(adapter, object(), {})
        iterator = response.body_iterator
        first = await asyncio.wait_for(anext(iterator), timeout=2)
        assert b"event: p01_event" in first
        await asyncio.wait_for(iterator.aclose(), timeout=2)
        await asyncio.sleep(0)
        assert adapter.cancelled

    asyncio.run(verify())
