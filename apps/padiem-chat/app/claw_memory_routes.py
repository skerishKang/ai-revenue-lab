"""Explicitly user-approved Claw memory routes (#2331).

Endpoints:
- POST /api/claw/memory/approve — persist one bounded public-safe proposal
  only when the signed-in owner gives explicit approval in this request.
- POST /api/claw/memory/reject — validate the proposal shape and return
  without creating any durable row.
- GET /api/claw/memory — owner/workspace-scoped hard-bounded list.
- GET /api/claw/memory/{memory_id} — owner/workspace-scoped read with a
  non-disclosing 404 for missing vs foreign records.

All identity comes from the signed-in session and the canonical tenant
authority. Caller-supplied owner/tenant fields are forbidden. Anonymous
callers cannot approve/list/read. Storage failures fail closed.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .approved_memory import (
    ApprovedMemoryError,
    MAX_APPROVED_MEMORIES,
    canonicalize_proposal,
    validate_memory_id,
)
from .auth_routes import auth_ready, current_user_id
from .control_plane_identity_shadow import resolve_refreshed_session

MAX_MEMORY_BODY_BYTES = 64 * 1024

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_TOP_LEVEL_OWNER_KEYS = frozenset({
    "user_id", "owner", "owner_id", "tenant_id", "tenant", "workspace_id", "workspace",
})


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


async def _resolve_memory_workspace(request: Request, user_id: str) -> str:
    """Bind workspace from canonical tenant authority with an owner-derived fallback.

    When the canonical session resolves, the tenant_id is the workspace. When
    the canonical path is unavailable (no shadow/authority in this deployment),
    the workspace falls back to a server-derived per-owner value. Callers can
    never supply or override it.
    """
    tenant_id: str | None = None
    try:
        if auth_ready(request):
            shadow_store = getattr(request.app.state, "identity_shadow_store", None)
            authority = getattr(request.app.state, "control_plane_identity_authority", None)
            if shadow_store is not None and authority is not None:
                session = await resolve_refreshed_session(
                    authority=authority,
                    store=shadow_store,
                    product_user_id=user_id,
                )
                candidate = getattr(session, "tenant_id", None)
                if isinstance(candidate, str) and candidate:
                    tenant_id = candidate
    except Exception:
        tenant_id = None
    if tenant_id:
        return tenant_id
    return f"owner:{user_id}"


def _require_owner(request: Request) -> str | None:
    if not auth_ready(request):
        return None
    try:
        uid = current_user_id(request)
    except Exception:
        return None
    return uid if uid else None


async def _read_json_body(request: Request) -> dict[str, Any] | JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_MEMORY_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")
    for key in _TOP_LEVEL_OWNER_KEYS:
        if key in data:
            return _error(400, "forbidden_owner_field", "요청 데이터는 객체여야 합니다.")
    return data


def _approved_store(request: Request) -> Any | None:
    return getattr(request.app.state, "approved_memory_store", None)


async def claw_memory_approve(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    data = await _read_json_body(request)
    if isinstance(data, JSONResponse):
        return data
    # Explicit user approval is server-enforced: the body must carry an
    # affirmative approval flag alongside the echoed public-safe proposal.
    # Model output alone (no signed-in approval request) can never persist.
    if data.get("approved") is not True:
        return _error(400, "explicit_approval_required", "명시적 승인이 필요합니다.")
    try:
        proposal = canonicalize_proposal(data.get("proposal"))
    except ApprovedMemoryError:
        return _error(400, "invalid_proposal", "제안 형식이 올바르지 않습니다.")
    store = _approved_store(request)
    if store is None or getattr(store, "approve_memory", None) is None:
        return _error(503, "approved_memory_unavailable", "승인 메모리를 사용할 수 없습니다.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        outcome = store.approve_memory(user_id=uid, workspace_id=workspace_id, proposal=proposal)
        if inspect.isawaitable(outcome):
            outcome = await outcome
    except ApprovedMemoryError:
        return _error(400, "invalid_proposal", "제안 형식이 올바르지 않습니다.")
    except Exception:
        return _error(503, "approved_memory_write_failed", "승인 메모리 저장에 실패했습니다.")
    if not isinstance(outcome, dict):
        return _error(503, "approved_memory_write_failed", "승인 메모리 저장에 실패했습니다.")
    return JSONResponse({"ok": True, "memory": outcome}, status_code=200, headers=_NO_STORE_HEADERS)


async def claw_memory_reject(request: Request) -> JSONResponse:
    """Explicit rejection: validate shape, never create a durable row."""
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    data = await _read_json_body(request)
    if isinstance(data, JSONResponse):
        return data
    try:
        canonicalize_proposal(data.get("proposal"))
    except ApprovedMemoryError:
        return _error(400, "invalid_proposal", "제안 형식이 올바르지 않습니다.")
    return JSONResponse({"ok": True, "persisted": False}, status_code=200, headers=_NO_STORE_HEADERS)


async def claw_memory_list(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    store = _approved_store(request)
    list_fn = getattr(store, "list_approved_memories", None) if store is not None else None
    if list_fn is None:
        return _error(503, "approved_memory_unavailable", "승인 메모리를 사용할 수 없습니다.")
    raw_limit = request.query_params.get("limit")
    try:
        limit = MAX_APPROVED_MEMORIES if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit 는 정수여야 합니다.")
    if limit < 1:
        return _error(400, "invalid_limit", "limit 는 1 이상이어야 합니다.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        memories = list_fn(user_id=uid, workspace_id=workspace_id, limit=limit)
        if inspect.isawaitable(memories):
            memories = await memories
    except Exception:
        return _error(503, "approved_memory_read_failed", "승인 메모리 읽기에 실패했습니다.")
    if not isinstance(memories, list):
        return _error(503, "approved_memory_read_failed", "승인 메모리 읽기에 실패했습니다.")
    return JSONResponse({"ok": True, "memories": memories}, status_code=200, headers=_NO_STORE_HEADERS)


async def claw_memory_detail(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    raw_id = request.path_params.get("memory_id", "")
    try:
        memory_id = validate_memory_id(raw_id)
    except ApprovedMemoryError:
        return _error(400, "invalid_memory_id", "잘못된 메모리 ID입니다.")
    store = _approved_store(request)
    get_fn = getattr(store, "get_approved_memory", None) if store is not None else None
    if get_fn is None:
        return _error(503, "approved_memory_unavailable", "승인 메모리를 사용할 수 없습니다.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        memory = get_fn(user_id=uid, workspace_id=workspace_id, memory_id=memory_id)
        if inspect.isawaitable(memory):
            memory = await memory
    except Exception:
        return _error(503, "approved_memory_read_failed", "승인 메모리 읽기에 실패했습니다.")
    if memory is None:
        # Non-disclosing: a foreign record is observationally identical to a
        # missing one. The store enforces ownership; only this projection is
        # normalized.
        return _error(404, "approved_memory_not_found", "메모리를 찾을 수 없습니다.")
    return JSONResponse({"ok": True, "memory": memory}, status_code=200, headers=_NO_STORE_HEADERS)
