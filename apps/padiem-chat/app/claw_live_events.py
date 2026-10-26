"""#3930 opt-in, authenticated, source-grounded Claw P01 live SSE relay.

Called only AFTER the existing signed-session and usage-gate checks in B54.
Never invents a read acknowledgment, stage, tool input or approval authority.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from starlette.responses import StreamingResponse
from kagent.p01_adapter import (
    P01AdapterError,
    P01DispatchClass,
    P01_FAILURE_DETAILS,
    P01_FAILURE_DETAIL_TOOL_STAGES,
)
from padiem_ai_core.orchestration_events import OrchestrationEvent

from .claw_general_routes import _MODEL_HOLD_ERROR_CODES, _MODEL_HOLD_USER_MESSAGE
from .dispatch_quota import _clear_reservation, _refund_active_reservation

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
    failure = _bounded_engine_failure()
    # #5015: parity with the non-live lane — the same closed vocabulary that
    # reaches the 502 body as `detail` rides here as a bounded `detail` too,
    # never raw Engine text.
    if isinstance(exc.failure_detail, str) and (
        exc.failure_detail in P01_FAILURE_DETAILS
        or exc.failure_detail in P01_FAILURE_DETAIL_TOOL_STAGES
    ):
        return {**failure, "detail": exc.failure_detail}
    return failure


def live_claw_sse(
    adapter: Any, run: Any, dispatch_args: dict[str, Any],
    *,
    on_completed: Callable[[str], Awaitable[str | None]] | None = None,
    on_terminal_without_answer: Callable[[str], Awaitable[None]] | None = None,
    sources: tuple[dict[str, str], ...] = (),
) -> StreamingResponse:
    """Queue backed SSE; upstream gets cancelled if the browser disconnects.

    This branch is strictly opt-in; the normal B54 endpoint is unchanged.
    After SSE headers, runtime failures travel as explicit error events, not
    a fabricated HTTP 200 success/AI answer. Quota compensation keeps the
    existing NOT_DISPATCHED vs dispatched/unknown classification.

    ``on_terminal_without_answer(terminal_class)`` fires only on terminals
    that carry no verified answer AND a proven execution verdict:
    ``proven_not_dispatched`` (the Engine never received the turn),
    ``verified_failure`` (Engine itself reported the failure) and
    ``verified_cancelled``. An approval pause, a browser disconnect and any
    completion that could not be verified are NOT execution failures — they
    are never claimed and the staged run stays where its owner can act on it
    (#5015r). A verified completion still belongs to ``on_completed`` alone.
    """
    async def settle_terminal_without_answer(terminal_class: str) -> None:
        if on_terminal_without_answer is None:
            return
        try:
            await on_terminal_without_answer(terminal_class)
        except Exception:
            # Settling history must never break the stream the user reads.
            pass

    async def events():
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=16)
        last_sequence = 0
        stream_identity: tuple[str, str, str] | None = None
        seen_event_ids: set[str] = set()
        verified_terminal: dict[str, object] | None = None
        terminal_kinds = {"run_completed", "run_failed", "run_cancelled", "approval_paused"}

        async def report(event: OrchestrationEvent) -> None:
            nonlocal last_sequence, stream_identity, verified_terminal
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
                # #5015r: NOT_DISPATCHED is a proven never-sent turn; any
                # other adapter failure was observed by the trusted adapter
                # itself. Only these two ever settle a staged run; a genuine
                # unknown stays unclaimed.
                if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
                    terminal_class = "proven_not_dispatched"
                else:
                    terminal_class = "verified_failure"
                # #5015: bounded identifiers only — the adapter code and the
                # reviewed failure detail, never Engine text or attributes.
                print(
                    "claw_live_adapter_failure"
                    f" code={exc.code} detail={exc.failure_detail}"
                    f" dispatch={exc.dispatch_class}",
                    flush=True,
                )
                await queue.put(("error", (_public_failure(exc), terminal_class)))
            except asyncio.CancelledError:
                _clear_reservation()
                raise
            except Exception as exc:
                _clear_reservation()
                # Parity with the non-live lane: a bare failure escape from
                # the trusted adapter is a verified failure, not a strand.
                print(
                    f"claw_live_unhandled_failure type={type(exc).__name__}",
                    flush=True,
                )
                await queue.put(("error", (_bounded_engine_failure(), "verified_failure")))
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
                    terminal_class = payload[1]
                    if (verified_terminal is not None
                            and verified_terminal["kind"] == "run_cancelled"):
                        terminal_class = "verified_cancelled"
                    elif (verified_terminal is not None
                            and verified_terminal["kind"] == "run_failed"):
                        # A Core-verified failure outranks the adapter's own
                        # dispatch classification: the run was really sent.
                        terminal_class = "verified_failure"
                    if (verified_terminal is not None
                            and verified_terminal["kind"] in ("run_failed", "run_cancelled")):
                        yield _frame("p01_event", verified_terminal)
                    await settle_terminal_without_answer(terminal_class)
                    yield _frame("error", {"error": payload[0]})
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
                    # #5015r: an approval pause is not a PC execution failure.
                    # The run keeps its staged state; only the owner consent
                    # surface can move it forward.
                    return
                if status != "completed" or not isinstance(payload.answer, str) or not payload.answer:
                    # A verified failure/cancellation is a real terminal
                    # state even when the final answer is absent. Never turn
                    # an invalid completed answer into a false run_completed.
                    if verified_terminal is not None and verified_terminal["kind"] != "run_completed":
                        yield _frame("p01_event", verified_terminal)
                    if status == "cancelled" or (
                        verified_terminal is not None
                        and verified_terminal["kind"] == "run_cancelled"
                    ):
                        # #5015r: a proven cancellation is not a PC execution
                        # failure; settle it as the cancellation it is.
                        await settle_terminal_without_answer("verified_cancelled")
                    elif status == "failed" or (
                        verified_terminal is not None
                        and verified_terminal["kind"] == "run_failed"
                    ):
                        await settle_terminal_without_answer("verified_failure")
                    # #5015r: any other invalid outcome (e.g. a completed
                    # status with an unusable answer) is unverified evidence,
                    # not a proven failure; it stays unclaimed.
                    yield _frame("error", {"error": {
                        "code": "engine_execution_failed", "message": "Engine 실행이 완료되지 않았습니다.",
                    }})
                    return
                if verified_terminal is None or verified_terminal["kind"] != "run_completed":
                    # #5015r: without a verified terminal this outcome's
                    # verdict is unknown. Never claim a PC execution failure
                    # for uncertainty; leave the staged run with its owner.
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
                if sources:
                    terminal["sources"] = list(sources)
                yield _frame("p01_event", verified_terminal)
                yield _frame("delta", {"delta": payload.answer})
                yield _frame("done", terminal)
                return
        finally:
            # #5015r: a browser disconnect or upstream cancel says nothing
            # about whether the PC command ran. Claiming "failed" here would
            # overwrite a verified completion that raced this cancellation,
            # so an answer-less stream end stays unclaimed; the guarded
            # update_claw_run_status keeps any real completion intact.
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


_PC_PROGRESS_FIELDS = frozenset({"pc_run_id", "dispatch_id", "kind", "stage", "sequence", "elapsed_ms"})
_PC_HEARTBEAT_FIELDS = frozenset({"run_id", "trace_id", "elapsed_ms"})
_PC_PROGRESS_STAGES = ("accepted", "picked_up", "executing", "result")


def project_pc_stream_record(record: Any, *, pc_run_id: str) -> tuple[str, dict]:
    """Closed display projection; no tool args, paths, outputs or authority."""
    import re
    if not isinstance(record, dict) or len(record) != 1:
        raise ValueError("invalid PC display record")
    kind = next(iter(record))
    value = record[kind]
    expected = _PC_PROGRESS_FIELDS if kind == "pc_progress" else _PC_HEARTBEAT_FIELDS
    if kind not in ("pc_progress", "heartbeat") or not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid PC display fields")
    ids = ("pc_run_id", "dispatch_id") if kind == "pc_progress" else ("run_id", "trace_id")
    if any(not isinstance(value[k], str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value[k]) is None for k in ids):
        raise ValueError("invalid PC display identity")
    numbers = ("sequence", "elapsed_ms") if kind == "pc_progress" else ("elapsed_ms",)
    if any(type(value[k]) is not int or value[k] < (1 if k == "sequence" else 0) for k in numbers):
        raise ValueError("invalid PC display sequence")
    if kind == "pc_progress" and (
        value["pc_run_id"] != pc_run_id or value["kind"] not in ("command", "read")
        or value["stage"] not in _PC_PROGRESS_STAGES
    ):
        raise ValueError("PC display correlation failed")
    return kind, dict(value)


def _engine_stream_record_kind(record) -> str:
    if isinstance(record, dict):
        kinds = set(record) & {"event", "pc_progress", "heartbeat", "text_delta", "result", "orchestration", "error"}
        if len(kinds) == 1:
            return next(iter(kinds))
    return "unknown"


def _engine_stream_cause(exc: Exception, record_kind: str) -> dict[str, str]:
    # Class names and a closed record-kind vocabulary only: never exception
    # messages, untrusted keys, payloads, credentials or provider response text.
    current = exc
    seen = set()
    while current.__cause__ is not None and id(current) not in seen:
        seen.add(id(current))
        current = current.__cause__
    kind = getattr(current, "record_kind", record_kind)
    if kind not in {"event", "pc_progress", "heartbeat", "text_delta", "result", "orchestration", "error"}:
        kind = "unknown"
    return {"exception_class": type(current).__name__, "record_kind": kind}


def chat_pc_orchestration_sse(
    stream, *, pc_run_id: str, on_completed, on_scope=None, done_fields=None, on_failed=None,
) -> StreamingResponse:
    """Relay one verified Engine stream; heartbeats are presentation only."""
    from .orchestration_bridge import B62OrchestrationError, _safe_events
    async def settle_failure():
        if on_failed is not None:
            try:
                await on_failed()
            except Exception:
                # Preserve the original terminal error; never expose storage details.
                import logging
                logging.getLogger(__name__).warning("chat_pc_run_settle_unavailable")

    async def events():
        text_seen = False
        pc_seen = False
        scope_sent = False
        progress = {}
        identity = None
        last_sequence = 0
        observed_events = []
        terminal = None
        settled = False
        record_kind = "unknown"
        iterator = aiter(stream)
        try:
            while True:
                # An iterator failure has no current record: do not attribute
                # it to the preceding valid event.
                record_kind = "unknown"
                try:
                    item = await anext(iterator)
                except StopAsyncIteration:
                    break
                record_kind = _engine_stream_record_kind(item)
                if "event" in item:
                    event = _safe_events([item["event"]])[0]
                    current = (event["run_id"], event["trace_id"], event["app_id"])
                    if ((identity is not None and identity != current)
                            or event["sequence"] <= last_sequence or terminal is not None):
                        raise ValueError("Engine lifecycle correlation failed")
                    identity, last_sequence = current, event["sequence"]
                    observed_events.append(event)
                    if event["kind"] in ("run_completed", "run_failed", "run_cancelled", "approval_paused"):
                        terminal = event["kind"]
                    # The final result, not a partial terminal, commits UI truth.
                    continue
                if "pc_progress" in item or "heartbeat" in item:
                    kind, value = project_pc_stream_record(item, pc_run_id=pc_run_id)
                    if kind == "heartbeat":
                        if identity is None or (value["run_id"], value["trace_id"]) != identity[:2]:
                            raise ValueError("Heartbeat correlation failed")
                    else:
                        pc_seen = True
                        prior = progress.get(value["dispatch_id"])
                        stage_index = _PC_PROGRESS_STAGES.index(value["stage"])
                        if (prior is None and stage_index != 0) or (
                            prior is not None and (value["sequence"] <= prior[0] or stage_index <= prior[1])
                        ):
                            raise ValueError("PC progress replay or regression")
                        progress[value["dispatch_id"]] = (value["sequence"], stage_index)
                        if not scope_sent and on_scope is not None:
                            notice = await on_scope()
                            from .history import PC_SCOPE_NOTICE_LABELS
                            if notice in PC_SCOPE_NOTICE_LABELS.values():
                                yield _frame("scope_notice", {"scope_notice": notice})
                                scope_sent = True
                    yield _frame(kind, value)
                    continue
                if "text_delta" in item:
                    value = item["text_delta"]
                    if not isinstance(value, dict) or set(value) != {"delta"} or not isinstance(value["delta"], str):
                        raise ValueError("Invalid text delta")
                    if terminal is not None:
                        raise ValueError("Text after terminal")
                    text_seen = True
                    yield _frame("delta", value)
                    continue
                if set(item) != {"result"} or settled:
                    raise ValueError("Invalid Engine result")
                result = item["result"]
                result_events = result.orchestration.get("events", [])
                if not result_events or result_events != observed_events or terminal != result_events[-1]["kind"]:
                    raise ValueError("Unverified Engine terminal")
                if result.orchestration.get("approval_pause") is not None:
                    yield _frame("orchestration_pause", {"orchestration": dict(result.orchestration)})
                    settled = True
                    return
                if terminal != "run_completed" or not isinstance(result.answer, str) or not result.answer:
                    raise B62OrchestrationError("engine_execution_failed", "Engine 실행이 완료되지 않았습니다.", status_code=502)
                # The final PC answer is additional to a model's pre-tool text;
                # ordinary streamed answers must never be emitted twice.
                if pc_seen or not text_seen:
                    yield _frame("delta", {"delta": result.answer})
                fields = await on_completed(result)
                done = {"done": True, **dict(done_fields or {}), **dict(fields or {})}
                yield _frame("done", done)
                settled = True
            if not settled:
                raise ValueError("Engine stream ended without a result")
        except B62OrchestrationError as exc:
            await settle_failure()
            error = {"code": exc.code, "message": exc.user_message}
            if exc.code == "invalid_engine_stream":
                error["cause"] = _engine_stream_cause(exc, record_kind)
            yield _frame("error", {"error": error})
        except Exception as exc:
            await settle_failure()
            yield _frame("error", {"error": {
                "cause": _engine_stream_cause(exc, record_kind),
                "code": "invalid_engine_stream", "message": "AI 작업 스트림을 확인할 수 없습니다.",
            }})
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                await close()
    return StreamingResponse(events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})
