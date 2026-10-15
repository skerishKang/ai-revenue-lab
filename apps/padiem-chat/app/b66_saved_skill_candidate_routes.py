"""B66 #3186 — authenticated Saved Quote Skill *candidate* (approval request) routes.

Normal customer runtime:
signed-in Padiem owner -> direct-entry candidate -> bounded submission -> durable
``pending`` approval request -> trusted operator review -> approved Saved Quote Skill.

What this module deliberately does **not** provide:
- no customer-facing approve/reject route. A customer can only *request* approval.
  Any owner/approval status supplied by the browser is rejected, so a client
  cannot self-approve or impersonate an operator.
- no source quotation parsing, no server-side totals calculation, no template
  mutation, no arbitrary tenant selection.

Ownership is always derived from the server session; the workspace is resolved
server-side exactly like the other account-scoped B66 routes.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .b66_saved_skill_candidate_review import (
    B66CandidateReviewError,
    B66SavedQuoteSkillCandidateReviewer,
)
from .b66_quote_skill_provisioning import TrustedB66ProvisioningGrant, ResolvedB66ProvisioningTarget
from .b66_saved_skill_candidate_store import (
    CANDIDATE_STATUSES,
    MAX_CANDIDATES,
    SavedQuoteSkillCandidateStoreError,
    canonicalize_candidate_submission,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_memory_routes import _resolve_memory_workspace

MAX_BODY_BYTES = 16 * 1024
MAX_LIST_LIMIT = MAX_CANDIDATES
_ALLOWED_SUBMIT_FIELDS = frozenset({"client_ref", "candidate"})
_FORBIDDEN_OWNER_KEYS = frozenset(
    {"user_id", "userId", "tenant_id", "tenantId", "workspace_id", "workspaceId", "owner"}
)
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE,
    )


def _store(request: Request) -> Any | None:
    return getattr(request.app.state, "b66_saved_skill_candidate_store", None)


def _saved_skill_store(request: Request) -> Any | None:
    return getattr(request.app.state, "b66_saved_quote_skill_store", None)


def _reviewer(request: Request) -> Any | None:
    reviewer = getattr(request.app.state, "b66_quote_skill_candidate_reviewer", None)
    if reviewer is not None:
        return reviewer
    candidate_store = _store(request)
    skill_store = _saved_skill_store(request)
    if candidate_store is None or skill_store is None:
        return None
    try:
        return B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)
    except Exception:
        return None


async def _trusted_grant(request: Request) -> TrustedB66ProvisioningGrant | None:
    resolver = getattr(request.app.state, "b66_operator_grant_resolver", None)
    if not callable(resolver):
        resolver = getattr(request.app.state, "b66_provisioning_grant_resolver", None)
    if not callable(resolver):
        return None
    try:
        value = resolver(request)
        if inspect.isawaitable(value):
            value = await value
    except Exception:
        return None
    return value if isinstance(value, TrustedB66ProvisioningGrant) else None


async def _resolved_target(request: Request, candidate_id: str) -> ResolvedB66ProvisioningTarget | None:
    resolver = getattr(request.app.state, "b66_operator_target_resolver", None)
    if not callable(resolver):
        resolver = getattr(request.app.state, "b66_provisioning_target_resolver", None)
    if not callable(resolver):
        return None
    try:
        value = resolver(request, candidate_id)
        if inspect.isawaitable(value):
            value = await value
    except Exception:
        return None
    return value if isinstance(value, ResolvedB66ProvisioningTarget) else None


async def _owner_and_workspace(request: Request) -> tuple[str, str] | None:
    if not auth_ready(request):
        return None
    try:
        uid = current_user_id(request)
    except Exception:
        return None
    if not uid:
        return None
    workspace_id = await _resolve_memory_workspace(request, uid)
    if not workspace_id:
        return None
    return uid, workspace_id


async def _json(request: Request) -> dict[str, Any] | JSONResponse:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_BODY_BYTES)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    if not body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")
    if any(key in data for key in _FORBIDDEN_OWNER_KEYS):
        return _error(400, "forbidden_owner_field", "계정 범위는 서버가 결정합니다.")
    if set(data) - _ALLOWED_SUBMIT_FIELDS:
        return _error(400, "unsupported_field", "지원되지 않는 요청 필드가 있습니다.")
    return data


async def b66_saved_skill_candidate_submit(request: Request) -> JSONResponse:
    """Open one durable approval request for the signed-in owner."""

    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    store = _store(request)
    submit_fn = getattr(store, "submit", None) if store is not None else None
    if not callable(submit_fn):
        return _error(503, "candidate_store_unavailable", "승인 요청을 접수할 수 없습니다.")

    data = await _json(request)
    if isinstance(data, JSONResponse):
        return data

    try:
        submission = canonicalize_candidate_submission(
            client_ref=data.get("client_ref"),
            candidate=data.get("candidate"),
        )
    except SavedQuoteSkillCandidateStoreError:
        return _error(400, "invalid_candidate", "승인 요청 내용을 확인해 주세요.")

    try:
        value = submit_fn(user_id=uid, workspace_id=workspace_id, submission=submission)
        stored = await value if inspect.isawaitable(value) else value
    except SavedQuoteSkillCandidateStoreError:
        return _error(400, "invalid_candidate", "승인 요청 내용을 확인해 주세요.")
    except Exception:
        return _error(503, "candidate_write_failed", "승인 요청을 저장하지 못했습니다.")
    if not isinstance(stored, dict) or not stored.get("candidate_id"):
        return _error(503, "candidate_write_failed", "승인 요청을 저장하지 못했습니다.")

    return JSONResponse(
        {
            "ok": True,
            "candidate": stored,
            "duplicate": stored.get("duplicate") is True,
            # Truthful contract: this is an approval *request*. Approval authority
            # is a trusted operator action and is never granted here.
            "approval": {
                "requested": True,
                "status": stored.get("status", "pending"),
                "approved": False,
                "decided_by_customer": False,
            },
        },
        headers=_NO_STORE,
    )


async def b66_saved_skill_candidate_list(request: Request) -> JSONResponse:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    store = _store(request)
    list_fn = getattr(store, "list_candidates", None) if store is not None else None
    if not callable(list_fn):
        return _error(503, "candidate_store_unavailable", "승인 요청을 확인할 수 없습니다.")

    raw_limit = request.query_params.get("limit")
    try:
        limit = MAX_LIST_LIMIT if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit 형식이 올바르지 않습니다.")
    if limit < 1:
        return _error(400, "invalid_limit", "limit 형식이 올바르지 않습니다.")

    try:
        value = list_fn(user_id=uid, workspace_id=workspace_id, limit=min(limit, MAX_LIST_LIMIT))
        candidates = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(503, "candidate_read_failed", "승인 요청을 불러오지 못했습니다.")
    if not isinstance(candidates, list):
        return _error(503, "candidate_read_failed", "승인 요청을 불러오지 못했습니다.")
    return JSONResponse({"ok": True, "candidates": candidates}, headers=_NO_STORE)


async def b66_saved_skill_candidate_detail(request: Request) -> JSONResponse:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    candidate_id = request.path_params.get("candidate_id", "")
    store = _store(request)
    get_fn = getattr(store, "get_candidate", None) if store is not None else None
    if not callable(get_fn):
        return _error(503, "candidate_store_unavailable", "승인 요청을 확인할 수 없습니다.")

    try:
        value = get_fn(user_id=uid, workspace_id=workspace_id, candidate_id=candidate_id)
        candidate = await value if inspect.isawaitable(value) else value
    except SavedQuoteSkillCandidateStoreError:
        return _error(400, "invalid_candidate_id", "승인 요청 ID 형식이 올바르지 않습니다.")
    except Exception:
        return _error(503, "candidate_read_failed", "승인 요청을 불러오지 못했습니다.")
    if candidate is None:
        return _error(404, "candidate_not_found", "승인 요청을 찾을 수 없습니다.")
    return JSONResponse({"ok": True, "candidate": candidate}, headers=_NO_STORE)


async def b66_saved_skill_candidate_operator_list(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    try:
        uid = current_user_id(request)
    except Exception:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    if not uid:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    admin_store = getattr(request.app.state, "b66_member_admin_store", None)
    admin_fn = getattr(admin_store, "is_google_admin", None) if admin_store is not None else None
    if not callable(admin_fn):
        return _error(503, "operator_unavailable", "운영자 권한을 확인할 수 없습니다.")
    try:
        allowed = await admin_fn(uid)
    except Exception:
        return _error(503, "operator_unavailable", "운영자 권한을 확인할 수 없습니다.")
    if allowed is not True:
        return _error(403, "operator_forbidden", "운영자 권한이 없습니다.")

    store = _store(request)
    list_fn = getattr(store, "list_operator_candidates", None) if store is not None else None
    if not callable(list_fn):
        return _error(503, "candidate_store_unavailable", "승인 대기 목록을 확인할 수 없습니다.")

    raw_status = request.query_params.get("status", "pending")
    if raw_status not in CANDIDATE_STATUSES:
        return _error(400, "invalid_status", "status 형식이 올바르지 않습니다.")
    raw_limit = request.query_params.get("limit")
    try:
        limit = MAX_LIST_LIMIT if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit 형식이 올바르지 않습니다.")
    if limit < 1:
        return _error(400, "invalid_limit", "limit 형식이 올바르지 않습니다.")

    try:
        value = list_fn(status=raw_status, limit=min(limit, MAX_LIST_LIMIT))
        candidates = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(503, "candidate_read_failed", "승인 대기 목록을 불러오지 못했습니다.")
    if not isinstance(candidates, list):
        return _error(503, "candidate_read_failed", "승인 대기 목록을 불러오지 못했습니다.")
    return JSONResponse({"ok": True, "status": raw_status, "candidates": candidates}, headers=_NO_STORE)


async def b66_saved_skill_candidate_operator_detail(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    try:
        uid = current_user_id(request)
    except Exception:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    if not uid:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    admin_store = getattr(request.app.state, "b66_member_admin_store", None)
    admin_fn = getattr(admin_store, "is_google_admin", None) if admin_store is not None else None
    if not callable(admin_fn):
        return _error(503, "operator_unavailable", "운영자 권한을 확인할 수 없습니다.")
    try:
        allowed = await admin_fn(uid)
    except Exception:
        return _error(503, "operator_unavailable", "운영자 권한을 확인할 수 없습니다.")
    if allowed is not True:
        return _error(403, "operator_forbidden", "운영자 권한이 없습니다.")

    candidate_id = request.path_params.get("candidate_id", "")
    store = _store(request)
    get_fn = getattr(store, "get_operator_candidate", None) if store is not None else None
    if not callable(get_fn):
        return _error(503, "candidate_store_unavailable", "승인 요청을 확인할 수 없습니다.")
    try:
        value = get_fn(candidate_id=candidate_id)
        candidate = await value if inspect.isawaitable(value) else value
    except SavedQuoteSkillCandidateStoreError:
        return _error(400, "invalid_candidate_id", "승인 요청 ID 형식이 올바르지 않습니다.")
    except Exception:
        return _error(503, "candidate_read_failed", "승인 요청을 불러오지 못했습니다.")
    if candidate is None:
        return _error(404, "candidate_not_found", "승인 요청을 찾을 수 없습니다.")
    return JSONResponse({"ok": True, "candidate": candidate}, headers=_NO_STORE)


async def b66_saved_skill_candidate_operator_decision(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    try:
        uid = current_user_id(request)
    except Exception:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    if not uid:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    admin_store = getattr(request.app.state, "b66_member_admin_store", None)
    admin_fn = getattr(admin_store, "is_google_admin", None) if admin_store is not None else None
    if not callable(admin_fn):
        return _error(503, "operator_unavailable", "운영자 권한을 확인할 수 없습니다.")
    try:
        admin_result = admin_fn(uid)
        if inspect.isawaitable(admin_result):
            admin_result = await admin_result
        if admin_result is not True:
            return _error(403, "operator_forbidden", "운영자 권한이 없습니다.")
    except Exception:
        return _error(503, "operator_unavailable", "운영자 권한을 확인할 수 없습니다.")

    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_BODY_BYTES)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large", "요청이 너무 큽니다.")
    if not body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")
    allowed_fields = {"action", "rejection_reason"}
    if set(data) - allowed_fields:
        return _error(400, "unsupported_field", "지원되지 않는 요청 필드가 있습니다.")
    action = data.get("action")
    if action not in {"approve", "reject"}:
        return _error(400, "invalid_decision", "승인 action 형식이 올바르지 않습니다.")
    rejection_raw = data.get("rejection_reason")
    if rejection_raw is not None:
        if not isinstance(rejection_raw, str):
            return _error(400, "invalid_rejection_reason", "거부 사유 형식이 올바르지 않습니다.")
        rejection_reason = rejection_raw.strip()
    else:
        rejection_reason = None
    if len(rejection_reason or "") > 200:
        return _error(400, "invalid_rejection_reason", "거부 사유가 너무 깁니다.")

    candidate_id = request.path_params.get("candidate_id", "")
    grant = await _trusted_grant(request)
    if not isinstance(grant, TrustedB66ProvisioningGrant):
        return _error(503, "operator_grant_unavailable", "서버 신뢰 grant가 제공되지 않았습니다.")
    target = await _resolved_target(request, candidate_id)
    if not isinstance(target, ResolvedB66ProvisioningTarget):
        return _error(503, "operator_target_unavailable", "서버 대상 계정을 확인할 수 없습니다.")

    reviewer = _reviewer(request)
    if reviewer is None:
        return _error(503, "operator_reviewer_unavailable", "운영자 검토기를 사용할 수 없습니다.")

    from datetime import datetime, timezone

    try:
        receipt = await reviewer.review(
            grant=grant,
            target=target,
            candidate_id=candidate_id,
            action=action,
            now=datetime.now(timezone.utc),
            rejection_reason=rejection_reason,
        )
    except B66CandidateReviewError:
        return _error(409, "candidate_decision_conflict", "승인 요청 상태를 처리할 수 없습니다.")
    except Exception:
        return _error(503, "candidate_review_failed", "승인 요청을 처리하지 못했습니다.")

    return JSONResponse(
        {
            "ok": True,
            "candidate_id": candidate_id,
            "decision": action,
            "approval": receipt.safe_dict() if hasattr(receipt, "safe_dict") else {"action": action},
        },
        headers=_NO_STORE,
    )
