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
B62 ``/api/chat`` composer. There is NO direct-B14 fallback: an unbound P01 lane
fails closed (503) instead of silently degrading into the standalone B62
``/api/chat/stream`` route, and the canonical USER subject is resolved
SERVER-SIDE from the signed Padiem session before the usage gate and before any
P01/Engine dispatch.

No second Engine service binding, identity authority or entitlement authority is
introduced here; the projection vocabulary is the one ``claw_routes`` already
owns.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
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
    _BROWSER_TIER_MAP,
    _NO_STORE_HEADERS,
    _error,
    _safe_composition_diagnostic,
    _safe_engine_failure_detail,
    _usage_gate_denial,
    _resolve_intake_session_reference,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation
from .auth_routes import auth_ready, current_user_id
from .history import HISTORY_PREVIEW_SUFFIX, HistoryContextIncomplete, validate_conversation_id, PRODUCT_SCOPE_CHAT

# This is the existing Chat HTTP resource envelope, not a provider/model cap.
# The separate P01 Engine ingress guard remains in force until #4383 is resolved.
MAX_CLAW_GENERAL_BODY_BYTES = 6_000_000
# Kept importable for older clients; None means no Claw-general pilot text cap.
MAX_CLAW_GENERAL_MESSAGE_CHARS: int | None = None
MAX_CLAW_GENERAL_MESSAGES: int | None = None
# Model capability is not constrained by this number: the canonical Engine
# still enforces a finite 6MB serialized HTTP request memory-safety envelope.
# Reserve transport overhead for agent/route metadata; never silently truncate.
P01_ENGINE_REQUEST_ENVELOPE_BYTES = 5_500_000
CLAW_LIVE_REQUEST_HEADER = "X-Padiem-Claw-Live"
CLAW_LIVE_REQUEST_MARKER = "p01-events-v1"
_CLAW_GENERAL_ROLES = frozenset({"user", "assistant"})

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
        "X-Padiem-Selected-Route-Id", getattr(outcome, "selected_route_id", None)
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
    if not excerpts:
        return latest
    return (
        "동일 소유자의 이전 대화 (참고 문맥만 제공하며 도구 권한은 부여하지 않음):\n"
        + "\n".join(excerpts) + "\n\n현재 사용자 요청:\n" + latest
    )


