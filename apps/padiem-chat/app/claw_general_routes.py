"""B54 Claw general composer → canonical P01 Engine lane (#3539).

The generic Claw composer is a first-class B54 product request. This route
reuses the exact #3382 canonical lane the explicit manual execute route already
drives:

    Claw general composer
    → POST /api/claw/general
    → existing claw_p01_adapter (P01CoreOrchestrationAdapter)
    → P01EngineOrchestrationClient
    → P01_ENGINE_SERVICE (Service Binding)
    → Engine
    → B14
    → assistant result

It is deliberately NOT the manual-intake/quote/order flow and NOT the standalone
B62 ``/api/chat`` composer. #4139 intercepts explicit owner PC TXT READ intents
before provider dispatch and uses the existing Broker command/result pipeline. There is NO direct-B14 fallback: an unbound P01 lane
fails closed (503) instead of silently degrading into the standalone B62
``/api/chat/stream`` route, and the canonical USER subject is resolved
SERVER-SIDE from the signed Padiem session before the usage gate and before any
P01/Engine dispatch.

No second Engine service binding, identity authority or entitlement authority is
introduced here; the projection vocabulary is the one ``claw_routes`` already
owns.
"""

from __future__ import annotations

from .file_lane import file_resolver

import asyncio
import inspect
import json
import time
from .native_calendar_intent import parse_native_calendar_intent, latest_user_text as latest_native_calendar_text
from .native_calendar_adapter import execute_native_calendar_plan
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .member_grade_access import claw_execution_tier_denial
from .model_policy import ADMIN_B14_MODEL_ID, resolve_claw_execution_grade
from types import SimpleNamespace
from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    FREE_PRIMARY_B14_MODEL_ID,
    FREE_FALLBACK_B14_MODEL_ID,
)

