"""Bounded Task/Alert inbox HTTP surface for Padiem Chat (#2341).

Consumes the existing D1ClawTaskAlertStore. Identity/workspace are derived only
from the signed-in owner and canonical tenant authority; browser callers cannot
supply either. Missing and foreign records share the same 404 projection.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from kagent.claw_memory import ClawAlertStatus, ClawMemoryError, ClawTaskStatus

from .claw_memory_routes import _require_owner, _resolve_memory_workspace
from .workspace_storage import WorkspaceStorageError

MAX_INBOX_HTTP_LIMIT = 50
_STORE_SCAN_LIMIT = 256  # existing D1ClawTaskAlertStore hard bound
MAX_INBOX_BODY_BYTES = 4096

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _store(request: Request) -> Any | None:
    return getattr(request.app.state, "claw_task_alert_store", None)


def _bounded_limit(request: Request) -> int | JSONResponse:
    raw = request.query_params.get("limit")
    if raw is None:
        return 20
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit must be an integer.")
    if value < 1:
        return _error(400, "invalid_limit", "limit must be at least 1.")
    return min(value, MAX_INBOX_HTTP_LIMIT)


async def _call(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def claw_inbox_list(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "Authentication is required.")
    kind = request.path_params.get("kind", "")
    if kind not in {"tasks", "alerts"}:
        return _error(404, "inbox_not_found", "Inbox not found.")
    limit = _bounded_limit(request)
    if isinstance(limit, JSONResponse):
        return limit
    store = _store(request)
    if store is None:
        return _error(503, "inbox_unavailable", "Inbox is unavailable.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        if kind == "tasks":
            records = await _call(store.list_tasks(workspace_id, limit=_STORE_SCAN_LIMIT))
            items = [item.safe_dict() for item in records if getattr(item, "member_id", None) == uid][:limit]
        else:
            records = await _call(store.list_alerts(workspace_id, member_id=uid, limit=_STORE_SCAN_LIMIT))
            items = [item.safe_dict() for item in records][:limit]
    except Exception:
        return _error(503, "inbox_read_failed", "Inbox could not be loaded.")
    return JSONResponse(
        {"ok": True, "kind": kind, "items": items, "limit": limit},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def _read_status(request: Request) -> str | JSONResponse:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON request required.")
    raw = await request.body()
    if not raw or len(raw) > MAX_INBOX_BODY_BYTES:
        return _error(400, "invalid_payload", "Invalid request payload.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "Invalid JSON.")
    if not isinstance(data, dict) or set(data) != {"status"} or not isinstance(data.get("status"), str):
        return _error(400, "invalid_payload", "Invalid request payload.")
    return data["status"]


async def claw_inbox_status(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "Authentication is required.")
    kind = request.path_params.get("kind", "")
    item_id = request.path_params.get("item_id", "")
    if kind not in {"tasks", "alerts"} or not item_id:
        return _error(404, "inbox_item_not_found", "Inbox item not found.")
    status_value = await _read_status(request)
    if isinstance(status_value, JSONResponse):
        return status_value
    store = _store(request)
    if store is None:
        return _error(503, "inbox_unavailable", "Inbox is unavailable.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        if kind == "tasks":
            status = ClawTaskStatus(status_value)
            current = await _call(store._get_task_locked(item_id, workspace_id=workspace_id))
            if current is None or getattr(current, "member_id", None) != uid:
                return _error(404, "inbox_item_not_found", "Inbox item not found.")
            updated = await _call(store.set_task_status(item_id, status, workspace_id=workspace_id))
        else:
            status = ClawAlertStatus(status_value)
            current = await _call(store._get_alert_locked(item_id, workspace_id=workspace_id))
            if current is None or not current.is_visible_to(uid):
                return _error(404, "inbox_item_not_found", "Inbox item not found.")
            updated = await _call(store.set_alert_status(item_id, status, workspace_id=workspace_id))
    except (ValueError, ClawMemoryError):
        return _error(400, "invalid_status", "Invalid inbox status.")
    except WorkspaceStorageError:
        return _error(503, "inbox_write_failed", "Inbox status could not be updated.")
    except Exception:
        return _error(503, "inbox_write_failed", "Inbox status could not be updated.")
    return JSONResponse(
        {"ok": True, "kind": kind, "item": updated.safe_dict()},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )
