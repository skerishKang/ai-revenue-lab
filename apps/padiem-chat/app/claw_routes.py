"""Claw Manual Intake Preview + Real Execution Routes (#2086 / #2215).

Provides:
- POST /api/claw/manual-intake/preview — deterministic preview (existing)
- POST /api/claw/manual-intake/execute — real P01/Engine-backed execution (#2215)

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
"""

from __future__ import annotations

import json
import re
from typing import Any
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .control_plane_identity_shadow import (
    IdentityShadowRecord,
    IdentityShadowStore,
    CurrentCanonicalSessionAuthority,
    resolve_refreshed_session,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation
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
from kagent.p01_adapter import P01AdapterError, P01CoreOrchestrationAdapter, P01DispatchClass
from kagent.p01_run_flow import create_claw_run
from .workspace_storage import WorkspaceStorageAccessError

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
        return _error(503, "engine_not_configured", "Engine 클라이언트가 설정되지 않았습니다.")

    task_text = _build_execute_task(action, content_clean)
    run = create_claw_run("padiem-chat", task_text)

    try:
        outcome = await adapter.execute(run)
    except P01AdapterError as exc:
        # Canonical #830 invariant: refund only when B62 can prove the Engine
        # call was never dispatched. Dispatched/ambiguous failures stay counted.
        if exc.dispatch_class == P01DispatchClass.NOT_DISPATCHED:
            await _refund_active_reservation()
        else:
            _clear_reservation()
        return _error(502, "engine_execution_failed", "Engine 실행에 실패했습니다.")
    except Exception:
        _clear_reservation()
        return _error(502, "engine_execution_failed", "Engine 실행에 실패했습니다.")
    _clear_reservation()

    if outcome.projection.status.value != "completed" or not outcome.answer:
        return _error(502, "engine_execution_failed", "Engine 실행이 완료되지 않았습니다.")

    title = f"[{channel.value.upper()}] {action.value}: {sender_hint or '미지정'}"

    # Artifact-producing actions (quote/order) require canonical tenant resolution.
    artifact_descriptor: dict[str, Any] | None = None
    if action in (ManualIntakeAction.QUOTE_DRAFT, ManualIntakeAction.ORDER_DRAFT):
        tenant_id = await _resolve_canonical_tenant(request)
        if tenant_id is None:
            return _error(
                503,
                "workspace_scope_unavailable",
                "문서 저장 권한을 확인할 수 없습니다.",
            )
        workspace_store: Any = getattr(request.app.state, "workspace_document_store", None)
        if workspace_store is None:
            return _error(
                503,
                "workspace_storage_unavailable",
                "문서 저장소가 설정되지 않았습니다.",
            )
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
            metadata = await workspace_store.put_generated_docx(
                tenant_id=tenant_id,
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
    except Exception:
        return _error(503, "workspace_document_read_failed", "문서 읽기 중 오류가 발생했습니다.")

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


def _build_execute_task(action: ManualIntakeAction, content: str) -> str:
    action_prompts: dict[ManualIntakeAction, str] = {
        ManualIntakeAction.QUOTE_DRAFT: f"다음 요청에 대한 견적서 초안을 작성하세요.\n\n{content}",
        ManualIntakeAction.ORDER_DRAFT: f"다음 요청에 대한 발주서 초안을 작성하세요.\n\n{content}",
        ManualIntakeAction.REPLY_DRAFT: f"다음 요청에 대한 답장을 작성하세요.\n\n{content}",
        ManualIntakeAction.SUMMARIZE_REQUEST: f"다음 요청을 요약하세요.\n\n{content}",
        ManualIntakeAction.EXTRACT_CANDIDATES: f"다음 요청에서 후보 정보를 추출하세요.\n\n{content}",
    }
    return action_prompts.get(action, content)