from kagent.p01_adapter import (
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01DispatchClass,
    P01_FAILURE_DETAIL_CONTRACT,
    P01_FAILURE_DETAIL_UNKNOWN,
    validate_explicit_b14_model_id,
)
from kagent.p01_run_flow import create_claw_run
from .claw_search_decision import (
    build_judgement_digest,
    evidence_agent,
    verdict_from_model,
)

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .byok_client import CustomProviderError, complete_owner_custom
from .byok_credentials import CustomProviderSelectionError
from .drive_general_grounding import DriveGroundingError, drive_general_grounding
from .binary_attachment_frame import decode_binary_attachment_frame
from .claw_attachment_context import (
    CLAW_IMAGE_ATTACHMENT_UNSUPPORTED,
    AttachmentValidationError,
    parse_claw_turn_attachments_async,
)
from .request_contract import BrowserRequestError, parse_custom_selection
from .claw_first_turn_authority import (
    B54VerifiedCodingContextV1,
    FirstTurnAuthorityError,
    claim_first_turn_grant,
    complete_first_turn_grant,
    fail_first_turn_grant,
    reserve_first_turn_grant,
)
from .claw_live_canary import live_stream_allowed
from .claw_general_run_history import project_completed_general_run
from .claw_routes import (
    _NO_STORE_HEADERS,
    _error,
    _safe_composition_diagnostic,
    _safe_engine_failure_detail,
    _usage_gate_denial,
    _resolve_intake_session_reference,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation
from .request_telemetry import emit_stage_event
from .auth_routes import auth_ready, current_user_id
from .history import HISTORY_PREVIEW_SUFFIX, HistoryContextIncomplete, validate_conversation_id, PRODUCT_SCOPE_CHAT

# This is the existing Chat HTTP resource envelope, not a provider/model cap.
# The separate P01 Engine ingress guard remains in force until #4383 is resolved.
# #4379: the Claw request body carries no PADIEM byte total. The reader
# stays incremental.
MAX_CLAW_GENERAL_BODY_BYTES: int | None = None
# Kept importable for older clients; None means no Claw-general pilot text cap.
MAX_CLAW_GENERAL_MESSAGE_CHARS: int | None = None
MAX_CLAW_GENERAL_MESSAGES: int | None = None
# #4379: the owned prior context is not cut to a PADIEM transport envelope.
# The Engine applies its own request contract; nothing is silently truncated.
P01_ENGINE_REQUEST_ENVELOPE_BYTES: int | None = None
CLAW_LIVE_REQUEST_HEADER = "X-Padiem-Claw-Live"
CLAW_LIVE_REQUEST_MARKER = "p01-events-v1"
_CLAW_GENERAL_ROLES = frozenset({"user", "assistant"})
# Same canonical device identity grammar the Broker device directory and the
# saved PC preference expose, including the composed Mesh node identity.


# #5554: bounded per-stage timing for the Claw turn. The route already had a
# whole-request duration, which cannot say which of the (many) serial Engine,
# D1 and provider steps actually held the answer. These stage events use the
# existing request telemetry contract: a fixed stage name, a duration and the
# request id only - never the message, model response, session or file text.
CLAW_STAGE_ROUTE = "claw.route"
CLAW_STAGE_HISTORY = "claw.history"
CLAW_STAGE_SESSION = "claw.b54_session"
CLAW_STAGE_DRIVE = "claw.drive"
CLAW_STAGE_PC_CONTEXT = "claw.pc_context"
CLAW_STAGE_CATALOG = "claw.catalog"
CLAW_STAGE_QUOTA = "claw.quota"
CLAW_STAGE_JUDGEMENT = "claw.search_judgement"
CLAW_STAGE_ANSWER = "claw.answer"
CLAW_STAGE_PERSIST = "claw.persist"


def _claw_stage(stage: str, started: float, *, outcome: str = "ok") -> None:
    """Emit one bounded stage duration; telemetry never fails the turn."""
    try:
        emit_stage_event(
            stage=stage,
            outcome=outcome,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
    except Exception:
        pass


async def _claw_timed(stage: str, awaitable: Any) -> Any:
    """Await one preflight read and record its own duration."""
    started = time.perf_counter()
    try:
        return await awaitable
    finally:
        _claw_stage(stage, started)


async def _no_session_read() -> None:
    """Keep the preflight gather's shape when no identity lane is composed."""
    return None


def _drain_task_result(task: "asyncio.Task[Any]") -> None:
    """Retrieve a background result the turn may never await.

    A turn refused by the PC target checks returns before the roster is
    evaluated. Retrieving the outcome here keeps that bounded metadata read
    from surfacing as an unretrieved task error; it never changes a response.
    """
    if task.cancelled():
        return
    try:
        task.exception()
    except Exception:
        pass


def _start_selectable_model_read(
    request: Any, selected_model_id: str | None, central_route_model_id: str | None
) -> tuple["asyncio.Task[Any] | None", bool]:
    """#5614: start the model-roster read before the PC work context.

    The roster read and the PC work context are independent reads of the same
    signed request, and the roster read used to run strictly after the PC one.
    Starting it first lets the two overlap on the wire.

    Returns ``(task, unavailable)``. ``unavailable`` reproduces the exact 503
    the sequential code returned when the composed catalog authority cannot
    list models at all - the refusal is still raised at its original position
    (after the PC target checks), never earlier.
    """

    if selected_model_id is None and central_route_model_id is None:
        return None, False
    resolver = getattr(
        getattr(getattr(request, "app", None), "state", None),
        "b14_model_choice_resolver",
        None,
    )
    if resolver is None:
        return None, False
    list_fn = getattr(resolver, "list_selectable_models", None)
    if not callable(list_fn):
        return None, True
    try:
        read = _claw_timed(CLAW_STAGE_CATALOG, list_fn())
    except Exception:
        return None, True
    task = asyncio.ensure_future(read)
    task.add_done_callback(_drain_task_result)
    return task, False


def _combine_system_context(*parts: str | None) -> str | None:
    """Join optional trusted context blocks in a fixed order.

    Each part is server-composed; a browser-supplied string never reaches this
    helper. Empty/absent blocks disappear instead of emitting a blank section.
    """
    blocks = [part for part in parts if isinstance(part, str) and part]
    return "\n\n".join(blocks) if blocks else None


# NO_EXECUTABLE_ROUTE product HOLD (#3568/#3566): these adapter codes mean the
# run was refused before any Engine/B14/provider dispatch because the selected
# tier has no executable route yet. They are product states, not engine
# failures, so they must not surface as a generic 502 engine error.
_MODEL_HOLD_ERROR_CODES = frozenset({"tier_hold", "max_tier_hold"})
_MODEL_HOLD_USER_MESSAGE = (
    "선택한 AI 모델을 현재 사용할 수 없습니다. 다른 모델을 선택해 주세요."
)

# #3655 one-shot canary evidence seam. The final Production canary needs the
# existing correlation/route refs projected to the caller, but the normal user
# surface must stay unchanged. Evidence headers are therefore emitted ONLY when
# the request carries the exact opt-in marker below (the owner one-shot harness
# sets it); every value is grammar-checked and omitted when it does not match.
# Values are opaque refs/counts from existing P01/B14 metadata seams — never
# prompts, answers, credentials, or free text.
CLAW_EVIDENCE_REQUEST_HEADER = "X-Padiem-Claw-Evidence"
CLAW_EVIDENCE_MARKER = "one-shot"
_CLAW_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{24}$")
_EVIDENCE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
# B14 reports its selected route as `platform:<provider>/<model>`, so the
# route header keeps the same bounded grammar plus `/`. Rejecting it dropped
# the header for every real B14 route and left the canary without its
# selected-route evidence (#5484).
_CLAW_SELECTED_ROUTE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,79}$")


def _evidence_header(
    name: str,
    value: Any,
    pattern: re.Pattern[str] = _EVIDENCE_VALUE_RE,
) -> tuple[str, str] | None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        return None
    return name, value


def _claw_evidence_response_headers(claw_run_id: str | None, outcome: Any) -> dict[str, str]:
    """Bounded opt-in canary evidence headers (#3655).

    Emitted only in evidence mode. A value that fails its grammar is omitted
    rather than degraded, so the canary can never record a fabricated ref.
    """
    headers: dict[str, str] = {}
    run_pair = _evidence_header("X-Padiem-Claw-Run-Id", claw_run_id, _CLAW_RUN_ID_RE)
    if run_pair is not None:
        headers[run_pair[0]] = run_pair[1]
    if outcome is None:
        return headers
    orch_pair = _evidence_header(
        "X-Padiem-Orchestration-Run-Id", getattr(outcome, "p01_run_id", None)
    )
    if orch_pair is not None:
        headers[orch_pair[0]] = orch_pair[1]
    route_pair = _evidence_header(
        "X-Padiem-Selected-Route-Id",
        getattr(outcome, "selected_route_id", None),
        _CLAW_SELECTED_ROUTE_ID_RE,
    )
    if route_pair is not None:
        headers[route_pair[0]] = route_pair[1]
    attempts = getattr(outcome, "provider_attempt_count", None)
    if isinstance(attempts, int) and not isinstance(attempts, bool) and 0 <= attempts <= 99:
        headers["X-Padiem-Provider-Attempts"] = str(attempts)
    fallback_used = getattr(outcome, "fallback_used", None)
    if isinstance(fallback_used, bool):
        headers["X-Padiem-Fallback-Used"] = "true" if fallback_used else "false"
    return headers


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _claw_general_sse(
    answer: str,
    evidence_headers: dict[str, str] | None = None,
    *,
    history: tuple[dict[str, object], ...] = (),
    conversation_id: str | None = None,
    sources: tuple[dict[str, str], ...] = (),
    pending_run_id: str | None = None,
) -> Response:
    """Bounded terminal SSE, optionally preceded by real *post-execution* history.

    The current Engine client is synchronous: all P01 events are only available
    AFTER the run. Never misrepresent this event history as live progress.
    Legacy clients still see their canonical delta + done frames unchanged.
    """
    headers = {"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"}
    if evidence_headers:
        headers.update(evidence_headers)
    frames = b""
    if isinstance(history, tuple) and len(history) <= 128:
        # Fixed public fields only: no free-form message/metadata/tool input.
        keys = ("event_id", "run_id", "trace_id", "app_id", "kind", "sequence", "timestamp_iso")
        for event in history:
            if not isinstance(event, dict) or any(key not in event for key in keys):
                frames = b""  # fail closed on malformed provider/history data
                break
            frames += _sse_frame("p01_event", {
                **{key: event[key] for key in keys}, "delivery": "post_execution",
            })
    terminal = {"done": True}
    if pending_run_id is not None:
        terminal.update({"pc_pending": True, "run_id": pending_run_id})
    if conversation_id is not None:
        terminal["conversation_id"] = conversation_id
    if sources:
        terminal["sources"] = list(sources)
    frames += _sse_frame("delta", {"delta": answer}) + _sse_frame("done", terminal)
    return Response(
        frames,
        status_code=200,
        media_type="text/event-stream",
        headers=headers,
    )


def _claw_general_user_text(data: dict[str, Any]) -> tuple[str | None, JSONResponse | None]:
    """Validate shared chat messages and preserve latest user text verbatim.

    P01 model-only Claw receives the latest user turn, not the browser-provided
    previous turns. Malformed shapes fail before quota or provider dispatch.
    """
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return None, _error(400, "invalid_messages", "메시지를 입력해 주세요.")
    last_user: str | None = None
    for item in messages:
        if not isinstance(item, dict):
            return None, _error(400, "invalid_messages", "메시지 형식이 올바르지 않습니다.")
        role = item.get("role")
        content = item.get("content")
        if role not in _CLAW_GENERAL_ROLES or not isinstance(content, str):
            return None, _error(400, "invalid_messages", "메시지 형식이 올바르지 않습니다.")
        if role == "user":
            last_user = content
    text = (last_user or "").strip()
    if not text:
        return None, _error(400, "invalid_messages", "메시지를 입력해 주세요.")
    return text, None


async def _owner_claw_context(
    request: Request, conversation_id: str | None, latest: str,
) -> str:
    """Bounded history from the SAME signed owner; no browser-provided prior turns."""
    # The existing model transcript stays byte-for-byte unchanged. Keep the
    # original roles separately at the trusted read boundary for the PC guard;
    # never reconstruct user authority from that flattened transcript.
    action_context = [{"role": "user", "content": latest}]
    state = getattr(request, "state", None)
    if state is not None:
        state.claw_pc_action_context = action_context
    if conversation_id is None:
        return latest
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    if not uid or not callable(getattr(store, "get_conversation", None)):
        raise ValueError("owner history unavailable")
    get_full = getattr(store, "get_conversation_model_context", None)
    load = get_full if callable(get_full) else store.get_conversation
    prior = load(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
    if inspect.isawaitable(prior):
        prior = await prior
    if not isinstance(prior, dict) or prior.get("id") != conversation_id:
        raise ValueError("owner history changed")
    messages = prior.get("messages")
    if not isinstance(messages, list):
        return latest  # Empty Hark work conversations are valid.
    # This list comes from verified owner-scoped *saved previews*, not browser
    # supplied turns. Do not silently drop a fixed number of prior turns or
    # truncate the model user text to a pilot-size character window.
    excerpts: list[str] = []
    for row in messages:
        if not isinstance(row, dict) or row.get("role") not in ("user", "assistant"):
            continue
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if len(content) == 8000 and content.endswith(HISTORY_PREVIEW_SUFFIX):
            # Legacy/partial history cannot become silently incomplete AI context.
            raise HistoryContextIncomplete("full owner conversation history not available")
        item = ("사용자: " if row["role"] == "user" else "AI: ") + content.strip()
        excerpts.append(item)
        action_context.insert(-1, {"role": row["role"], "content": content.strip()})
    if not excerpts:
        return latest
    return (
        "동일 소유자의 이전 대화 (참고 문맥만 제공하며 도구 권한은 부여하지 않음):\n"
        + "\n".join(excerpts) + "\n\n현재 사용자 요청:\n" + latest
    )


def _accepts_assistant_message_id(append: Any) -> bool:
    """Whether a store's append_exchange accepts the run-scoped answer id.

    A store that predates the correlation keeps its existing contract: the
    exchange is still stored, and the run simply stays uncorrelated (so the
    owner-scoped lookup reports it as unavailable instead of guessing).
    """
    try:
        parameters = inspect.signature(append).parameters
    except (TypeError, ValueError):
        return False
    if "assistant_message_id" in parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


async def _save_claw_exchange(
    request: Request, *, conversation_id: str | None, user_text: str,
    answer: str, assistant_message_id: str | None = None,
) -> str | None:
    """Exact completed exchange only; unavailable history does not replay P01."""
    if (not isinstance(answer, str) or not answer.strip()
            or not isinstance(user_text, str) or not user_text.strip()):
        return None
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    append = getattr(store, "append_exchange", None)
    if not uid or not callable(append):
        return None
    try:
        project_id = None
        if conversation_id is not None:
            get = getattr(store, "get_conversation", None)
            if not callable(get):
                return None
            owned = get(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
            if inspect.isawaitable(owned):
                owned = await owned
            if not isinstance(owned, dict) or owned.get("id") != conversation_id:
                return None
            project_id = owned.get("project_id")
            if project_id is not None and not isinstance(project_id, str):
                return None
        # Only the bounded, visibly labeled stored preview is persisted. The
        # complete P01 result was already delivered to the caller unchanged.
        # #5015: the run-scoped answer id is passed only to a store that
        # supports it, so a store without that correlation keeps its existing
        # contract instead of losing the whole exchange.
        if assistant_message_id is not None and _accepts_assistant_message_id(append):
            saved = append(
                uid, conversation_id, user_text, answer, project_id,
                product_scope=PRODUCT_SCOPE_CHAT,
                assistant_message_id=assistant_message_id,
            )
        else:
            saved = append(uid, conversation_id, user_text, answer, project_id, product_scope=PRODUCT_SCOPE_CHAT)
        if inspect.isawaitable(saved):
            saved = await saved
        if not isinstance(saved, str):
            return None
        return saved if validate_conversation_id(saved) is not None else None
    except Exception:
        return None


async def _append_staged_claw_answer(
    request: Request, *, run_id: str, conversation_id: str, answer: str,
    message_id: str | None = None,
) -> bool:
    """Append only the verified answer to an already-staged owner run.

    The owner turn was persisted before Engine dispatch, so the completion
    step owns the assistant message alone. ``append_local_task_result`` keeps
    the exactly-once and terminal-immutability guards of the existing store.
    """
    if not isinstance(answer, str) or not answer.strip():
        return False
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    append = getattr(store, "append_local_task_result", None)
    if not uid or not callable(append):
        return False
    from .claw_local_task_result_projection import result_message_id
    try:
        # #5015: a model-only run stores its verified answer under the
        # run-scoped id, so the owner-scoped lookup can correlate the stored
        # completion record with the actual message. A staged run that carries
        # a dispatch correlation keeps the projection identity instead.
        resolved_id = message_id or result_message_id(
            conversation_id=conversation_id, command_id=run_id,
            revision_ref="general_answer",
        )
        appended = append(
            user_id=uid, run_id=run_id,
            message_id=resolved_id,
            summary=answer, content=answer, status="completed",
        )
        if inspect.isawaitable(appended):
            appended = await appended
        return bool(appended)
    except Exception:
        return False


async def _settle_staged_run_status(request: Request, run_id: str, status: str) -> None:
    """Best-effort truthful single-row settle for a staged run (#5015r).

    ``update_claw_run_status`` is an atomic guarded write, so an already
    completed run and an existing result summary are never overwritten.
    """
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    mark = getattr(store, "update_claw_run_status", None)
    if not isinstance(uid, str) or not uid or not callable(mark):
        return
    try:
        result = mark(uid, run_id, status)
        if inspect.isawaitable(result):
            await result
    except Exception:
        pass


async def _mark_staged_run_failed(request: Request, run_id: str) -> None:
    """Best-effort truthful terminal state for a staged run with no answer."""
    await _settle_staged_run_status(request, run_id, "failed")


async def _record_completed_claw_result(
    request: Request, *, run_id: str, conversation_id: str | None,
    user_text: str, answer: str, authorized_workspace_id: str | None,
    first_turn_grant: B54VerifiedCodingContextV1 | None = None,
    staged_conversation_id: str | None = None,
) -> str | None:
    """Persist only a verified completed Claw result; never replay Engine.

    Conversation saving and completed-run history are both optional read-model
    projections. Failure to save must not conceal an already-completed answer
    or advertise a server conversation ID that was not actually stored.

    A #4139 desktop run is staged before dispatch, so its verified answer is
    appended to that same conversation instead of re-inserting the user turn.
    """
    saved_conversation_id: str | None
    staged_answer_saved = True
    # #5015: the verified answer of a model-only run is stored under the
    # run-scoped message id, so the owner-scoped lookup can compare the stored
    # completion record with the actual assistant message of this run.
    from .history import general_answer_message_id
    try:
        answer_message_id = general_answer_message_id(run_id)
    except Exception:
        answer_message_id = None
    if staged_conversation_id is not None:
        saved_conversation_id = staged_conversation_id
        staged_answer_saved = await _append_staged_claw_answer(
            request, run_id=run_id, conversation_id=staged_conversation_id,
            answer=answer, message_id=answer_message_id,
        )
    else:
        saved_conversation_id = await _save_claw_exchange(
            request, conversation_id=conversation_id,
            user_text=user_text, answer=answer,
            assistant_message_id=answer_message_id,
        )
    # #3933 S1: link the reserved first-turn grant to its verified outcome.
    # Best-effort provenance only: a grant-store failure must never conceal
    # an already-completed answer.
    await complete_first_turn_grant(
        request, first_turn_grant, run_ref=run_id,
        saved_conversation_id=saved_conversation_id,
    )
    if staged_conversation_id is not None:
        if not staged_answer_saved:
            # The answer reached the caller, but its run must not stay pending.
            await _mark_staged_run_failed(request, run_id)
        return staged_conversation_id
    projected_conversation_id = saved_conversation_id or conversation_id
    if projected_conversation_id is None:
        await project_completed_general_run(
            request, run_id=run_id, user_text=user_text, answer=answer,
        )
    else:
        await project_completed_general_run(
            request, run_id=run_id, user_text=user_text, answer=answer,
            conversation_id=projected_conversation_id,
            workspace_id=authorized_workspace_id,
        )
    return saved_conversation_id


async def claw_general_capabilities(request: Request) -> JSONResponse:
    """Read-only session-specific SSE capability and opt-in pre-dispatch diagnostic.

    The normal browser GET keeps its existing one-field response and does not
    trigger an extra Control Plane lookup when live SSE is disabled. Diagnostic
    mode checks ONLY signed auth, P01 adapter presence, and current canonical
    B54 session: never quota, entitlement, Engine, B14 or Provider.
    """
    from .auth_routes import auth_ready, current_user_id

    adapter = getattr(request.app.state, "claw_p01_adapter", None)
    runner = getattr(adapter, "_runner", None)
    signed_in = bool(auth_ready(request) and current_user_id(request) is not None)
    subject_lane = (
        adapter is not None
        and getattr(adapter, "subject_identity_lane", False) is True
    )
    diagnostic = request.query_params.get("diagnostic") == "pre_dispatch_v1"
    live_candidate = bool(
        signed_in
        and getattr(request.app.state, "claw_live_sse_enabled", False) is True
        and callable(getattr(runner, "run_stream", None))
        and subject_lane
    )

    # One read-only CP session lookup maximum per GET. Normal callers with
    # live SSE disabled do not incur an additional identity roundtrip.
    session = None
    if signed_in and subject_lane and (live_candidate or diagnostic):
        from .b54_canonical_session import resolve_current_b54_canonical_session

        try:
            session = await resolve_current_b54_canonical_session(request)
        except Exception:
            # Read-only diagnostics never disclose Control Plane failures.
            session = None

    enabled = bool(
        live_candidate
        and session is not None
        and live_stream_allowed(
            request.app.state, session.auth_session.subject.subject_id
        )
    )
    result: dict[str, object] = {"live_events_available": enabled}
    if diagnostic:
        # Fixed codes only. No owner, tenant, subject, session, quota, model,
        # credential, request body or raw Control Plane exception is returned.
        if not signed_in:
            state = "authentication_required"
        elif adapter is None:
            state = "p01_adapter_unavailable"
        elif not subject_lane:
            state = "canonical_subject_lane_unverified"
        elif session is None:
            state = "canonical_b54_session_unavailable"
        else:
            state = "pre_quota_ready"
        result["pre_dispatch_status"] = state
        result["pre_dispatch_scope"] = "auth_adapter_session_only"
    return JSONResponse(result, headers=_NO_STORE_HEADERS)


CLAW_PUBLIC_SEARCH_STATE_FLAG = "claw_web_search_enabled"
MAX_CLAW_SEARCH_SOURCES = 5
MAX_CLAW_SEARCH_SOURCE_TITLE_CHARS = 200
CLAW_GROUNDING_PREAMBLE_MARKER = "웹 근거 사용 규칙"



def _project_search_sources(raw: Any) -> tuple[dict[str, str], ...] | None:
    """Verified provenance only: https URL, title and retrieval timestamp."""

    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    projected: list[dict[str, str]] = []
    for item in raw[:MAX_CLAW_SEARCH_SOURCES]:
        if not isinstance(item, dict):
            return None
        url = item.get("url")
        title = item.get("title")
        retrieved_at = item.get("retrieved_at")
        if not isinstance(url, str) or not url.startswith("https://"):
            return None
        if not isinstance(title, str) or not isinstance(retrieved_at, str):
            return None
        projected.append({
            "url": url[:2048],
            "title": title[:MAX_CLAW_SEARCH_SOURCE_TITLE_CHARS],
            "retrieved_at": retrieved_at[:64],
        })
    return tuple(projected)


async def _claw_public_search_grounding(
    request: Request, adapter: Any, messages: Any, *, model_id: str | None = None
) -> tuple[str | None, tuple[dict[str, str], ...]]:
    """Let the model decide, then reuse the existing Engine evidence operation once.

    The conversation digest stays inside Padiem. Only a query that survives this lane's
    own privacy and length checks may reach a provider, and grounding plus provenance
    stand or fall together. Any refusal degrades to the pre-search answer surface.
    """

    denied = (None, ())
    if getattr(request.app.state, CLAW_PUBLIC_SEARCH_STATE_FLAG, False) is not True:
        return denied
    client = getattr(getattr(adapter, "_runner", None), "_client", None)
    judge = getattr(client, "search_judgement", None)
    search_evidence = getattr(client, "search_evidence", None)
    if not callable(judge) or not callable(search_evidence):
        return denied
    digest = build_judgement_digest(messages)
    if digest is None:
        return denied
    if not isinstance(model_id, str) or not model_id.strip():
        return denied
    agent = evidence_agent(model_id)
    try:
        verdict = verdict_from_model(await judge(conversation=digest, agent=agent))
    except Exception:
        return denied
    if not verdict.should_search:
        return denied
    try:
        evidence = await search_evidence(query=verdict.query, agent=agent)
    except Exception:
        return denied
    if not isinstance(evidence, dict):
        return denied
    sources = _project_search_sources(evidence.get("sources"))
    context = evidence.get("grounding_context")
    if sources is None:
        # Provenance that cannot be shown means the claim cannot be made either.
        return denied
    if not isinstance(context, str) or not context.strip() or len(context) > 32_768:
        return denied
    if CLAW_GROUNDING_PREAMBLE_MARKER not in context:
        # Without Core's untrusted-data preamble the text would enter the prompt as
        # ordinary context, which is exactly the promotion this route forbids.
        return denied
    return context, sources


def _requested_local_txt_path(user_text: str) -> tuple[bool, str | None]:
    """Narrow first-party PC TXT read intent: no model or browser-made grant."""
    compact = "".join(user_text.lower().split())
    if not any(marker in compact for marker in (
        "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "mypc", "mycomputer",
    )):
        return False, None
    if not re.search("읽어|보여|열어|확인해|read|open|show", user_text, re.I):
        return False, None
    if ".txt" not in user_text.lower():
        return False, None
    matches = []
    for word in user_text.split():
        token = word.strip(".,!?()[]'\\\"“”‘’")
        for particle in ("에서", "를", "을", "은", "도", "이"):
            if token.lower().endswith(".txt" + particle):
                token = token[:-len(particle)]
                break
        if token.lower().endswith(".txt"):
            matches.append(token)
    return True, matches[0] if len(matches) == 1 else None


_COMMAND_PC_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)
#: Imperative forms only: a description of a command must not execute it.
_COMMAND_VERBS = ("실행해", "실행하", "run ", "execute ")
#: #4139: a command is ordinary text — Korean, quotes, tabs and several lines
#: are allowed, and there is no product length rule. The former 512-character
#: and then 8,192-character caps were trial limits that rejected normal work, so
#: the size of a command is bounded by the transport it arrives on
#: (MAX_CLAW_GENERAL_BODY_BYTES) and by the row it is stored in, both checked at
#: their own boundary. Here only the characters that break the lane are refused:
#: NUL and CR (neither survives the exec/transcript path) and the other C0
#: controls and DEL.
_COMMAND_BODY = re.compile(r"[^\x00-\x08\x0b-\x1f\x7f]+")


def _requested_local_command(user_text: str) -> tuple[bool, str | None]:
    """Explicit, delimited terminal command for the verified owner PC.

    #4139 terminal lane. The command must be BOTH named as a PC action and
    written in exactly one backtick span, so ordinary prose ("내 PC에서 실행
    계획을 알려줘") never becomes a remote execution. Anything ambiguous is not
    this lane and falls through to the model.
    """
    if not isinstance(user_text, str) or not user_text:
        return False, None
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _COMMAND_PC_MARKERS):
        return False, None
    if not any(verb in lowered for verb in _COMMAND_VERBS):
        return False, None
    # A delimited command may span several lines; only a backtick, NUL or CR
    # ends the span, so a multi-line script is ordinary input. The span itself
    # carries no length rule — the request envelope bounds it.
    matches = re.findall(r"`([^`\x00\r]*)`", user_text)
    if len(matches) != 1:
        return False, None
    command = matches[0].strip()
    if _COMMAND_BODY.fullmatch(command) is None:
        return False, None
    return True, command


#: #4139: a natural-language PC query needs no backtick. The user asks about
#: their verified PC in prose ("내 PC에 데이터베이스가 있나?") and Claw runs a
#: bounded inventory command on that PC instead of answering from model memory.
#: Conservative: only clear PC-state questions with a recognizable subject map
#: to a command; everything else falls through to the model.
_NATURAL_PC_QUERY_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)
_NATURAL_PC_QUERY_NOUNS = (
    "데이터베이스", "db", "파일", "폴더", "디렉터리", "프로그램", "서비스",
    "프로세스", "호스트", "hostname", "정보", "상태", "인벤토리",
    "드라이브", "디스크", "drive", "disk",
)
_NATURAL_PC_QUERY_VERBS = (
    "있", "뭐", "무엇", "확인", "조회", "목록", "리스트", "검색", "찾",
    "보여", "알려", "인벤토리", "어떻",
)


