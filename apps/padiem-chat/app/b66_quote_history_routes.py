"""Authenticated B66 quotation-history routes — server authority (#3405, Slice A).

    GET    /api/b66/quotes?limit=N
    POST   /api/b66/quotes
    GET    /api/b66/quotes/{quote_history_id}
    DELETE /api/b66/quotes/{quote_history_id}

Owner and workspace are always derived from the authenticated session and the
server-owned workspace resolution. A caller-supplied owner/workspace is rejected
rather than honoured. Records owned by another account or workspace are
indistinguishable from missing records (non-disclosing fail-closed).

Slice A is server authority only: no browser-local history file is read or
written, and no historical record is mutated by this module.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .b66_quote_history_store import (
    MAX_QUOTE_HISTORY,
    MAX_QUOTE_HISTORY_LIMIT,
    QuoteHistoryStoreError,
    normalize_quote_draft_snapshot,
    validate_row_id,
)
from .claw_memory_routes import _resolve_memory_workspace

_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}

# Client-supplied ownership fields are never authority; their presence is an
# explicit contract violation rather than something silently ignored.
_CLIENT_OWNER_KEYS = {"userid", "user", "owner", "ownerid", "accountid", "tenantid",
                      "workspaceid", "workspace", "tenant"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE,
    )


async def _owner_and_workspace(request: Request) -> tuple[str, str] | None:
    if not auth_ready(request):
        return None
    try:
        uid = current_user_id(request)
    except Exception:
        return None
    if not uid:
        return None
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        return None
    if not workspace_id:
        return None
    return uid, workspace_id


def _store(request: Request) -> Any | None:
    return getattr(request.app.state, "b66_quote_history_store", None)


def _reject_client_owner(body: Any) -> bool:
    """True when the payload tries to assert its own owner/workspace."""
    if not isinstance(body, dict):
        return False
    for key in body:
        normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
        if normalized in _CLIENT_OWNER_KEYS:
            return True
    return False


async def _call(fn, **kwargs):
    value = fn(**kwargs)
    return await value if inspect.isawaitable(value) else value


def _bounded_limit(raw: object) -> int:
    if raw is None or raw == "":
        return MAX_QUOTE_HISTORY
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return MAX_QUOTE_HISTORY
    return max(1, min(value, MAX_QUOTE_HISTORY_LIMIT))


async def b66_quote_history_list(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    store = _store(request)
    list_fn = getattr(store, "list_quotes", None) if store is not None else None
    if not callable(list_fn):
        return _error(503, "quote_history_unavailable", "최근 견적을 사용할 수 없습니다.")

    limit = _bounded_limit(request.query_params.get("limit"))
    try:
        quotes = await _call(list_fn, user_id=uid, workspace_id=workspace_id, limit=limit)
    except QuoteHistoryStoreError:
        return _error(503, "quote_history_read_failed", "최근 견적을 읽지 못했습니다.")
    except Exception:
        return _error(503, "quote_history_read_failed", "최근 견적을 읽지 못했습니다.")

    return JSONResponse({"ok": True, "quotes": list(quotes or []), "limit": limit},
                        headers=_NO_STORE)


async def b66_quote_history_save(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_snapshot", "견적 스냅샷 형식이 올바르지 않습니다.")

    if _reject_client_owner(body):
        return _error(400, "client_owner_not_allowed",
                      "소유자/워크스페이스는 서버가 결정합니다.")

    try:
        snapshot = normalize_quote_draft_snapshot(body)
    except QuoteHistoryStoreError:
        return _error(400, "invalid_snapshot", "견적 스냅샷 형식이 올바르지 않습니다.")

    store = _store(request)
    save_fn = getattr(store, "save_quote", None) if store is not None else None
    if not callable(save_fn):
        return _error(503, "quote_history_unavailable", "최근 견적을 사용할 수 없습니다.")

    try:
        saved = await _call(save_fn, user_id=uid, workspace_id=workspace_id, snapshot=snapshot)
    except QuoteHistoryStoreError:
        return _error(503, "quote_history_write_failed", "최근 견적을 저장하지 못했습니다.")
    except Exception:
        return _error(503, "quote_history_write_failed", "최근 견적을 저장하지 못했습니다.")

    return JSONResponse({"ok": True, "quote": saved}, status_code=201, headers=_NO_STORE)


async def b66_quote_history_detail(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    try:
        row_id = validate_row_id(request.path_params.get("quote_history_id", ""))
    except QuoteHistoryStoreError:
        return _error(404, "quote_not_found", "최근 견적을 찾을 수 없습니다.")

    store = _store(request)
    get_fn = getattr(store, "get_quote", None) if store is not None else None
    if not callable(get_fn):
        return _error(503, "quote_history_unavailable", "최근 견적을 사용할 수 없습니다.")

    try:
        record = await _call(get_fn, user_id=uid, workspace_id=workspace_id,
                             quote_history_id=row_id)
    except QuoteHistoryStoreError:
        return _error(503, "quote_history_read_failed", "최근 견적을 읽지 못했습니다.")
    except Exception:
        return _error(503, "quote_history_read_failed", "최근 견적을 읽지 못했습니다.")

    if not record:
        # Another owner's record is reported exactly like a missing record.
        return _error(404, "quote_not_found", "최근 견적을 찾을 수 없습니다.")

    return JSONResponse({"ok": True, "quote": record}, headers=_NO_STORE)


async def b66_quote_history_delete(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    try:
        row_id = validate_row_id(request.path_params.get("quote_history_id", ""))
    except QuoteHistoryStoreError:
        return _error(404, "quote_not_found", "최근 견적을 찾을 수 없습니다.")

    store = _store(request)
    delete_fn = getattr(store, "delete_quote", None) if store is not None else None
    if not callable(delete_fn):
        return _error(503, "quote_history_unavailable", "최근 견적을 사용할 수 없습니다.")

    try:
        deleted = await _call(delete_fn, user_id=uid, workspace_id=workspace_id,
                              quote_history_id=row_id)
    except QuoteHistoryStoreError:
        return _error(503, "quote_history_delete_failed", "최근 견적을 삭제하지 못했습니다.")
    except Exception:
        return _error(503, "quote_history_delete_failed", "최근 견적을 삭제하지 못했습니다.")

    if not deleted:
        return _error(404, "quote_not_found", "최근 견적을 찾을 수 없습니다.")

    return JSONResponse({"ok": True, "deleted": row_id}, headers=_NO_STORE)


__all__ = [
    "b66_quote_history_delete",
    "b66_quote_history_detail",
    "b66_quote_history_list",
    "b66_quote_history_save",
]