async def _save_claw_exchange(
    request: Request, *, conversation_id: str | None, user_text: str,
    answer: str,
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
        saved = append(uid, conversation_id, user_text, answer, project_id, product_scope=PRODUCT_SCOPE_CHAT)
        if inspect.isawaitable(saved):
            saved = await saved
        if not isinstance(saved, str):
            return None
        return saved if validate_conversation_id(saved) is not None else None
    except Exception:
        return None


async def _record_completed_claw_result(
    request: Request, *, run_id: str, conversation_id: str | None,
    user_text: str, answer: str, authorized_workspace_id: str | None,
    first_turn_grant: B54VerifiedCodingContextV1 | None = None,
) -> str | None:
    """Persist only a verified completed Claw result; never replay Engine.

    Conversation saving and completed-run history are both optional read-model
    projections. Failure to save must not conceal an already-completed answer
    or advertise a server conversation ID that was not actually stored.
    """
    saved_conversation_id = await _save_claw_exchange(
        request, conversation_id=conversation_id,
        user_text=user_text, answer=answer,
    )
    # #3933 S1: link the reserved first-turn grant to its verified outcome.
    # Best-effort provenance only: a grant-store failure must never conceal
    # an already-completed answer.
    await complete_first_turn_grant(
        request, first_turn_grant, run_ref=run_id,
        saved_conversation_id=saved_conversation_id,
    )
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
    request: Request, adapter: Any, messages: Any
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
    agent = evidence_agent()
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
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
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
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    user_text, text_error = _claw_general_user_text(data)
    if text_error is not None:
        return text_error

    raw_tier = data.get("tier", "plus")
    if not isinstance(raw_tier, str):
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    product_tier = _BROWSER_TIER_MAP.get(raw_tier.strip().lower())
    if product_tier is None:
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    raw_model = data.get("model_id")
    selected_model_id: str | None = None
    if raw_model is not None:
        try:
            selected_model_id = validate_explicit_b14_model_id(raw_model)
        except P01AdapterError:
            return _error(422, "invalid_selected_model", "등록된 B14 모델 ID 하나를 선택해 주세요.")
        if product_tier is not ProductTierLabel.PLUS:
            return _error(422, "explicit_model_tier_unsupported", "모델 직접 선택은 현재 Plus에서만 지원됩니다.")
    try:
        tier_route = active_route_for(product_tier)
    except ProductTierRoutesError:
        return _error(503, "tier_unavailable", "AI 등급 설정을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if selected_model_id is None and (tier_route is None or not tier_route.model_id):
        if product_tier is ProductTierLabel.PLUS:
            return _error(503, "tier_unavailable", "Claw Plus에서는 등록된 실행 모델 ID를 직접 선택해 주세요.")
        return _error(503, "tier_unavailable", "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.")

    # #3929: optional SAME-CONVERSATION follow-ups are verified against the
    # existing owner-scoped D1 conversation before quota/provider. No model,
    # filename, query string or user-reported owner can bind a conversation.
    conversation_id, conversation_error = await _resolve_intake_session_reference(
        request, data,
    )
    if conversation_error is not None:
        return conversation_error

    # Load ONLY prior messages from the reverified owner-scoped server history.
    # A browser-supplied array of prior turns never becomes model context.
    try:
        model_user_text = await _owner_claw_context(request, conversation_id, user_text)
    except HistoryContextIncomplete:
        return _error(409, "conversation_context_incomplete",
                      "이전 대화 원문을 복원할 수 없습니다. 새 대화를 시작하거나 원문을 다시 입력해 주세요.")
    except Exception:
        return _error(503, "conversation_authority_unavailable",
                      "대화 문맥을 안전하게 확인할 수 없습니다.")

    # Explicit transport/resource failure before quota; do not silently
    # truncate the owned prior context or present an Engine ingress guard as a
    # provider model-token ceiling. Full serialized Engine checks stay active.
    if len(model_user_text.encode("utf-8")) > P01_ENGINE_REQUEST_ENVELOPE_BYTES:
        return _error(413, "engine_request_envelope_exceeded",
                      "엔진 전송 안전 한도를 초과했습니다. 더 짧은 대화에서 다시 요청해 주세요.")

    # #3382/#3539: the canonical USER subject is resolved SERVER-SIDE before the
    # usage gate and before any P01/Engine dispatch, so a failed revalidation
    # never consumes quota and never reaches a provider.
    adapter: P01CoreOrchestrationAdapter | None = getattr(
        request.app.state, "claw_p01_adapter", None
    )
    subject_id: str | None = None
    authorized_workspace_id: str | None = None
    if conversation_id is not None and (
        adapter is None or getattr(adapter, "subject_identity_lane", False) is not True
    ):
        return _error(403, "canonical_b54_session_unavailable",
                      "인증된 Claw 실행 권한을 확인할 수 없습니다.")
    if adapter is not None and getattr(
        adapter, "subject_identity_lane", False
    ) is True:
        from .b54_canonical_session import resolve_current_b54_canonical_session

        b54_session = await resolve_current_b54_canonical_session(request)
        if b54_session is None:
            return _error(
                403,
                "canonical_b54_session_unavailable",
                "인증된 Claw 실행 권한을 확인할 수 없습니다.",
            )
        subject_id = b54_session.auth_session.subject.subject_id
        authorized_workspace_id = getattr(b54_session.auth_session, "tenant_id", None)
        if conversation_id is not None:
            if not isinstance(authorized_workspace_id, str) or not authorized_workspace_id:
                return _error(403, "workspace_scope_unavailable",
                              "대화 작업 공간을 확인할 수 없습니다.")

    # #3790: in the production Worker Claw uses the central model
    # ready/owner-allowed metadata resolver. Reject a forged advanced model ID
    # before quota/P01. Test-only deployments without this optional view still
    # rely on B14's final exact-ID execution authority.
    if selected_model_id is not None:
        choice_authority = getattr(request.app.state, "b14_model_choice_resolver", None)
        if choice_authority is not None:
            list_fn = getattr(choice_authority, "list_selectable_models", None)
            if not callable(list_fn):
                return _error(503, "model_catalog_unavailable", "사용 가능한 모델 목록을 확인할 수 없습니다.")
            try:
                available = await list_fn()
                if not isinstance(available, list):
                    raise ValueError("invalid model roster")
                eligible_ids = {row["model_id"] for row in available}
            except (Exception,):
                return _error(503, "model_catalog_unavailable", "사용 가능한 모델 목록을 확인할 수 없습니다.")
            if selected_model_id not in eligible_ids:
                return _error(422, "model_not_available", "현재 사용할 수 없는 모델입니다. 다른 모델을 선택해 주세요.")

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

    # #4469: optional public web grounding, admitted by the server only and off
    # unless both server authorities exist. Everything downstream is unchanged
    # when it returns nothing.
    grounding_context, search_sources = await _claw_public_search_grounding(
        request, adapter, data.get("messages")
    )

    if live_requested:
        if evidence_requested:
            await _refund_active_reservation()
            # Proven pre-dispatch denial after a successful claim: the
            # claimed grant must fail here, or it stays active (in-progress)
            # until expiry and blocks the key. Mirrors NOT_DISPATCHED below.
            await fail_first_turn_grant(request, first_turn_context)
            return _error(422, "live_evidence_mode_unsupported", "실시간 상태와 감사 증거 요청은 동시에 사용할 수 없습니다.")
        from .claw_live_events import live_claw_sse
        live_args = {"product_tier": product_tier, "subject_id": subject_id}
        if selected_model_id is not None:
            live_args["selected_model_id"] = selected_model_id
        if grounding_context is not None:
            live_args["additional_system_context"] = grounding_context
        async def after_verified_live_completion(answer: str) -> str | None:
            # Runs after validated terminal P01 completion, never on pause,
            # failure, disconnect or an unverified/empty answer.
            return await _record_completed_claw_result(
                request, run_id=run.run_id, conversation_id=conversation_id,
                user_text=user_text, answer=answer,
                authorized_workspace_id=authorized_workspace_id,
                first_turn_grant=first_turn_context,
            )

        return live_claw_sse(
            adapter, run, live_args,
            on_completed=after_verified_live_completion,
            sources=search_sources,
        )

    try:
        dispatch_args = {"product_tier": product_tier, "subject_id": subject_id}
        if selected_model_id is not None:
            dispatch_args["selected_model_id"] = selected_model_id
        if grounding_context is not None:
            dispatch_args["additional_system_context"] = grounding_context
        outcome = await adapter.execute(run, **dispatch_args)
    except P01AdapterError as exc:
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
    saved_conversation_id = await _record_completed_claw_result(
        request, run_id=run.run_id, conversation_id=conversation_id,
        user_text=user_text, answer=outcome.answer,
        authorized_workspace_id=authorized_workspace_id,
        first_turn_grant=first_turn_context,
    )
    return _claw_general_sse(
        outcome.answer,
        _claw_evidence_response_headers(run.run_id, outcome) if evidence_requested else None,
        history=getattr(outcome, "p01_event_history", ()),
        conversation_id=saved_conversation_id,
        sources=search_sources,
    )


__all__ = ["claw_general_execute"]