def _natural_pc_query_command(user_text: str) -> str | None:
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if any(marker in compact for marker in ("데이터베이스", "db")):
        return (
            "Get-ChildItem -Path C:\\ -Recurse -Include *.db,*.sqlite,*.sqlite3,"
            "*.mdf,*.ldb -ErrorAction SilentlyContinue | Select-Object -First 50 "
            "| ForEach-Object { $_.FullName }"
        )
    if any(marker in compact for marker in ("드라이브", "디스크", "drive", "disk")):
        # Cmdlet-only: no native exit is observed, so the lane records the
        # honest no_exit_code termination. The drive list itself is carried
        # as JSON in the transcript.
        return (
            "Get-PSDrive -PSProvider FileSystem | "
            "Select-Object Name,Root,Used,Free | ConvertTo-Json"
        )
    if "hostname" in lowered or "호스트" in lowered:
        return "hostname.exe"
    return None


def _requested_natural_pc_query(user_text: str) -> tuple[bool, str | None]:
    """Natural-language PC state query for the verified owner PC.

    #4139. No backtick is required: a clear question about the verified PC's
    state ("내 PC에 데이터베이스가 있나?") becomes one bounded command on that
    PC. Ambiguous prose falls through to the model, so ordinary chat never
    becomes remote execution.
    """
    if not isinstance(user_text, str) or not user_text:
        return False, None
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _NATURAL_PC_QUERY_MARKERS):
        return False, None
    if not any(noun in lowered for noun in _NATURAL_PC_QUERY_NOUNS):
        return False, None
    if not any(verb in lowered for verb in _NATURAL_PC_QUERY_VERBS):
        return False, None
    # A backtick command is the explicit lane; do not double-handle it.
    if "`" in user_text:
        return False, None
    command = _natural_pc_query_command(user_text)
    if command is None:
        return False, None
    return True, command


