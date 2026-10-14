"""#3930 opt-in, authenticated, source-grounded Claw P01 live SSE relay.

Called only AFTER the existing signed-session and usage-gate checks in B54.
Never invents a read acknowledgment, stage, tool input or approval authority.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from starlette.responses import StreamingResponse
from kagent.p01_adapter import P01AdapterError, P01DispatchClass
from padiem_ai_core.orchestration_events import OrchestrationEvent

from .claw_general_routes import _MODEL_HOLD_ERROR_CODES, _MODEL_HOLD_USER_MESSAGE
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


def _bounded_engine_failure() -> dict[str, str]:
    return {"code": "engine_execution_failed", "message": "Engine 실행에 실패했습니다."}


def _public_failure(exc: P01AdapterError) -> dict[str, str]:
    # A #3568 model HOLD never reached Engine/B14 and already refunded quota, so
    # it is the general route's bounded `tier_unavailable` product state. The
    # live relay has sent SSE headers and cannot return that 503, so the same
    # public code has to survive here instead of an engine-failure claim.
    if exc.code in _MODEL_HOLD_ERROR_CODES:
        return {"code": "tier_unavailable", "message": _MODEL_HOLD_USER_MESSAGE}
    return _bounded_engine_failure()


def live_claw_sse(
    adapter: Any, run: Any, dispatch_args: dict[str, Any],
    *,
    on_completed: Callable[[str], Awaitable[str | None]] | None = None,
) -> StreamingResponse:
    """Queue backed SSE; upstream gets cancelled if the browser disconnects.

    This branch is strictly opt-in; the normal B54 endpoint is unchanged.
    After SSE headers, runtime failures travel as explicit error events, not
    a fabricated HTTP 200 success/AI answer. Quota compensation keeps the
    existing NOT_DISPATCHED vs dispatched/unknown classification.
    """
    async def events():
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=16)
        seen = 0
        last_sequence = 0
        stream_identity: tuple[str, str, str] | None = None
        seen_event_ids: set[str] = set()
        verified_terminal: dict[str, object] | None = None
        terminal_kinds = {"run_completed", "run_failed", "run_cancelled", "approval_paused"}

        async def report(event: OrchestrationEvent) -> None:
            nonlocal seen, last_sequence, stream_identity, verified_terminal
            seen += 1
            if seen > MAX_RELAY_EVENTS:
                raise ValueError("P01 stream event budget exceeded")
            projected = _event_projection(event)
            sequence = projected["sequence"]
            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence <= last_sequence
            ):
                raise ValueError("P01 stream events are not strictly ordered")
            identity = (
                projected["run_id"], projected["trace_id"], projected["app_id"],
            )
            if stream_identity is None:
                stream_identity = identity
            elif identity != stream_identity:
                # Only one Core run may own the events in a browser SSE reply.
                raise ValueError("P01 stream event identity changed")
            event_id = projected["event_id"]
            if event_id in seen_event_ids:
                raise ValueError("P01 stream event identity replayed")
            if verified_terminal is not None:
                # A duplicated terminal or any stage after termination is
                # inconsistent Core evidence, never successful SSE completion.
                raise ValueError("P01 stream event after verified terminal")
            seen_event_ids.add(event_id)
            last_sequence = sequence
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
                await queue.put(("error", _public_failure(exc)))
            except asyncio.CancelledError:
                _clear_reservation()
                raise
            except Exception:
                _clear_reservation()
                await queue.put(("error", _bounded_engine_failure()))
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
                    # The trusted Core already verified the failed/cancelled
                    # run. Forward its bounded terminal BEFORE the error so
                    # Claw recovery can distinguish failed from cancelled.
                    # A withheld run_completed must never be exposed here.
                    if (verified_terminal is not None
                            and verified_terminal["kind"] in ("run_failed", "run_cancelled")):
                        yield _frame("p01_event", verified_terminal)
                    yield _frame("error", {"error": payload})
                    return
                status = payload.projection.status.value
                if status == "waiting_approval":
                    # This is observed P01 state, not browser approval power.
                    # If the Core emitted no such event, keep error-only.
                    if (verified_terminal is not None
                            and verified_terminal["kind"] == "approval_paused"):
                        yield _frame("p01_event", verified_terminal)
                    yield _frame("error", {"error": {
                        "code": "claw_general_approval_required",
                        "message": "승인이 필요한 요청입니다. Claw 업무 화면에서 진행해 주세요.",
                    }})
                    return
                if status != "completed" or not isinstance(payload.answer, str) or not payload.answer:
                    # A verified failure/cancellation is a real terminal
                    # state even when the final answer is absent. Never turn
                    # an invalid completed answer into a false run_completed.
                    if (verified_terminal is not None
                            and verified_terminal["kind"] in ("run_failed", "run_cancelled")):
                        yield _frame("p01_event", verified_terminal)
                    yield _frame("error", {"error": {
                        "code": "engine_execution_failed", "message": "Engine 실행이 완료되지 않았습니다.",
                    }})
                    return
                if verified_terminal is None or verified_terminal["kind"] != "run_completed":
                    yield _frame("error", {"error": {
                        "code": "engine_execution_failed", "message": "Engine 완료 상태를 확인할 수 없습니다.",
                    }})
                    return
                # One post-completion owner-history projection. The signed
                # route owns the callback; this SSE relay never mints threads
                # or stores a failed/approval-paused result.
                saved_conversation_id = None
                if on_completed is not None:
                    try:
                        saved_conversation_id = await on_completed(payload.answer)
                    except Exception:
                        # A successful P01 execution cannot become a retryable
                        # error solely because the optional D1 history failed.
                        saved_conversation_id = None
                terminal = {"done": True}
                if isinstance(saved_conversation_id, str) and saved_conversation_id:
                    terminal["conversation_id"] = saved_conversation_id
                yield _frame("p01_event", verified_terminal)
                yield _frame("delta", {"delta": payload.answer})
                yield _frame("done", terminal)
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
