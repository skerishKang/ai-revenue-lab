"""#3930 opt-in, authenticated, source-grounded Claw P01 live SSE relay.

Called only AFTER the existing signed-session and usage-gate checks in B54.
Never invents a read acknowledgment, stage, tool input or approval authority.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.responses import StreamingResponse
from kagent.p01_adapter import P01AdapterError, P01DispatchClass
from padiem_ai_core import OrchestrationEvent

from .dispatch_quota import _clear_reservation, _refund_active_reservation

MAX_RELAY_EVENTS = 128
_ALLOWED_FIELDS = (
    "event_id", "run_id", "trace_id", "app_id",
    "kind", "sequence", "timestamp_iso",
)


def _frame(name: str, value: dict[str, Any]) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return f"event: {name}\ndata: {payload}\n\n".encode("utf-8")


def _event_projection(event: OrchestrationEvent) -> dict[str, object]:
    # Only the Core-owned validated immutable object is accepted, not raw
    # Engine text, metadata, hidden reasoning, tool args or a user-supplied ID.
    if not isinstance(event, OrchestrationEvent):
        raise ValueError("untrusted P01 event")
    public = event.to_public_dict()
    return {**{key: public[key] for key in _ALLOWED_FIELDS}, "delivery": "live"}


def live_claw_sse(adapter: Any, run: Any, dispatch_args: dict[str, Any]) -> StreamingResponse:
    """Queue backed SSE; upstream gets cancelled if the browser disconnects.

    This branch is strictly opt-in; the normal B54 endpoint is unchanged.
    After SSE headers, runtime failures travel as explicit error events, not
    a fabricated HTTP 200 success/AI answer. Quota compensation keeps the
    existing NOT_DISPATCHED vs dispatched/unknown classification.
    """
    async def events():
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=16)
        seen = 0
        verified_terminal: dict[str, object] | None = None
        terminal_kinds = {"run_completed", "run_failed", "run_cancelled", "approval_paused"}

        async def report(event: OrchestrationEvent) -> None:
            nonlocal seen, verified_terminal
            seen += 1
            if seen > MAX_RELAY_EVENTS:
                raise ValueError("P01 stream event budget exceeded")
            projected = _event_projection(event)
            if projected["kind"] in terminal_kinds:
                # A completed Core run with an unusable public answer must
                # never appear completed in the browser before B54 checks it.
                verified_terminal = projected
                return
            await queue.put(("p01_event", projected))

        async def produce() -> None:
            try:
                outcome = await adapter.execute(run, on_event=report, **dispatch_args)
                await queue.put(("outcome", outcome))
            except P01AdapterError as exc:
                if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
                    await _refund_active_reservation()
                else:
                    _clear_reservation()
                await queue.put(("error", "engine_execution_failed"))
            except asyncio.CancelledError:
                _clear_reservation()
                raise
            except Exception:
                _clear_reservation()
                await queue.put(("error", "engine_execution_failed"))
            finally:
                _clear_reservation()

        task = asyncio.create_task(produce())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "p01_event":
                    yield _frame("p01_event", payload)
                    continue
                if kind == "error":
                    yield _frame("error", {
                        "error": {"code": payload, "message": "Engine 실행에 실패했습니다."}
                    })
                    return
                status = payload.projection.status.value
                if status == "waiting_approval":
                    yield _frame("error", {"error": {
                        "code": "claw_general_approval_required",
                        "message": "승인이 필요한 요청입니다. Claw 업무 화면에서 진행해 주세요.",
                    }})
                    return
                if status != "completed" or not isinstance(payload.answer, str) or not payload.answer:
                    yield _frame("error", {"error": {
                        "code": "engine_execution_failed", "message": "Engine 실행이 완료되지 않았습니다.",
                    }})
                    return
                if verified_terminal is None or verified_terminal["kind"] != "run_completed":
                    yield _frame("error", {"error": {
                        "code": "engine_execution_failed", "message": "Engine 완료 상태를 확인할 수 없습니다.",
                    }})
                    return
                yield _frame("p01_event", verified_terminal)
                yield _frame("delta", {"delta": payload.answer})
                yield _frame("done", {"done": True})
                return
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )
