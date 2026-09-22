"""Claw Manual Intake Preview + Real Execution Routes (#2086 / #2215).

Provides:
- POST /api/claw/manual-intake/preview — deterministic preview (existing)
- POST /api/claw/manual-intake/execute — real P01/Engine-backed execution (#2215)
- POST /api/claw/manual-intake/quote-compare — deterministic supplier quote
  comparison and draft-only negotiation (#2812)

The preview route remains deterministic and never calls provider/P01.
The execute route consumes a Worker-native P01 adapter composed from trusted
B62 bindings at app/route composition time (see ``claw_p01_composition``) and
exposed on ``app.state.claw_p01_adapter``. It never reads ``os.environ``. The
composition chain it drives is the existing B54 P01 contract:

    ManualIntakeRequest
    → create_claw_run
    → P01CoreOrchestrationAdapter
    → P01EngineOrchestrationClient
    → Engine
    → B14

Both routes are fail-closed: missing/malformed input, a missing Worker P01/Engine
binding (adapter unbound), Engine timeout/unreachable, and malformed P01
responses all return bounded safe errors. No credential/provider raw text leaks
into the browser. No silent preview fallback after explicit execute.

Artifact download (#2308): an unauthorized cross-tenant ``document_id`` is
projected as the same non-disclosing ``404 artifact_not_found`` as a missing
artifact, so no caller can learn whether a foreign document exists. Genuine
storage failures stay ``503 workspace_document_read_failed``. The store keeps
raising on tenant mismatch; only the HTTP projection is normalized.

Quota accounting (#2226): the B62 UsageGate consumes before the P01/Engine
transport. A consumed authorization is compensated only when the failure is
provably pre-dispatch (unbound adapter or ``P01DispatchClass.NOT_DISPATCHED``
classification from the P01 chain). Success, dispatched failures, ambiguous
timeouts, and gate denials never refund. Callers cannot request or mint a
refund: the decision derives solely from server-side dispatch classification.

Run history (#2317): ``GET /api/claw/runs`` serves a bounded, owner-scoped list
of recent Claw runs (run id, channel, action, title, status, timestamps, a
truncated result summary, and a document reference for artifact runs). Rows are
written by the execute path through the existing D1 ``PADIEM_CHAT_DB`` history
authority; raw request content, provider secrets, session cookies, OAuth tokens,
and object keys are never persisted. A history write/read failure fails closed
with a stable public-safe 503 instead of silently claiming persistence.

Canonical session projection (#2829): the execute route may carry an optional
``conversation_id`` referencing the existing canonical conversation authority.
It is validated by the conversation validator itself and resolved with the
owner-scoped conversation lookup — no new session, account, or workspace
authority. Missing/foreign references fail closed with the same non-disclosing
``conversation_not_found`` projection the chat routes use, before any quota,
tenant, or P01/Engine work. The resolved handle echoes on the execute result
for UI session routing. Run-history rows gain a bounded ``session`` projection
that carries a validated owner conversation reference only when the stored row
supplies one; legacy rows (which persist no reference) project ``session: null``
rather than a fabricated session. Persisting per-run linkage would require a
separately justified storage migration and is deliberately NOT part of Phase A.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
)

from .auth_routes import auth_ready, current_user_id
from .control_plane_identity_shadow import (
    IdentityShadowRecord,
    IdentityShadowStore,
    CurrentCanonicalSessionAuthority,
    resolve_refreshed_session,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation
from .history import (
    MAX_CLAW_RUNS,
    MAX_RUN_RESULT_SUMMARY_CHARS,
    HistoryStore,
    validate_conversation_id,
)
from .usage_gate import UsageGate
from kagent.document_export import (
    DocumentExportError,
    GeneratedDocumentArtifact,
    build_document_artifact,
)
from kagent.manual_intake import (
    ContractError,
    ManualIntakeAction,
    ManualIntakeChannel,
    ManualIntakeRequest,
    ManualIntakeRouter,
)
from kagent.ops_quote_compare_flow import (
    COMPARISON_DOCUMENT_TYPE,
    OpsQuoteCompareFlowError,
    build_comparison_document,
    compare_supplier_quotes,
)
from kagent.p01_adapter import (
    P01AdapterError,
    P01CoreOrchestrationAdapter,
    P01DispatchClass,
    P01ProjectionError,
    P01_FAILURE_DETAIL_CONTRACT,
    P01_FAILURE_DETAIL_DOWNSTREAM,
    P01_FAILURE_DETAIL_TRANSPORT,
    P01_FAILURE_DETAIL_UNKNOWN,
    P01_FAILURE_DETAILS,
)
from kagent.p01_run_flow import create_claw_run
from .worker_config import P01_COMPOSITION_DIAGNOSTICS
from .workspace_storage import WorkspaceStorageAccessError, WorkspaceStorageError

MAX_MANUAL_INTAKE_BODY_BYTES = 64 * 1024  # 64 KiB
MAX_CONTENT_CHARS = 4_000
MAX_SENDER_CHARS = 120

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_ACTION_MAP: dict[str, ManualIntakeAction] = {
    "quote": ManualIntakeAction.QUOTE_DRAFT,
    "order": ManualIntakeAction.ORDER_DRAFT,
    "reply": ManualIntakeAction.REPLY_DRAFT,
    "summary": ManualIntakeAction.SUMMARIZE_REQUEST,
    "quote_draft": ManualIntakeAction.QUOTE_DRAFT,
    "order_draft": ManualIntakeAction.ORDER_DRAFT,
    "reply_draft": ManualIntakeAction.REPLY_DRAFT,
    "summarize_request": ManualIntakeAction.SUMMARIZE_REQUEST,
    "extract_candidates": ManualIntakeAction.EXTRACT_CANDIDATES,
}

_BROWSER_TIER_MAP: dict[str, ProductTierLabel] = {
    "plus": ProductTierLabel.PLUS,
    "pro": ProductTierLabel.PRO,
    "max": ProductTierLabel.MAX,
}

_CHANNEL_MAP: dict[str, ManualIntakeChannel] = {
    "kakao": ManualIntakeChannel.KAKAO,
    "sms": ManualIntakeChannel.SMS,
    "email": ManualIntakeChannel.EMAIL,
    "telegram": ManualIntakeChannel.TELEGRAM,
    "discord": ManualIntakeChannel.DISCORD,
    "other": ManualIntakeChannel.OTHER,
}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


_P01_CONTRACT_ERROR_CODES = frozenset(
    {
        "invalid_p01_result",
        "incomplete_p01_lifecycle",
        "p01_contract_failure",
        "p01_result_correlation_mismatch",
        "unsupported_result_field",
        "unsupported_result_approval_pause",
    }
)
_P01_DOWNSTREAM_ERROR_CODES = frozenset(
    {"p01_engine_request_failed", "engine_unavailable"}
)
_P01_TRANSPORT_ERROR_CODES = frozenset(
    {"p01_engine_unreachable", "p01_engine_response_too_large", "p01_engine_url_invalid"}
)


def _safe_engine_failure_detail(exc: P01AdapterError) -> str:
    """Project only the closed failure vocabulary to the public route."""
    if exc.failure_detail in P01_FAILURE_DETAILS:
        return exc.failure_detail
    if isinstance(exc, P01ProjectionError) or exc.code in _P01_CONTRACT_ERROR_CODES:
        return P01_FAILURE_DETAIL_CONTRACT
    if exc.code in _P01_TRANSPORT_ERROR_CODES:
        return P01_FAILURE_DETAIL_TRANSPORT
    if exc.code in _P01_DOWNSTREAM_ERROR_CODES:
        return P01_FAILURE_DETAIL_DOWNSTREAM
    return P01_FAILURE_DETAIL_UNKNOWN


def _safe_composition_diagnostic(request: Request) -> str:
    """Return the bounded P01 composition diagnostic for a public 503 (#2413).

    Only a value from the closed allowlist is ever projected; anything else
    (including an unset state) degrades to ``composition_unavailable``. The
    generic ``engine_not_configured`` code is preserved unchanged for existing
    clients; the diagnostic rides in a separate bounded ``detail`` field.
    """
    diagnostic = getattr(request.app.state, "claw_p01_composition_diagnostic", None)
    if isinstance(diagnostic, str) and diagnostic in P01_COMPOSITION_DIAGNOSTICS:
        return diagnostic
    return "composition_unavailable"


_WORKSPACE_READ_DETAIL_METADATA_INVALID = "metadata_invalid"
_WORKSPACE_READ_DETAIL_R2_READ_FAILED = "r2_read_failed"
_WORKSPACE_READ_DETAIL_BYTE_LENGTH_MISMATCH = "byte_length_mismatch"
_WORKSPACE_READ_DETAIL_UNKNOWN = "storage_unknown"


def _safe_workspace_read_failure_detail(exc: Exception) -> str:
    """Project storage read failures to a closed, non-secret public vocabulary."""
    if not isinstance(exc, WorkspaceStorageError):
        return _WORKSPACE_READ_DETAIL_UNKNOWN
    return {
        "workspace document metadata is invalid": _WORKSPACE_READ_DETAIL_METADATA_INVALID,
        "workspace document read failed": _WORKSPACE_READ_DETAIL_R2_READ_FAILED,
        "workspace document length mismatch": _WORKSPACE_READ_DETAIL_BYTE_LENGTH_MISMATCH,
    }.get(str(exc), _WORKSPACE_READ_DETAIL_UNKNOWN)

def _usage_denied_response(decision) -> JSONResponse:
    headers = dict(_NO_STORE_HEADERS)
    if decision.retry_after_seconds is not None:
        headers["Retry-After"] = str(decision.retry_after_seconds)
    return JSONResponse(
        {"ok": False, "error": {"code": decision.code, "message": decision.user_message}},
        status_code=decision.status_code,
        headers=headers,
    )


async def _usage_gate_denial(request: Request) -> JSONResponse | None:
    """Server-derived B62 usage gate for the real-execution path.

    Identity comes only from the signed-in session cookie and the trusted
    edge IP header; nothing in the request body can supply or override it.
    Returns a bounded product-safe response when denied, otherwise None.
    """
    if not getattr(request.app.state, "usage_gate_enforced", False):
        return None
    uid = current_user_id(request) if auth_ready(request) else None
    usage_gate: UsageGate = request.app.state.usage_gate
    decision = await usage_gate.authorize(
        raw_ip=request.headers.get("cf-connecting-ip"),
        user_id=uid,
    )
    return _usage_denied_response(decision) if not decision.allowed else None


async def _resolve_canonical_tenant(request: Request) -> str | None:
    """Resolve the canonical tenant_id from the signed-in session.

    Flow:
        signed-in user_id → identity shadow → Control Plane session refresh
        → shared canonical contract validation (RefreshingCanonicalSubjectResolver
        contract: session id, chat product id, USER subject, canonical subject
        id, monotonic revision, ACTIVE effective state, snapshot type)
        → AuthSessionSnapshot.tenant_id

    The tenant is returned only when every contract check passes; any
    violation (revoked, expired, product/subject mismatch, revision rollback,
    invalid snapshot) resolves to None and the caller fails closed.
    """
    if not auth_ready(request):
        return None
    product_user_id = current_user_id(request)
    if not product_user_id:
        return None
    shadow_store: IdentityShadowStore | None = getattr(
        request.app.state, "identity_shadow_store", None
    )
    authority: CurrentCanonicalSessionAuthority | None = getattr(
        request.app.state, "control_plane_identity_authority", None
    )
    if shadow_store is None or authority is None:
        return None
    try:
        session = await resolve_refreshed_session(
            authority=authority,
            store=shadow_store,
            product_user_id=product_user_id,
        )
    except Exception:
        return None
    tenant_id = session.tenant_id
    if not isinstance(tenant_id, str) or not tenant_id:
        return None
    return tenant_id


async def _resolve_intake_session_reference(
    request: Request, data: dict[str, Any]
) -> tuple[str | None, JSONResponse | None]:
    """Resolve the optional canonical conversation/session reference (#2829).

    The reference reuses the existing conversation authority itself: the same
    ``validate_conversation_id`` shape validator and the same owner-scoped
    ``get_conversation`` lookup the chat routes use — no new session, account,
    or workspace authority. A non-owner or missing conversation is the same
    non-disclosing ``conversation_not_found`` projection used elsewhere; the
    caller stops before any quota decision, tenant resolution, or P01/Engine
    dispatch. Carrying no reference keeps legacy execute behavior byte-for-byte
    identical.
    """
    raw = data.get("conversation_id")
    if raw is None:
        return None, None
    try:
        candidate = validate_conversation_id(raw)
    except ValueError:
        return None, _error(400, "invalid_conversation_id", "대화 세션 참조 형식이 올바르지 않습니다.")
    if candidate is None:
        return None, None
    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return None, _error(401, "unauthorized", "세션 참조를 확인하려면 로그인이 필요합니다.")
    store: HistoryStore | None = getattr(request.app.state, "history_store", None)
    get_conversation = getattr(store, "get_conversation", None) if store is not None else None
    if not callable(get_conversation):
        return None, _error(503, "conversation_authority_unavailable", "대화 세션 권한을 확인할 수 없습니다.")
    try:
        conversation = get_conversation(uid, candidate)
        if inspect.isawaitable(conversation):
            conversation = await conversation
    except Exception:
        return None, _error(503, "conversation_authority_unavailable", "대화 세션 권한을 확인할 수 없습니다.")
    if not isinstance(conversation, dict) or conversation.get("id") != candidate:
        return None, _error(404, "conversation_not_found", "대화를 찾을 수 없습니다.")
    return candidate, None


async def claw_manual_intake_preview(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")

    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_MANUAL_INTAKE_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return _error(400, "invalid_content", "요청 원문을 입력해 주세요.")
    content_clean = content.strip()
    if len(content_clean) > MAX_CONTENT_CHARS:
        return _error(400, "content_too_long", f"요청 원문은 {MAX_CONTENT_CHARS}자 이하로 입력해 주세요.")

    raw_channel = str(data.get("channel") or "other").strip().lower()
    channel = _CHANNEL_MAP.get(raw_channel)
    if channel is None:
        return _error(400, "invalid_channel", f"지원되지 않는 채널입니다: {raw_channel}")

    raw_action = str(data.get("action") or "quote").strip().lower()
    action = _ACTION_MAP.get(raw_action)
    if action is None:
        return _error(400, "invalid_action", f"지원되지 않는 작업입니다: {raw_action}")

    sender_hint: str | None = None
    if "sender_hint" in data and data["sender_hint"] is not None:
        raw_sender = str(data["sender_hint"]).strip()
        if len(raw_sender) > MAX_SENDER_CHARS:
            return _error(400, "sender_hint_too_long", f"발신자 힌트는 {MAX_SENDER_CHARS}자 이하로 입력해 주세요.")
        sender_hint = raw_sender or None

    req_id = f"prev_{uuid.uuid4().hex[:12]}"
    workspace_id = "preview_ephemeral_workspace"

    try:
        intake_req = ManualIntakeRequest(
            request_id=req_id,
            workspace_id=workspace_id,
            channel=channel,
            action=action,
            raw_content=content_clean,
            sender_hint=sender_hint,
            requested_format="md",
        )
        router = ManualIntakeRouter()
        intake_result = router.process(intake_req)
    except ContractError as exc:
        return _error(400, "contract_violation", str(exc))
    except Exception as exc:
        return _error(500, "preview_generation_failed", "미리보기 생성에 실패했습니다.")

    safe_projection = intake_result.safe_dict()

    return JSONResponse(
        {
            "ok": True,
            "preview": {
                "request_id": safe_projection["request_id"],
                "channel": safe_projection["channel"],
                "action": safe_projection["action"],
                "title": safe_projection["title"],
                "result_text": safe_projection["result_text"],
                "disabled_actions": safe_projection["disabled_actions"],
                "memory_proposals": safe_projection["memory_proposals"],
                "direct_kakao_send": False,
                "direct_sms_send": False,
                "connector_required": False,
            },
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_manual_intake_execute(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")

    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_MANUAL_INTAKE_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return _error(400, "invalid_content", "요청 원문을 입력해 주세요.")
    content_clean = content.strip()
    if len(content_clean) > MAX_CONTENT_CHARS:
        return _error(400, "content_too_long", f"요청 원문은 {MAX_CONTENT_CHARS}자 이하로 입력해 주세요.")

    raw_channel = str(data.get("channel") or "other").strip().lower()
    channel = _CHANNEL_MAP.get(raw_channel)
    if channel is None:
        return _error(400, "invalid_channel", f"지원되지 않는 채널입니다: {raw_channel}")

    raw_action = str(data.get("action") or "quote").strip().lower()
    action = _ACTION_MAP.get(raw_action)
    if action is None:
        return _error(400, "invalid_action", f"지원되지 않는 작업입니다: {raw_action}")

    sender_hint: str | None = None
    if "sender_hint" in data and data["sender_hint"] is not None:
        raw_sender = str(data["sender_hint"]).strip()
        if len(raw_sender) > MAX_SENDER_CHARS:
            return _error(400, "sender_hint_too_long", f"발신자 힌트는 {MAX_SENDER_CHARS}자 이하로 입력해 주세요.")
        sender_hint = raw_sender or None

    raw_tier = data.get("tier", "plus")
    if not isinstance(raw_tier, str):
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    product_tier = _BROWSER_TIER_MAP.get(raw_tier.strip().lower())
    if product_tier is None:
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    try:
        tier_route = active_route_for(product_tier)
    except ProductTierRoutesError:
        return _error(503, "tier_unavailable", "AI 등급 설정을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if tier_route is None or not tier_route.model_id:
        return _error(503, "tier_unavailable", "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.")

    try:
        intake_req = ManualIntakeRequest(
            request_id=f"exec_{uuid.uuid4().hex[:12]}",
            workspace_id="execute_ephemeral_workspace",
            channel=channel,
            action=action,
            raw_content=content_clean,
            sender_hint=sender_hint,
            requested_format="md",
        )
        router = ManualIntakeRouter()
        router.process(intake_req)
    except ContractError as exc:
        return _error(400, "contract_violation", str(exc))
    except Exception as exc:
        return _error(400, "invalid_input", str(exc))

    # Canonical session reference (#2829): resolved through the conversation
    # authority itself, and it fails closed before quota, tenant, or dispatch.
    session_conversation_id, session_error = await _resolve_intake_session_reference(
        request, data
    )
    if session_error is not None:
        return session_error

    # Artifact-producing actions require canonical tenant + storage authority
    # before quota consumption or any P01/Engine/B14 dispatch (#2583).
    artifact_tenant_id: str | None = None
    artifact_store: Any = None
    if action in (ManualIntakeAction.QUOTE_DRAFT, ManualIntakeAction.ORDER_DRAFT):
        artifact_tenant_id = await _resolve_canonical_tenant(request)
        if artifact_tenant_id is None:
            return _error(
                503,
                "workspace_scope_unavailable",
                "문서 저장 권한을 확인할 수 없습니다.",
            )
        artifact_store = getattr(request.app.state, "workspace_document_store", None)
        if artifact_store is None:
            return _error(
                503,
                "workspace_storage_unavailable",
                "문서 저장소가 설정되지 않았습니다.",
            )

    denial = await _usage_gate_denial(request)
    if denial is not None:
        return denial

    adapter: P01CoreOrchestrationAdapter | None = getattr(
        request.app.state, "claw_p01_adapter", None
    )
    if adapter is None:
        # No composed transport exists, so the consumed authorization is
        # provably un-dispatched: compensate the exact receipt (#2226).
        await _refund_active_reservation()
        # Public code stays the generic ``engine_not_configured`` for existing
        # clients; the bounded non-secret ``detail`` distinguishes why the
        # composition failed closed (#2413).
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

    task_text = _build_execute_task(action, content_clean)
    run = create_claw_run("padiem-chat", task_text)

    try:
        outcome = await adapter.execute(run, product_tier=product_tier)
    except P01AdapterError as exc:
        # Canonical #830 invariant: refund only when B62 can prove the Engine
        # call was never dispatched. Dispatched/ambiguous failures stay counted.
        if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
            await _refund_active_reservation()
        else:
            _clear_reservation()
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
            headers=_NO_STORE_HEADERS,
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

    if outcome.projection.status.value != "completed" or not outcome.answer:
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

    title = f"[{channel.value.upper()}] {action.value}: {sender_hint or '미지정'}"

    # Artifact authority was preflighted before quota/P01 dispatch above.
    artifact_descriptor: dict[str, Any] | None = None
    if artifact_tenant_id is not None and artifact_store is not None:
        try:
            artifact = build_document_artifact(
                document_type=action.value.replace("_draft", ""),
                file_format="docx",
                title=title,
                metadata_fields=[
                    ("채널", channel.value),
                    ("작업", action.value),
                    ("발신자", sender_hint or "미지정"),
                ],
                section_title=f"실행 결과 — {action.value}",
                body_text=outcome.answer or "",
                items=[],
                total="",
                markdown_fallback_text=outcome.answer or "",
            )
            metadata = await artifact_store.put_generated_docx(
                tenant_id=artifact_tenant_id,
                filename=artifact.filename,
                body=artifact.content_bytes(),
            )
            artifact_descriptor = metadata.public_projection()
        except DocumentExportError:
            return _error(
                500,
                "artifact_generation_failed",
                "문서 아티팩트 생성에 실패했습니다.",
            )
        except Exception:
            return _error(
                500,
                "artifact_storage_failed",
                "문서 저장에 실패했습니다.",
            )

    result: dict[str, Any] = {
        "request_id": run.run_id,
        "channel": channel.value,
        "action": action.value,
        "title": title,
        "result_text": outcome.answer,
        "status": outcome.projection.status.value,
        "p01_run_id": outcome.p01_run_id,
        "p01_event_count": outcome.p01_event_count,
        "direct_kakao_send": False,
        "direct_sms_send": False,
        "connector_required": False,
    }
    if artifact_descriptor is not None:
        result["artifact"] = artifact_descriptor
    if session_conversation_id is not None:
        # Bounded canonical session handle for UI session routing only; a
        # validated conversation id, never an internal storage row/user id.
        result["conversation_id"] = session_conversation_id

    history_failure = await _record_claw_run_history(
        request,
        run_id=run.run_id,
        channel=channel.value,
        action=action.value,
        title=title,
        status=outcome.projection.status.value,
        result_text=outcome.answer,
        artifact=artifact_descriptor,
        conversation_id=session_conversation_id,
    )
    if history_failure is not None:
        return history_failure

    return JSONResponse(
        {"ok": True, "result": result},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_manual_intake_artifact(request: Request) -> JSONResponse | Response:
    document_id = request.path_params.get("document_id", "")
    if not document_id or not re.match(r"^doc_[A-Za-z0-9]{32}$", document_id):
        return _error(400, "invalid_document_id", "잘못된 문서 ID입니다.")

    tenant_id = await _resolve_canonical_tenant(request)
    if tenant_id is None:
        return _error(401, "workspace_scope_unavailable", "인증 세션이 필요합니다.")

    workspace_store: Any = getattr(request.app.state, "workspace_document_store", None)
    if workspace_store is None:
        return _error(503, "workspace_storage_unavailable", "문서 저장소가 설정되지 않았습니다.")

    try:
        result = await workspace_store.get_for_tenant(
            tenant_id=tenant_id,
            document_id=document_id,
        )
    except WorkspaceStorageAccessError:
        # #2308: a canonical-tenant denial must be observationally identical to
        # a missing artifact. Returning 503 here disclosed that a foreign
        # document id exists; the same 404 body removes that oracle. The store
        # still raises (tenant enforcement unchanged) — only the projection is
        # normalized.
        return _error(404, "artifact_not_found", "아티팩트를 찾을 수 없습니다.")
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": {
                    "code": "workspace_document_read_failed",
                    "message": "문서 읽기 중 오류가 발생했습니다.",
                    "detail": _safe_workspace_read_failure_detail(exc),
                },
            },
            status_code=503,
            headers=_NO_STORE_HEADERS,
        )

    if result is None:
        return _error(404, "artifact_not_found", "아티팩트를 찾을 수 없습니다.")

    metadata, content = result
    import urllib.parse as _urllib_parse

    return Response(
        content,
        status_code=200,
        headers={
            "Content-Type": metadata.media_type,
            "Content-Disposition": f"attachment; filename*=UTF-8''{_urllib_parse.quote(metadata.filename)}",
            "Cache-Control": "no-store, max-age=0",
            "Content-Length": str(len(content)),
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _record_claw_run_history(
    request: Request,
    *,
    run_id: str,
    channel: str,
    action: str,
    title: str,
    status: str,
    result_text: str | None,
    artifact: dict[str, Any] | None,
    conversation_id: str | None = None,
) -> JSONResponse | None:
    """Persist a bounded owner-scoped run history row (#2317, #2829).

    Fail-closed: a store that advertises ``record_claw_run`` but raises is a
    storage failure and returns a stable public-safe 503 so the caller never
    sees a success that silently dropped history. A store that does not
    implement the capability (a presence-only auth stub) is a no-op, and an
    anonymous run has no owner to record against, so both return ``None``.

    #2829 Phase B: the optional ``conversation_id`` is the already-validated
    canonical conversation handle from ``_resolve_intake_session_reference``.
    It is persisted only when the caller carried a reference that passed the
    existing canonical conversation authority; otherwise ``None`` keeps legacy
    rows at ``session: null``. No new session authority is created.
    """
    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return None
    history_store = getattr(request.app.state, "history_store", None)
    record = getattr(history_store, "record_claw_run", None)
    if record is None:
        return None
    summary = result_text[:MAX_RUN_RESULT_SUMMARY_CHARS] if result_text else None
    try:
        outcome_record = record(
            user_id=uid,
            run_id=run_id,
            channel=channel,
            action=action,
            title=title,
            status=status,
            result_summary=summary,
            artifact_document_id=artifact.get("document_id") if artifact else None,
            artifact_filename=artifact.get("filename") if artifact else None,
            artifact_media_type=artifact.get("media_type") if artifact else None,
            conversation_id=conversation_id,
        )
        if inspect.isawaitable(outcome_record):
            await outcome_record
    except Exception:
        return _error(503, "run_history_write_failed", "실행 이력 저장에 실패했습니다.")
    return None


async def claw_runs_history(request: Request) -> JSONResponse:
    """Owner-scoped bounded recent run history (#2317).

    Identity is server-derived only; a caller can never list another owner's
    runs because every read is filtered by the session user id, and a
    non-owner ``run_id`` is not distinguishable from a missing one.
    """
    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")

    history_store = getattr(request.app.state, "history_store", None)
    list_runs = getattr(history_store, "list_recent_claw_runs", None)
    if list_runs is None:
        return _error(503, "run_history_unavailable", "실행 이력을 사용할 수 없습니다.")

    raw_limit = request.query_params.get("limit")
    try:
        limit = MAX_CLAW_RUNS if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit 는 정수여야 합니다.")
    if limit < 1:
        return _error(400, "invalid_limit", "limit 는 1 이상이어야 합니다.")

    try:
        runs = list_runs(uid, limit)
        if inspect.isawaitable(runs):
            runs = await runs
    except Exception:
        return _error(503, "run_history_read_failed", "실행 이력 읽기에 실패했습니다.")
    if not isinstance(runs, list):
        return _error(503, "run_history_read_failed", "실행 이력 읽기에 실패했습니다.")
    return JSONResponse({"ok": True, "runs": runs}, status_code=200, headers=_NO_STORE_HEADERS)


def _build_execute_task(action: ManualIntakeAction, content: str) -> str:
    action_prompts: dict[ManualIntakeAction, str] = {
        ManualIntakeAction.QUOTE_DRAFT: f"다음 요청에 대한 견적서 초안을 작성하세요.\n\n{content}",
        ManualIntakeAction.ORDER_DRAFT: f"다음 요청에 대한 발주서 초안을 작성하세요.\n\n{content}",
        ManualIntakeAction.REPLY_DRAFT: f"다음 요청에 대한 답장을 작성하세요.\n\n{content}",
        ManualIntakeAction.SUMMARIZE_REQUEST: f"다음 요청을 요약하세요.\n\n{content}",
        ManualIntakeAction.EXTRACT_CANDIDATES: f"다음 요청에서 후보 정보를 추출하세요.\n\n{content}",
    }
    return action_prompts.get(action, content)


# ── #2812 deterministic supplier quote comparison + draft-only negotiation ───

_QUOTE_COMPARE_ARTIFACT_FORMATS = frozenset({"docx"})


async def claw_manual_intake_quote_compare(request: Request) -> JSONResponse:
    """Compare captured supplier quotes with the existing Claw Ops engine (#2812).

    This route closes the product-wiring gap found in the Claw Ops audit: the
    deterministic ``SupplierComparisonEngine`` already existed with no HTTP
    surface. Authority stays where it already is — the engine decides price,
    delivery and payment-terms ranking, and the negotiation target is bounded by
    another captured quote. Nothing here reaches a model, provider, quota
    reservation or outbound connector, and the comparison itself persists nothing:

    - no ``claw_p01_adapter`` / ``create_claw_run`` / Engine / B14 dispatch, and
      deliberately no usage-gate call because nothing is dispatched;
    - storing the result is opt-in. With no ``artifact`` field the route writes
      nothing at all; with ``artifact="docx"`` it writes through the existing
      generated-document store -- the same D1 metadata plus private R2 bytes the
      execute route already uses -- and the existing
      ``GET /api/claw/manual-intake/artifact/{document_id}`` path serves it back.
      That is the only persistence on this route: no new table, no migration and
      no Claw Ops ledger write, and it needs the same canonical tenant authority
      as the execute route, failing closed without it;
    - a value the caller did not capture stays ``null`` plus an engine
      ``unknown_fields`` entry; the flow never fills a price, date or term in.

    Malformed, empty and over-bound input fails closed with the flow's own
    bounded code vocabulary.
    """
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")

    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_MANUAL_INTAKE_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    raw_artifact = data.get("artifact")
    artifact_format: str | None = None
    if raw_artifact not in (None, False, ""):
        if not isinstance(raw_artifact, str) or raw_artifact.strip().lower() not in (
            _QUOTE_COMPARE_ARTIFACT_FORMATS
        ):
            return _error(400, "invalid_artifact_format", "저장 가능한 비교 문서 형식은 DOCX 입니다.")
        artifact_format = raw_artifact.strip().lower()

    try:
        outcome = compare_supplier_quotes(data)
    except OpsQuoteCompareFlowError as exc:
        return _error(400, exc.error_code, exc.public_message)
    except ContractError:
        return _error(400, "contract_violation", "견적 입력을 비교할 수 없습니다.")
    except Exception:
        return _error(500, "quote_compare_failed", "견적 비교에 실패했습니다.")

    comparison = outcome.safe_dict()
    projection = {"ok": True, "comparison": comparison}

    if artifact_format is not None:
        tenant_id = await _resolve_canonical_tenant(request)
        if tenant_id is None:
            return _error(503, "workspace_scope_unavailable", "문서 저장 권한을 확인할 수 없습니다.")
        artifact_store: Any = getattr(request.app.state, "workspace_document_store", None)
        if artifact_store is None:
            return _error(503, "workspace_storage_unavailable", "문서 저장소가 설정되지 않았습니다.")
        try:
            document_text = build_comparison_document(outcome)
            artifact = build_document_artifact(
                document_type=COMPARISON_DOCUMENT_TYPE,
                file_format=artifact_format,
                title=outcome.document_title(),
                metadata_fields=[
                    ("비교 모드", comparison["mode"]),
                    (
                        "가중치",
                        "가격 {price} / 납기 {delivery} / 결제조건 {cashflow}".format(
                            **comparison["weights"]
                        ),
                    ),
                    ("통화", comparison["currency"]),
                    ("비교 공급업체 수", str(comparison["supplier_count"])),
                    ("추천 공급업체", comparison["recommended_supplier_label"]),
                    ("협상 초안", "작성됨 (DRAFT ONLY)" if comparison["negotiation"] else "미작성"),
                ],
                section_title="공급업체 견적 비교",
                body_text=document_text,
                items=outcome.document_table(),
                total=outcome.document_total(),
                markdown_fallback_text=document_text,
            )
            metadata = await artifact_store.put_generated_docx(
                tenant_id=tenant_id,
                filename=artifact.filename,
                body=artifact.content_bytes(),
            )
            projection["artifact"] = metadata.public_projection()
        except DocumentExportError:
            return _error(500, "artifact_generation_failed", "문서 아티팩트 생성에 실패했습니다.")
        except Exception:
            return _error(500, "artifact_storage_failed", "문서 저장에 실패했습니다.")

    return JSONResponse(projection, status_code=200, headers=_NO_STORE_HEADERS)