_PC_FILE_NOUNS = ("파일", "폴더", "디렉터리", "디렉토리", "txt", "문서")
_PC_FILE_VERBS = ("목록", "리스트", "보여", "읽", "내용", "설명", "찾", "열어")


def _requested_natural_pc_files(user_text: str) -> bool:
    """Natural-language PC folder/file task for the model's file tools.

    This only selects the model-driven PC file plan; the model chooses the
    folder/file arguments from the verified context and uses the actual tool
    results. A surface drive question stays on the drive lane, and a backtick
    command stays on the explicit terminal lane.
    """
    if not isinstance(user_text, str) or not user_text:
        return False
    if "`" in user_text:
        return False
    # An explicit named .txt path keeps the existing single-file TXT lane
    # (which resolves the deployment-mapped file); the model file plan is for
    # folder listing + a file chosen from the actual listing.
    if _requested_local_txt_path(user_text)[0]:
        return False
    compact = "".join(user_text.lower().split())
    if not any(marker in compact for marker in _NATURAL_PC_QUERY_MARKERS):
        return False
    lowered = user_text.lower()
    if not any(noun in lowered for noun in _PC_FILE_NOUNS):
        return False
    if not any(verb in lowered for verb in _PC_FILE_VERBS):
        return False
    if any(noun in lowered for noun in ("드라이브", "디스크", "drive", "disk")):
        return False
    return True


_DESKTOP_PC_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)
#: Desktop verbs only: a description of the screen must not operate it.
_DESKTOP_VERBS = (
    "캡처", "스크린샷", "화면", "클릭", "입력", "타이핑",
    "키보드", "마우스", "메모장", "눌러", "보여",
)


def _requested_local_desktop(user_text: str) -> tuple[bool, str | None]:
    """Explicit, delimited desktop op for the verified owner PC.

    #4139 desktop lane. The turn must be BOTH named as a PC desktop action
    and written in exactly one backtick span holding one op
    (``capture`` | ``type:<text>`` | ``keys:<combo>`` | ``click:<x>,<y>``),
    so ordinary prose never becomes remote input. Anything ambiguous is not
    this lane and falls through to the model. The span is converted to the
    canonical ``desktop:<op>`` dispatch body and validated with the same
    grammar the executor enforces.
    """
    if not isinstance(user_text, str) or not user_text:
        return False, None
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _DESKTOP_PC_MARKERS):
        return False, None
    if not any(verb in lowered for verb in _DESKTOP_VERBS):
        return False, None
    matches = re.findall(r"`([^`\x00\r]*)`", user_text)
    if len(matches) != 1:
        return False, None
    span = matches[0].strip()
    head, sep, tail = span.partition(":")
    op = head.strip().lower()
    if op == "capture":
        canonical = "desktop:capture" if not sep else None
    elif op in ("type", "keys", "click"):
        canonical = "desktop:" + op + "\n" + tail.strip(" \t\n") if sep else None
    else:
        canonical = None
    if canonical is None:
        return False, None
    from .oracle_mesh_read_return_routes import _parse_desktop_op_text
    if _parse_desktop_op_text(canonical) is None:
        return False, None
    return True, canonical


async def _dispatch_user_desktop_request(
    request: Request, *, user_text: str, desktop_op: str, data: dict[str, Any],
) -> JSONResponse | Response:
    """Claw composer -> one desktop dispatch on the pinned PC.

    The run row is staged first so the result has a conversation to land in;
    the dispatch itself re-verifies the owner session, the canonical account
    and the deployment's command grant (a desktop input drives the PC, so
    the TXT read grant is never enough).
    """
    from .claw_memory_routes import _resolve_memory_workspace
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_desktop_intent

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "command_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "command_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=user_text, conversation_id=conversation_id,
        )
    except Exception:
        return _error(503, "command_history_unavailable", "대화 저장에 실패했습니다.")
    selected = data.get("device_id")
    dispatched = await dispatch_oracle_mesh_desktop_intent(
        request,
        desktop_op=desktop_op,
        wire={
            "run_id": run.run_id,
            "device_id": selected if isinstance(selected, str) and selected else None,
            "confirmed": True,  # derived from this authenticated user's own text
        },
    )
    if dispatched.status_code != 200:
        mark_failed = getattr(history, "update_claw_run_status", None)
        if callable(mark_failed):
            try:
                await mark_failed(uid, run.run_id, "failed")
            except Exception:
                pass
        return dispatched
    return _claw_general_sse(
        "COM1 데스크톱을 조작하는 중입니다. 실제 화면·결과는 작업 완료 후 이 대화에 표시됩니다.",
        conversation_id=cid, pending_run_id=run.run_id,
    )


async def _dispatch_user_command_request(
    request: Request, *, user_text: str, command: str, data: dict[str, Any],
) -> JSONResponse | Response:
    """Claw composer -> one terminal dispatch on the pinned PC.

    The run row is staged first so the result has a conversation to land in;
    the dispatch itself re-verifies the owner session, the canonical account
    and the deployment's separate command grant.
    """
    from .claw_memory_routes import _resolve_memory_workspace
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "command_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "command_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=user_text, conversation_id=conversation_id,
        )
    except Exception:
        return _error(503, "command_history_unavailable", "대화 저장에 실패했습니다.")
    selected = data.get("device_id")
    dispatched = await dispatch_oracle_mesh_command_intent(
        request,
        command=command,
        wire={
            "run_id": run.run_id,
            "device_id": selected if isinstance(selected, str) and selected else None,
            "confirmed": True,  # derived from this authenticated user's own text
        },
    )
    if dispatched.status_code != 200:
        mark_failed = getattr(history, "update_claw_run_status", None)
        if callable(mark_failed):
            try:
                await mark_failed(uid, run.run_id, "failed")
            except Exception:
                pass
        return dispatched
    return _claw_general_sse(
        "COM1에서 명령을 실행하는 중입니다. 실제 출력은 작업 완료 후 이 대화에 표시됩니다.",
        conversation_id=cid, pending_run_id=run.run_id,
    )


async def _settle_claw_run_failed(history: Any, uid: str, run_id: str) -> None:
    """Give a staged run a terminal state so it can never strand as ``pending``.

    Without this, a dispatch step that raises leaves the run row at ``pending``
    with no dispatch row and no answer, so the composer keeps showing the
    previous turn and the request silently never completes.
    """
    mark_failed = getattr(history, "update_claw_run_status", None)
    if callable(mark_failed):
        try:
            await mark_failed(uid, run_id, "failed")
        except Exception:
            pass


async def _dispatch_user_txt_request(
    request: Request, *, user_text: str, path_relative: str,
    data: dict[str, Any],
) -> JSONResponse | Response:
    """Claw's existing composer → existing Broker enqueue, with owned run."""
    from .claw_memory_routes import _resolve_memory_workspace
    from .connector_txt_read_routes import (
        choose_verified_txt_device, dispatch_verified_txt_read,
    )

    conversation_id, denial = await _resolve_intake_session_reference(request, data)
    if denial is not None:
        return denial
    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required", "로그인이 필요합니다.")
    selected = data.get("device_id")
    if selected is not None and (not isinstance(selected, str) or not selected):
        return _error(422, "txt_read_device_invalid", "선택한 PC를 확인할 수 없습니다.")

    # #4139: an ordinary TXT request may execute on the management host over
    # the verified Mesh ownership map. That decision is made BEFORE the native
    # device directory lookup, so a PC without a native binding is not filtered
    # out first; the native lane below is unchanged for everything else.
    from .oracle_mesh_read_return_routes import (
        dispatch_oracle_mesh_read_intent, resolve_oracle_mesh_execution,
    )
    mesh_target, mesh_error = await resolve_oracle_mesh_execution(
        request, path_relative=path_relative, selected_device_id=selected,
    )
    if mesh_error is not None:
        return mesh_error
    if mesh_target is not None:
        try:
            workspace = await _resolve_memory_workspace(request, uid)
        except Exception:
            workspace = None
        if not isinstance(workspace, str) or not workspace:
            return _error(503, "txt_read_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
        history = getattr(request.app.state, "history_store", None)
        stage = getattr(history, "record_txt_pending_run", None)
        if not callable(stage):
            return _error(503, "txt_read_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
        run = create_claw_run("padiem-chat", user_text, model_only_text=True)
        try:
            cid = await stage(
                user_id=uid, run_id=run.run_id, workspace_id=workspace,
                user_text=user_text, conversation_id=conversation_id,
            )
        except Exception:
            return _error(503, "txt_read_history_unavailable", "대화 저장에 실패했습니다.")
        try:
            staged = await dispatch_oracle_mesh_read_intent(request, {
                "device_id": mesh_target["device_id"],
                "run_id": run.run_id,
                "root_ref": mesh_target["root_ref"],
                "path_relative": mesh_target["path_relative"],
                "confirmed": True,  # derived from this authenticated user's READ text
            })
        except Exception:
            await _settle_claw_run_failed(history, uid, run.run_id)
            return _error(503, "txt_read_dispatch_unavailable",
                          "PC 작업 요청을 보내지 못했습니다.")
        if staged.status_code != 200:
            await _settle_claw_run_failed(history, uid, run.run_id)
            return staged
        return _claw_general_sse(
            "PC의 TXT 파일을 읽는 중입니다. 실제 파일 내용은 작업 완료 후 이 대화에 표시됩니다.",
            conversation_id=cid, pending_run_id=run.run_id,
        )

    device_id, error = await choose_verified_txt_device(
        request, selected_device_id=selected,
    )
    if error is not None:
        return error
    try:
        workspace = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not isinstance(workspace, str) or not workspace:
        return _error(503, "txt_read_workspace_unavailable", "대화 범위를 확인할 수 없습니다.")
    history = getattr(request.app.state, "history_store", None)
    stage = getattr(history, "record_txt_pending_run", None)
    if not callable(stage):
        return _error(503, "txt_read_history_unavailable", "대화 저장소를 확인할 수 없습니다.")
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    try:
        cid = await stage(
            user_id=uid, run_id=run.run_id, workspace_id=workspace,
            user_text=user_text, conversation_id=conversation_id,
        )
    except Exception:
        return _error(503, "txt_read_history_unavailable", "대화 저장에 실패했습니다.")
    try:
        dispatched = await dispatch_verified_txt_read(request, {
            "device_id": device_id, "root_ref": "root.3140",
            "path_relative": path_relative, "run_id": run.run_id,
            "confirmed": True,  # derived from this authenticated user's actual READ text
        })
    except Exception:
        await _settle_claw_run_failed(history, uid, run.run_id)
        return _error(503, "txt_read_dispatch_unavailable",
                      "PC 작업 요청을 보내지 못했습니다.")
    if dispatched.status_code != 200:
        await _settle_claw_run_failed(history, uid, run.run_id)
        return dispatched
    # Only a wait response is emitted. The *verified* PC body is appended
    # asynchronously on existing run-history/local-result reconciliation.
    return _claw_general_sse(
        "PC의 TXT 파일을 읽는 중입니다. 실제 파일 내용은 작업 완료 후 이 대화에 표시됩니다.",
        conversation_id=cid, pending_run_id=run.run_id,
    )


async def _claw_custom_direct(
    request: Request,
    *,
    uid: str,
    custom: Any,
    data: dict[str, Any],
    user_text: str,
) -> JSONResponse | Response:
    """One owner-key text turn without Engine, B14, quota or tool dispatch."""
    conversation_id, conversation_error = await _resolve_intake_session_reference(
        request, data,
    )
    if conversation_error is not None:
        return conversation_error
    try:
        model_user_text = await _owner_claw_context(request, conversation_id, user_text)
    except HistoryContextIncomplete:
        return _error(
            409,
            "conversation_context_incomplete",
            "이전 대화 원문을 복원할 수 없습니다. 새 대화를 시작하거나 원문을 다시 입력해 주세요.",
        )
    except Exception:
        return _error(
            503,
            "conversation_authority_unavailable",
            "대화 문맥을 안전하게 확인할 수 없습니다.",
        )
    try:
        result = await complete_owner_custom(
            request.app.state,
            uid=uid,
            selection=custom,
            messages=[{"role": "user", "content": model_user_text}],
        )
    except CustomProviderSelectionError as exc:
        return _error(422, "custom_provider_unsupported", str(exc))
    except CustomProviderError as exc:
        return _error(exc.status_code, exc.code, exc.user_message)
    answer = result.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return _error(
            502,
            "malformed_custom_provider_response",
            "PADIEM Custom 공급사 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
        )
    run = create_claw_run("padiem-chat", user_text, model_only_text=True)
    saved_conversation_id = await _record_completed_claw_result(
        request,
        run_id=run.run_id,
        conversation_id=conversation_id,
        user_text=user_text,
        answer=answer,
        authorized_workspace_id=None,
    )
    return _claw_general_sse(
        answer, None, conversation_id=saved_conversation_id or conversation_id,
    )


async def claw_general_execute(request: Request) -> JSONResponse | Response:
    """Run one generic B54 Claw request through the canonical P01 Engine lane (#3539).

    Reuses the existing #3382 authority end to end: ``claw_p01_adapter`` composed
    from trusted Worker bindings, the canonical USER subject resolved server-side
    from the signed Padiem session, the existing usage gate, and the existing P01
    result projection. The product boundary stays intact:

    - the canonical subject is resolved BEFORE the usage gate and BEFORE any
      P01/Engine dispatch, and is never read from or returned to the browser;
    - an unbound adapter fails closed with 503 ``engine_not_configured`` — this
      route never falls through to the standalone B62 direct-B14 chat route;
    - no manual-intake/quote/order, B66, connector, Memory or sandbox semantics
      are involved.
    """
    turn_started = time.perf_counter()
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    # #2505: an attached binary document travels in the same frame the Chat lane
    # already accepts, so the Claw lane reads it with the same decoder.
    binary_frame = content_type == "application/octet-stream"
    if content_type not in ("application/json", "application/octet-stream"):
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")

    try:
        raw_body = await read_bounded_request_body(
            request,
            max_bytes=MAX_CLAW_GENERAL_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")

    try:
        data = (
            decode_binary_attachment_frame(raw_body)
            if binary_frame else json.loads(raw_body.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    except ValueError:
        return _error(400, "invalid_attachment_frame", "첨부 파일 요청 형식이 올바르지 않습니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    user_text, text_error = _claw_general_user_text(data)
    if text_error is not None:
        return text_error

    # #2505: an attached file is read with the SAME Chat attachment contract, and
    # a document becomes the same untrusted reference context Chat builds. It
    # travels on the existing `additional_system_context` seam below, so the
    # Claw lane gains no second parser, storage row or Engine argument. Both
    # refusals happen before quota, first-turn claim, Engine dispatch and any
    # provider call.
    try:
        document_context, image_attachments = await parse_claw_turn_attachments_async(
            data.get("attachments"), file_resolver=file_resolver(request)
        )
    except AttachmentValidationError as exc:
        return _error(422, "invalid_attachment", str(exc))
    if image_attachments:
        return _error(
            422, "claw_image_attachment_unsupported",
            CLAW_IMAGE_ATTACHMENT_UNSUPPORTED,
        )
    # A document is model reference data for the answer lane. A lane that runs a
    # PC tool, a desktop op or the owner's direct provider never reads it, so a
    # mixed request is refused instead of silently dropping the file.
    attachment_conflict = (
        _error(
            422, "attachment_lane_unsupported",
            "첨부한 문서는 일반 AI 답변 요청에만 사용할 수 있습니다. 문서 없이 다시 요청해 주세요.",
        )
        if document_context is not None else None
    )

    # PADIEM Custom is a direct text completion: it cannot drive a PC tool,
    # desktop op or local file lane, and it never mixes with a PADIEM-managed
    # tier/model selection. Refuse those combinations before any dispatch.
    custom = None
    if "custom" in data:
        if "tier" in data or "model_id" in data:
            return _error(
                422,
                "custom_selection_conflict",
                "PADIEM 제공 모델과 PADIEM Custom을 한 요청에서 함께 선택할 수 없습니다.",
            )
        try:
            custom = parse_custom_selection(data.get("custom"))
        except BrowserRequestError as exc:
            return _error(422, "custom_provider_invalid", str(exc))
        if (
            request.headers.get(CLAW_LIVE_REQUEST_HEADER, "").strip()
            == CLAW_LIVE_REQUEST_MARKER
        ):
            return _error(
                422,
                "custom_live_unsupported",
                "PADIEM Custom은 Claw 실시간 실행 스트림과 함께 사용할 수 없습니다.",
            )
        if (
            _requested_local_desktop(user_text)[0]
            or _requested_local_command(user_text)[0]
            or _requested_natural_pc_files(user_text)
            or _requested_natural_pc_query(user_text)[0]
            or _requested_local_txt_path(user_text)[0]
        ):
            return _error(
                422,
                "custom_tool_unsupported",
                "PADIEM Custom은 현재 PC 실행·파일 도구 요청에 사용할 수 없습니다.",
            )
        if attachment_conflict is not None:
            # Same contract as the Chat lane: PADIEM Custom is a text-only
            # direct completion and never mixes with an attachment.
            return _error(422, "attachment_lane_unsupported",
                          "PADIEM Custom은 현재 텍스트 대화만 지원합니다.")
        uid = current_user_id(request) if auth_ready(request) else None
        if not isinstance(uid, str) or not uid:
            return _error(401, "unauthorized", "로그인이 필요합니다.")
        return await _claw_custom_direct(
            request, uid=uid, custom=custom, data=data, user_text=user_text,
        )

    # The desktop grammar is narrower than a shell command, so it is checked
    # first: a span that parses as a desktop op is never executed as one.
    desktop_requested, desktop_op = _requested_local_desktop(user_text)
    if desktop_requested:
        if attachment_conflict is not None:
            return attachment_conflict
        if desktop_op is None:
            return _error(422, "desktop_op_required",
                          "수행할 데스크톱 동작을 백틱으로 하나만 지정해 주세요.")
        return await _dispatch_user_desktop_request(
            request, user_text=user_text, desktop_op=desktop_op, data=data,
        )

    # One owner-requested initial observation runs through P01/Engine ToolRuntime
    # rather than the manual backtick diagnostic lane above.
    initial_pc_capture = bool(re.search(
        r"(?:내|우리|PC|pc|컴퓨터|COM1|com1).{0,40}"
        r"(?:화면|스크린|screen).{0,40}"
        r"(?:캡처|찍|보여|봐|capture|observe)",
        user_text, re.I,
    ))
    if initial_pc_capture and attachment_conflict is not None:
        return attachment_conflict
    # A selected PC is shape-checked once here and then bound to the two PC
    # lanes below. It is only a target hint: the server re-verifies that the
    # account actually has this Mesh execution target before dispatch.
    requested_device_id = data.get("device_id")
    if requested_device_id is not None and not is_pc_device_id(requested_device_id):
        return _error(422, "oracle_mesh_device_invalid", "PC 장치 선택이 유효하지 않습니다.")
    desktop_device_id = requested_device_id if initial_pc_capture else None

    command_requested, command_text = _requested_local_command(user_text)
    if command_requested:
        if attachment_conflict is not None:
            return attachment_conflict
        if command_text is None:
            return _error(422, "command_text_required",
                          "실행할 명령을 백틱으로 하나만 지정해 주세요.")
        return await _dispatch_user_command_request(
            request, user_text=user_text, command=command_text, data=data,
        )

    # #4976: a natural-language folder/file task (list then read) uses the
    # model-selected PC file tools. It is classified before the older
    # single-command/TXT lanes so a named TXT is read by the model from the
    # actual listing rather than by a fixed-path shortcut.
    pc_files_requested = _requested_natural_pc_files(user_text)
    if pc_files_requested and attachment_conflict is not None:
        return attachment_conflict
    # The browser hint was already shape-checked once above; the saved target
    # or the server-verified target replaces it before dispatch.
    pc_files_device_id = requested_device_id if pc_files_requested else None

    # #4139: natural-language PC state query (no backtick). Routes a clear
    # question about the verified PC to a bounded inventory command on that PC.
    natural_pc_requested, natural_pc_command = _requested_natural_pc_query(user_text)
    if natural_pc_requested:
        if attachment_conflict is not None:
            return attachment_conflict
        if natural_pc_command is None:
            return _error(422, "natural_pc_command_required",
                          "PC 조회 명령을 결정할 수 없습니다.")
        if "Get-PSDrive" not in natural_pc_command:
            return await _dispatch_user_command_request(
                request, user_text=user_text, command=natural_pc_command, data=data,
            )
        initial_pc_drive_query = True
        desktop_device_id = requested_device_id
    else:
        initial_pc_drive_query = False

    txt_requested, txt_path = _requested_local_txt_path(user_text)
    if txt_requested and not pc_files_requested:
        if attachment_conflict is not None:
            return attachment_conflict
        if txt_path is None:
            return _error(422, "txt_read_path_required",
                          "내 PC에서 읽을 TXT 파일의 상대 경로를 하나 지정해 주세요.")
        return await _dispatch_user_txt_request(
            request, user_text=user_text, path_relative=txt_path, data=data,
        )

    raw_tier = data.get("tier", "free")
    # #5223: the grade is resolved by the ONE shared authority, exactly like the
    # manual-execution lane. A lane with its own copy of the grade map refused
    # a valid administrator with ``422 invalid_tier`` (#5229).
    grade = resolve_claw_execution_grade(raw_tier)
    if grade is None:
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    requested_tier = grade.tier_id
    admin_lane = grade.admin_lane
    # P01 currently transports only member-tier enums. The administrator
    # chooses the separately authorized exact model, never a browser-provided
    # tier/model grant. PLUS here is solely the existing P01 transport profile.
    product_tier = grade.product_tier
    # The administrator lane is not a member grade: its identity answer stays
    # neutral instead of claiming the PLUS transport profile as a membership.
    identity_tier_id = None if admin_lane else requested_tier
    if "tier" in data:
        user_id = current_user_id(request) if auth_ready(request) else None
        tier_denial = await claw_execution_tier_denial(request, user_id, grade)
        if tier_denial is not None:
            return tier_denial
    # #4428: the central per-grade route is resolved SERVER-SIDE before any
    # browser model choice is considered. A stored row is authoritative; no row
    # keeps the historical static declaration.
    from .central_model_route_runtime import resolve_claw_tier_model

    claw_route = (SimpleNamespace(ok=True, model_id=ADMIN_B14_MODEL_ID,
                                  fallback_model_id=None, source="admin")
                  if admin_lane else await resolve_claw_tier_model(request, requested_tier))
    route_candidates = {
        model_id for model_id in (claw_route.model_id, claw_route.fallback_model_id)
        if model_id is not None
    }
    raw_model = data.get("model_id")
    selected_model_id: str | None = None
    central_route_model_id: str | None = None
    if raw_model is not None:
        try:
            selected_model_id = validate_explicit_b14_model_id(raw_model)
        except P01AdapterError:
            return _error(422, "invalid_selected_model", "등록된 B14 모델 ID 하나를 선택해 주세요.")
        if admin_lane and selected_model_id != ADMIN_B14_MODEL_ID:
            return _error(403, "model_not_available_for_tier", "관리자 모델과 일치하지 않습니다.")
        if product_tier is ProductTierLabel.FREE:
            # The resolved route candidates are the administrator's stored
            # per-grade selection when a central row exists, and the shared
            # static free contract when no row exists. No model name is
            # hardcoded here, so a renamed or replaced model needs no code
            # change and never bypasses the approved route.
            if selected_model_id not in route_candidates:
                return _error(403, "model_not_available_for_tier", "Free 등급에서 선택할 수 없는 모델입니다.")
        elif product_tier is not ProductTierLabel.PLUS:
            return _error(422, "explicit_model_tier_unsupported", "이 등급의 모델 직접 선택은 아직 지원되지 않습니다.")
        elif claw_route.source == "central" and selected_model_id not in route_candidates:
            # #5108: a stored central row is the administrator's exact selection
            # for this grade, and the chooser already offers only those models.
            # A paid-lane pick outside them fails closed instead of silently
            # replacing the applied route. Without a stored row the Plus
            # explicit-choice feature keeps its existing behaviour.
            return _error(403, "model_not_available_for_tier", "선택한 AI 등급에서 선택할 수 없는 모델입니다.")
    if selected_model_id is None:
        if not claw_route.ok or not claw_route.model_id:
            if product_tier is ProductTierLabel.PLUS:
                return _error(503, "tier_unavailable", "Claw Plus에서는 등록된 실행 모델 ID를 직접 선택해 주세요.")
            return _error(503, "tier_unavailable", "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.")
        central_route_model_id = claw_route.model_id
    elif selected_model_id in route_candidates:
        # A model already assigned by the central route is not treated as an
        # unrestricted member choice; it still travels as an exact model.
        central_route_model_id = selected_model_id
        selected_model_id = None

    _claw_stage(CLAW_STAGE_ROUTE, turn_started)

    # #3929: optional SAME-CONVERSATION follow-ups are verified against the
    # existing owner-scoped D1 conversation before quota/provider. No model,
    # filename, query string or user-reported owner can bind a conversation.
    conversation_id, conversation_error = await _resolve_intake_session_reference(
        request, data,
    )
    if conversation_error is not None:
        return conversation_error

    # #3382/#3539: the canonical USER subject is resolved SERVER-SIDE before the
    # usage gate and before any P01/Engine dispatch, so a failed revalidation
    # never consumes quota and never reaches a provider.
    adapter: P01CoreOrchestrationAdapter | None = getattr(
        request.app.state, "claw_p01_adapter", None
    )
    has_identity_lane = (
        adapter is not None
        and getattr(adapter, "subject_identity_lane", False) is True
    )

    # Explicit transport/resource failure before quota; do not silently
    # truncate the owned prior context or present an Engine ingress guard as a
    # provider model-token ceiling. Full serialized Engine checks stay active.
    #
    # #5554: the owned history read, the canonical B54 session and the Drive
    # grounding are three independent reads of the same signed request. They
    # used to run one after another, so a short Claw message paid their sum
    # before the model was even asked. They are issued together now and each
    # keeps its own stage duration. The refusals below are still evaluated in
    # the original order (history, then the session lane, then Drive), each
    # read is still fail-closed, and nothing reaches a quota, a provider or a
    # PC lane while these preflight reads are in flight.
    if has_identity_lane:
        from .b54_canonical_session import resolve_current_b54_canonical_session

        session_read = _claw_timed(
            CLAW_STAGE_SESSION, resolve_current_b54_canonical_session(request)
        )
    else:
        session_read = _claw_timed(CLAW_STAGE_SESSION, _no_session_read())
    # Load ONLY prior messages from the reverified owner-scoped server history.
    # A browser-supplied array of prior turns never becomes model context.
    # Use the signed owner and Control Plane workspace for the connected Drive.
    # Never let browser-provided historical turns choose file access.
    history_read, b54_session, drive_result = await asyncio.gather(
        _claw_timed(
            CLAW_STAGE_HISTORY,
            _owner_claw_context(request, conversation_id, user_text),
        ),
        session_read,
        _claw_timed(CLAW_STAGE_DRIVE, drive_general_grounding(request, user_text)),
        return_exceptions=True,
    )
    if isinstance(history_read, Exception):
        if isinstance(history_read, HistoryContextIncomplete):
            return _error(409, "conversation_context_incomplete",
                          "이전 대화 원문을 복원할 수 없습니다. 새 대화를 시작하거나 원문을 다시 입력해 주세요.")
        return _error(503, "conversation_authority_unavailable",
                      "대화 문맥을 안전하게 확인할 수 없습니다.")
    if isinstance(history_read, BaseException):
        raise history_read
    model_user_text = history_read

    subject_id: str | None = None
    authorized_workspace_id: str | None = None
    canonical_session_id: str | None = None
    if conversation_id is not None and not has_identity_lane:
        return _error(403, "canonical_b54_session_unavailable",
                      "인증된 Claw 실행 권한을 확인할 수 없습니다.")
    if has_identity_lane:
        if isinstance(b54_session, BaseException):
            raise b54_session
        if b54_session is None:
            return _error(
                403,
                "canonical_b54_session_unavailable",
                "인증된 Claw 실행 권한을 확인할 수 없습니다.",
            )
        subject_id = b54_session.auth_session.subject.subject_id
        authorized_workspace_id = getattr(b54_session.auth_session, "tenant_id", None)
        canonical_session_id = getattr(b54_session.auth_session, "session_id", None)
        if conversation_id is not None:
            if not isinstance(authorized_workspace_id, str) or not authorized_workspace_id:
                return _error(403, "workspace_scope_unavailable",
                              "대화 작업 공간을 확인할 수 없습니다.")

    if isinstance(drive_result, Exception):
        if isinstance(drive_result, DriveGroundingError):
            return _error(drive_result.status_code, drive_result.code, drive_result.message)
        raise drive_result
    if isinstance(drive_result, BaseException):
        raise drive_result
    drive_context, drive_sources = drive_result

    # #5015: one per-request, server-verified PC work context. It reads BOTH
    # the owner/workspace-scoped Broker directory the "내 컴퓨터" panel shows
    # and the deployment's Mesh execution target, so an empty Broker list is
    # never reported as "unregistered" and an online badge never becomes tool
    # permission. It is not an execution grant: dispatch re-verifies the owner
    # and the exact target.
    pc_work_text: str | None = None
    pc_context_started = time.perf_counter()
    # #5614: the account's selectable-model roster is an independent read, so
    # it starts here and is evaluated after the PC block. The PC target checks
    # therefore still decide first and still fail closed; only the read itself
    # overlaps.
    catalog_task, catalog_unavailable = _start_selectable_model_read(
        request, selected_model_id, central_route_model_id,
    )
    # #5479: every exit from this span - a PC-target refusal, an exception,
    # or a client that left - either already awaited the roster read or must
    # not leave it running. The finally below is the guarantee.
    try:
        pc_owner = current_user_id(request) if auth_ready(request) else None
        if isinstance(pc_owner, str) and pc_owner:
            from .claw_memory_routes import _resolve_memory_workspace
            from .pc_work_context import (
                SAVED_SELECTION_SELECTED, SAVED_SELECTION_UNAVAILABLE,
                render_pc_work_context, resolve_pc_work_context,
                read_saved_device_selection,
            )

            try:
                pc_workspace = await _resolve_memory_workspace(request, pc_owner)
            except Exception:
                pc_workspace = None
            pc_target_requested = initial_pc_drive_query or pc_files_requested
            explicit_pc_device_id = (
                desktop_device_id if initial_pc_drive_query
                else (pc_files_device_id if pc_files_requested else None)
            )
            selected_pc_device_id = explicit_pc_device_id
            if (
                pc_target_requested
                and isinstance(pc_workspace, str) and pc_workspace
            ):
                # The saved value is the account's default target. A failed read
                # is NOT "no selection": never fall back to another PC.
                saved_selection = await read_saved_device_selection(
                    request, owner_id=pc_owner, workspace_id=pc_workspace,
                )
                if explicit_pc_device_id is not None:
                    if (
                        saved_selection.status == SAVED_SELECTION_SELECTED
                        and saved_selection.device_id != explicit_pc_device_id
                    ):
                        # A stale tab must not execute on a target that differs
                        # from the current server preference.
                        return _error(
                            409, "pc_selection_stale",
                            "저장된 작업 대상과 화면 선택이 다릅니다. 내 컴퓨터에서 대상을 다시 선택해 주세요.",
                        )
                elif saved_selection.status == SAVED_SELECTION_SELECTED:
                    selected_pc_device_id = saved_selection.device_id
                elif saved_selection.status == SAVED_SELECTION_UNAVAILABLE:
                    return _error(
                        503, "pc_selection_unavailable",
                        "저장된 PC 작업 대상을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
                    )
            pc_context = await resolve_pc_work_context(
                request, owner_id=pc_owner,
                workspace_id=pc_workspace,
                session_id=canonical_session_id,
                selected_device_id=selected_pc_device_id,
            )
            if pc_target_requested and selected_pc_device_id is not None:
                selected_row = next(
                    (device for device in pc_context.devices
                     if device.device_id == selected_pc_device_id),
                    None,
                )
                if selected_row is not None and selected_row.state == "REVOKED":
                    return _error(
                        409, "pc_selection_revoked",
                        "선택한 PC의 연결이 해제되었습니다. 작업 대상을 다시 선택해 주세요.",
                    )
                if not pc_context.selected_confirmed:
                    # An explicit or saved target that did not resolve to the
                    # verified Mesh execution target never falls back to another PC.
                    if not pc_context.execution.ready:
                        return _error(
                            409, "pc_target_unavailable",
                            "선택한 PC의 서버 실행 대상을 확인할 수 없습니다. 작업 대상을 다시 확인해 주세요.",
                        )
                    return _error(
                        403, "pc_target_mismatch",
                        "선택한 PC가 서버 실행 대상과 일치하지 않습니다. 작업 대상을 다시 선택해 주세요.",
                    )
                # Carry the SAME effective target into the Engine plan for each
                # PC lane that this turn selected.
                if initial_pc_drive_query:
                    desktop_device_id = selected_pc_device_id
                if pc_files_requested:
                    pc_files_device_id = selected_pc_device_id
            pc_work_text = render_pc_work_context(pc_context)
        _claw_stage(CLAW_STAGE_PC_CONTEXT, pc_context_started)

        # #3790: in the production Worker Claw uses the central model
        # ready/owner-allowed metadata resolver. Reject a forged advanced model ID
        # before quota/P01. Test-only deployments without this optional view still
        # rely on B14's final exact-ID execution authority.
        #
        # #5614: the read was started before the PC work context and is only
        # EVALUATED here, so this refusal still comes after the PC target checks.
        if catalog_unavailable:
            return _error(503, "model_catalog_unavailable", "사용 가능한 모델 목록을 확인할 수 없습니다.")
        if catalog_task is not None:
            try:
                available = await catalog_task
                if not isinstance(available, list):
                    raise ValueError("invalid model roster")
                eligible_ids = {row["model_id"] for row in available}
            except (Exception,):
                return _error(503, "model_catalog_unavailable", "사용 가능한 모델 목록을 확인할 수 없습니다.")
            target_model = selected_model_id or central_route_model_id
            if target_model not in eligible_ids:
                # Only a server-resolved central route may advance to its
                # explicitly configured fallback. A member choice never does.
                if (selected_model_id is None
                        and claw_route.fallback_model_id in eligible_ids):
                    central_route_model_id = claw_route.fallback_model_id
                else:
                    return _error(422, "model_not_available", "현재 사용할 수 없는 모델입니다. 다른 모델을 선택해 주세요.")

    finally:
        # A task the evaluation awaited is done, where this is a no-op; one
        # the turn never reached is cancelled here, and the drain callback
        # keeps even its outcome retrieved.
        if catalog_task is not None and not catalog_task.done():
            catalog_task.cancel()

    live_requested = (
        request.headers.get(CLAW_LIVE_REQUEST_HEADER, "").strip()
        == CLAW_LIVE_REQUEST_MARKER
    )
    if live_requested and not live_stream_allowed(request.app.state, subject_id):
        # Admission is pre-quota, pre-Engine and cannot be broadened by
        # a forged browser header or a stale GET capability response.
        return _error(503, "claw_live_stream_unavailable", "Claw 실시간 실행 상태를 사용할 수 없습니다.")

    # #3933 S1: optional first-turn trusted coding context. OFF by default:
    # the helper returns None without touching any store, keeping the exact
    # historical first-turn path below byte-for-byte identical. When enabled,
    # a missing canonical subject or tenant fails closed here, pre-quota.
    quota_started = time.perf_counter()
    first_turn_context: B54VerifiedCodingContextV1 | None = None
    if conversation_id is None:
        try:
            first_turn_context = await reserve_first_turn_grant(
                request,
                user_id=current_user_id(request) if auth_ready(request) else None,
                subject_id=subject_id,
                tenant_id=authorized_workspace_id,
                route_scope="claw_general_execute",
            )
        except FirstTurnAuthorityError as gate_exc:
            return _error(gate_exc.status_code, gate_exc.code, gate_exc.message)

    denial = await _usage_gate_denial(request)
    _claw_stage(CLAW_STAGE_QUOTA, quota_started)
    if denial is not None:
        return denial

    if adapter is None:
        # No composed P01 lane exists, so the consumed authorization is provably
        # un-dispatched: compensate the exact receipt (#2226). This route has no
        # direct-B14 fallback (#3539); it fails closed instead.
        await _refund_active_reservation()
        await fail_first_turn_grant(request, first_turn_context)
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_not_configured",
                    "message": "Engine 클라이언트가 설정되지 않았습니다.",
                    "detail": _safe_composition_diagnostic(request),
                },
            },
            status_code=503,
            headers=_NO_STORE_HEADERS,
        )

    # #3930: An explicitly requested live SSE relay requires BOTH the reviewed
    # server authority and the canonical P01 stream port. No silent fallback to
    # completed requests, direct B14, or an unapproved UI mode is permitted.
    if live_requested:
        runner = getattr(adapter, "_runner", None)
        if (
            getattr(request.app.state, "claw_live_sse_enabled", False) is not True
            or not callable(getattr(runner, "run_stream", None))
        ):
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "claw_live_stream_unavailable", "Claw 실시간 실행 상태를 사용할 수 없습니다.")

    timezone_name = data.get("timezone") if isinstance(data.get("timezone"), str) else None
    native_plan = parse_native_calendar_intent(user_text, timezone_name=timezone_name)
    if native_plan.get("op") != "none":
        native_store = getattr(request.app.state, "calendar_store", None)
        if native_store is None:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "calendar_store_unavailable", "캘린더 저장소를 사용할 수 없습니다.")
        native_uid = current_user_id(request) if auth_ready(request) else None
        if native_uid is None:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(401, "unauthorized", "로그인이 필요합니다.")
        client_turn_id = data.get("calendar_turn_id") if isinstance(data.get("calendar_turn_id"), str) else request.headers.get("X-Padiem-Calendar-Turn-Id")
        if not isinstance(client_turn_id, str) or not client_turn_id or len(client_turn_id) > 128:
            client_turn_id = None
        turn_seed = "|".join(str(v) for v in (native_uid, conversation_id, user_text, timezone_name, client_turn_id or ""))

        turn_key = "claw-" + __import__("hashlib").sha256(turn_seed.encode("utf-8")).hexdigest()[:16]
        run = create_claw_run("padiem-chat", user_text, model_only_text=True)
        if native_plan.get("op") == "clarify":
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(422, "clarification_required", str(native_plan.get("question")))
        # Claim after the reserved grant exists. Do not fake state if the request
        # was never eligible for a first-turn grant.
        if first_turn_context is not None:
            first_turn_store = getattr(request.app.state, "claw_first_turn_grant_store", None)
            try:
                claimed = await claim_first_turn_grant(first_turn_store, first_turn_context)
            except Exception:
                await _refund_active_reservation()
                await fail_first_turn_grant(request, first_turn_context)
                return _error(503, "first_turn_grant_unavailable", "대화 권한 저장소를 사용할 수 없습니다.")
            if not claimed:
                await _refund_active_reservation()
                return _error(409, "first_turn_dispatch_in_progress", "같은 요청이 이미 처리 중입니다. 잠시 후 다시 시도해 주세요.")
        try:
            native_result = await execute_native_calendar_plan(request, native_store, native_uid, native_plan, turn_key=turn_key)
        except Exception as exc:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(getattr(exc, "status_code", 503), getattr(exc, "code", "calendar_unavailable"), getattr(exc, "message", "Calendar operation failed"))
        if not native_result.get("ok"):
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(502, "calendar_unavailable", "Calendar operation failed")
        if native_result.get("operation") == "create_appointment":
            apt = native_result.get("appointment", {})
            native_answer = "네이티브 일정이 등록되었습니다: " + str(apt.get("title")) + " (" + str(apt.get("date")) + ")"
        elif native_result.get("operation") == "read":
            items = native_result.get("items", [])
            if not items:
                native_answer = "해당 기간에 저장된 네이티브 일정이 없습니다 (" + str(native_result.get("timezone")) + ")."
            else:
                native_answer = "네이티브 일정 " + str(len(items)) + "건입니다."
        else:
            native_answer = str(native_result.get("question", "일정 정보가 필요합니다."))
        _clear_reservation()
        saved_conversation_id = await _record_completed_claw_result(request, run_id=run.run_id, conversation_id=conversation_id, user_text=user_text, answer=native_answer, authorized_workspace_id=authorized_workspace_id, first_turn_grant=first_turn_context)
        return _claw_general_sse(native_answer, None, conversation_id=saved_conversation_id)
    # continue normal P01 path below
    # continue normal P01 path below
    run = create_claw_run("padiem-chat", model_user_text, model_only_text=True)

    # #3933 S1: the reservation above never authorizes a dispatch by itself.
    # Exactly one atomic claim may proceed; a concurrent or replayed attach
    # loses here, gets a status-only 409, and the quota reservation is
    # refunded. No provider/Engine dispatch happens on this path.
    if first_turn_context is not None:
        store = getattr(request.app.state, "claw_first_turn_grant_store", None)
        try:
            claimed = await claim_first_turn_grant(store, first_turn_context)
        except FirstTurnAuthorityError as claim_exc:
            await _refund_active_reservation()
            return _error(claim_exc.status_code, claim_exc.code, claim_exc.message)
        if not claimed:
            await _refund_active_reservation()
            return _error(409, "first_turn_dispatch_in_progress",
                          "같은 요청이 이미 처리 중입니다. 잠시 후 다시 시도해 주세요.")

    # #3655: evidence mode is opt-in per request; normal callers see the exact
    # same response surface as before.
    evidence_requested = (
        request.headers.get(CLAW_EVIDENCE_REQUEST_HEADER, "").strip() == CLAW_EVIDENCE_MARKER
    )

    # #3936/#3655: a request this route is going to refuse must be refused before any
    # search judgement, so a rejected call can never spend a model inference or reach a
    # provider. The quota refund and first-turn release stay exactly as they were.
    if live_requested and evidence_requested:
        await _refund_active_reservation()
        # Proven pre-dispatch denial after a successful claim: the claimed grant must
        # fail here, or it stays active (in-progress) until expiry and blocks the key.
        await fail_first_turn_grant(request, first_turn_context)
        return _error(422, "live_evidence_mode_unsupported", "실시간 상태와 감사 증거 요청은 동시에 사용할 수 없습니다.")

    # #4469: optional public web grounding, judged by the model and off unless the
    # server says otherwise. It reads the SAME owner-verified history the answer lane
    # uses, never browser-supplied prior turns, so forged history cannot move the
    # search target. Everything downstream is unchanged when it returns nothing.
    # Private Drive data never enters the public web search judgement/query.
    if initial_pc_drive_query or pc_files_requested:
        # #5015/#4976: a PC drive or file task needs no public web evidence.
        # Skipping the judgement call keeps this turn from spending a model
        # call before the Engine PC tool dispatch.
        grounding_context, search_sources = None, ()
    elif drive_context is None:
        judgement_started = time.perf_counter()
        grounding_context, search_sources = await _claw_public_search_grounding(
            request, adapter, model_user_text,
            model_id=selected_model_id or central_route_model_id,
        )
        _claw_stage(CLAW_STAGE_JUDGEMENT, judgement_started)
    else:
        grounding_context, search_sources = drive_context, drive_sources

    # #4139: a model-driven desktop run must have an owner-bound run row
    # BEFORE Engine dispatch. The signed internal desktop route resolves the
    # target conversation, workspace and owner session from that row, so an
    # unstaged run can only fail after the model has already started.
    staged_conversation_id: str | None = None
    if initial_pc_capture or initial_pc_drive_query or pc_files_requested:
        from .claw_memory_routes import _resolve_memory_workspace
        stage_uid = current_user_id(request) if auth_ready(request) else None
        stage = getattr(
            getattr(request.app.state, "history_store", None),
            "record_txt_pending_run", None,
        )
        if not isinstance(stage_uid, str) or not stage_uid or not callable(stage):
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "desktop_history_unavailable",
                          "대화 저장소를 확인할 수 없습니다.")
        try:
            stage_workspace = await _resolve_memory_workspace(request, stage_uid)
        except Exception:
            stage_workspace = None
        if not isinstance(stage_workspace, str) or not stage_workspace:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "desktop_workspace_unavailable",
                          "대화 범위를 확인할 수 없습니다.")
        try:
            staged_conversation_id = await stage(
                user_id=stage_uid, run_id=run.run_id,
                workspace_id=stage_workspace, user_text=user_text,
                conversation_id=conversation_id,
            )
        except Exception:
            await _refund_active_reservation()
            await fail_first_turn_grant(request, first_turn_context)
            return _error(503, "desktop_history_unavailable",
                          "대화 저장에 실패했습니다.")

    # #5015: the verified PC context travels on the same optional
    # `additional_system_context` seam grounding already uses. It is composed
    # server-side per request; the browser cannot supply or suppress it.
    # #2505: an attached document rides the same seam, as the same untrusted
    # reference data Chat already builds for its own turn.
    combined_system_context = _combine_system_context(
        grounding_context, document_context, pc_work_text,
    )
    # This side channel is assembled only from the signed owner's saved rows,
    # the actual latest user message and server-read external data. Browser
    # history and browser pc_action_context fields are never copied into it.
    pc_action_context = list(getattr(request.state, "claw_pc_action_context", (
        {"role": "user", "content": user_text},
    )))
    for content, source in (
        (grounding_context, "file" if drive_context is not None else "web"),
        (document_context, "file"),
    ):
        if content:
            pc_action_context.append({
                "role": "tool_result", "content": content, "source": source,
            })
    pc_delegation = None
    if initial_pc_drive_query or pc_files_requested:
        from .pc_delegation_routes import load_pc_delegation

        # stage_uid is the authenticated owner whose PC run was just staged.
        # No browser delegation field participates in this decision snapshot.
        pc_delegation = await load_pc_delegation(request, stage_uid)

    if live_requested:
        from .claw_live_events import live_claw_sse
        live_args = {"product_tier": product_tier, "subject_id": subject_id,
                     "identity_tier_id": identity_tier_id}
        if initial_pc_capture:
            live_args["desktop_capture"] = True
            live_args["desktop_device_id"] = desktop_device_id
        if initial_pc_drive_query:
            live_args["pc_drive_query"] = True
        if initial_pc_drive_query:
            live_args["pc_drive_query"] = True
            if desktop_device_id is not None:
                # Carries the SAME server-verified target the context named;
                # the Engine forwards it to the signed Mesh dispatch.
                live_args["desktop_device_id"] = desktop_device_id
        if pc_files_requested:
            live_args["pc_files_query"] = True
            live_args["pc_files_device_id"] = pc_files_device_id
        if initial_pc_drive_query or pc_files_requested:
            live_args["pc_action_context"] = pc_action_context
            live_args["pc_delegation"] = pc_delegation
        if selected_model_id is not None:
            live_args["selected_model_id"] = selected_model_id
        if central_route_model_id is not None:
            live_args["central_route_model_id"] = central_route_model_id
        if combined_system_context is not None:
            live_args["additional_system_context"] = combined_system_context
        async def after_verified_live_completion(answer: str) -> str | None:
            # Runs after validated terminal P01 completion, never on pause,
            # failure, disconnect or an unverified/empty answer.
            return await _record_completed_claw_result(
                request, run_id=run.run_id, conversation_id=conversation_id,
                user_text=user_text, answer=answer,
                authorized_workspace_id=authorized_workspace_id,
                first_turn_grant=first_turn_context,
                staged_conversation_id=staged_conversation_id,
            )

        async def after_live_terminal_without_answer(terminal_class: str) -> None:
            # The SSE relay only settles terminals with a proven execution
            # verdict (#5015r): proven_not_dispatched / verified_failure
            # settle as failed, verified_cancelled settles as cancelled.
            # An approval pause, a browser disconnect and an unverifiable
            # outcome are not PC execution failures and are never claimed,
            # so this handler keeps them untouched.
            if staged_conversation_id is None:
                return
            if terminal_class in ("verified_failure", "proven_not_dispatched"):
                await _mark_staged_run_failed(request, run.run_id)
            elif terminal_class == "verified_cancelled":
                await _settle_staged_run_status(request, run.run_id, "cancelled")

        return live_claw_sse(
            adapter, run, live_args,
            on_completed=after_verified_live_completion,
            on_terminal_without_answer=after_live_terminal_without_answer,
            sources=search_sources,
        )

    try:
        dispatch_args = {"product_tier": product_tier, "subject_id": subject_id,
                         "identity_tier_id": identity_tier_id}
        if initial_pc_capture:
            dispatch_args["desktop_capture"] = True
            dispatch_args["desktop_device_id"] = desktop_device_id
        if initial_pc_drive_query:
            dispatch_args["pc_drive_query"] = True
        if initial_pc_drive_query:
            dispatch_args["pc_drive_query"] = True
            if desktop_device_id is not None:
                dispatch_args["desktop_device_id"] = desktop_device_id
        if pc_files_requested:
            dispatch_args["pc_files_query"] = True
            dispatch_args["pc_files_device_id"] = pc_files_device_id
        if initial_pc_drive_query or pc_files_requested:
            dispatch_args["pc_action_context"] = pc_action_context
            dispatch_args["pc_delegation"] = pc_delegation
        if selected_model_id is not None:
            dispatch_args["selected_model_id"] = selected_model_id
        if central_route_model_id is not None:
            dispatch_args["central_route_model_id"] = central_route_model_id
        if combined_system_context is not None:
            dispatch_args["additional_system_context"] = combined_system_context
        answer_started = time.perf_counter()
        outcome = await adapter.execute(run, **dispatch_args)
        _claw_stage(CLAW_STAGE_ANSWER, answer_started)
    except P01AdapterError as exc:
        if staged_conversation_id is not None:
            await _mark_staged_run_failed(request, run.run_id)
        if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
            await _refund_active_reservation()
            # Proven non-dispatch: the claimed grant may terminally fail.
            # Any other class leaves it active until expiry (no auto-retry).
            await fail_first_turn_grant(request, first_turn_context)
        else:
            _clear_reservation()
        if exc.code in _MODEL_HOLD_ERROR_CODES:
            # NO_EXECUTABLE_ROUTE product HOLD (#3568): the run never dispatched,
            # so the user sees a bounded model-unavailable state instead of a
            # generic engine failure. Same code family as the pre-dispatch
            # tier_unavailable projection used by the other tiers. Evidence
            # mode (#3655 seam) carries only the route-minted Claw run id on
            # this path — no orchestration ref, selected route, provider
            # attempts, or fallback, because no orchestration run materialized.
            # The HOLD projection stays 503 and never becomes an
            # engine_execution_failed.
            hold_headers = dict(_NO_STORE_HEADERS)
            if evidence_requested:
                hold_headers.update(_claw_evidence_response_headers(run.run_id, None))
            return JSONResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "tier_unavailable",
                        "message": _MODEL_HOLD_USER_MESSAGE,
                    },
                },
                status_code=503,
                headers=hold_headers,
            )
        failure_headers = dict(_NO_STORE_HEADERS)
        if evidence_requested:
            # The outcome never materialized, so only the route-minted Claw run
            # id is available as the correlation ref on this path.
            failure_headers.update(_claw_evidence_response_headers(run.run_id, None))
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행에 실패했습니다.",
                    "detail": _safe_engine_failure_detail(exc),
                },
            },
            status_code=502,
            headers=failure_headers,
        )
    except Exception:
        _clear_reservation()
        if staged_conversation_id is not None:
            await _mark_staged_run_failed(request, run.run_id)
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행에 실패했습니다.",
                    "detail": P01_FAILURE_DETAIL_UNKNOWN,
                },
            },
            status_code=502,
            headers=_NO_STORE_HEADERS,
        )
    _clear_reservation()

    status_value = outcome.projection.status.value
    if status_value == "waiting_approval":
        # The generic lane exposes no approval-consent surface; an
        # approval-requiring run is refused rather than reported as an answer.
        return _error(
            409,
            "claw_general_approval_required",
            "승인이 필요한 요청입니다. Claw 업무 화면에서 진행해 주세요.",
        )
    if status_value != "completed" or not outcome.answer:
        if staged_conversation_id is not None:
            await _mark_staged_run_failed(request, run.run_id)
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행이 완료되지 않았습니다.",
                    "detail": P01_FAILURE_DETAIL_CONTRACT,
                },
            },
            status_code=502,
            headers=_NO_STORE_HEADERS,
        )

    # Preserve the existing completed-path persistence contract; the live
    # callback above now uses the exact same authority and read-model logic.
    persist_started = time.perf_counter()
    saved_conversation_id = await _record_completed_claw_result(
        request, run_id=run.run_id, conversation_id=conversation_id,
        user_text=user_text, answer=outcome.answer,
        authorized_workspace_id=authorized_workspace_id,
        first_turn_grant=first_turn_context,
        staged_conversation_id=staged_conversation_id,
    )
    _claw_stage(CLAW_STAGE_PERSIST, persist_started)
    return _claw_general_sse(
        outcome.answer,
        _claw_evidence_response_headers(run.run_id, outcome) if evidence_requested else None,
        history=getattr(outcome, "p01_event_history", ()),
        conversation_id=saved_conversation_id,
        sources=search_sources,
    )


__all__ = ["claw_general_execute"]
