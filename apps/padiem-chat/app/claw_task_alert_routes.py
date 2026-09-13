"""Task / alert inbox read seam for the B54 Claw contracts (#2341).

Thin product read surface over the already-accepted durable store
(``D1ClawTaskAlertStore``, #2328 / B62). It *consumes* the store authority and
adds no persistence, scheduling, or execution semantics of its own.

Endpoints:
- GET  /api/claw/tasks                    — owner/workspace-scoped bounded list
- GET  /api/claw/tasks/{task_id}          — non-disclosing single read
- POST /api/claw/tasks/{task_id}/status   — reversible status update
- GET  /api/claw/alerts                   — workspace + member-scoped bounded list
- GET  /api/claw/alerts/{alert_id}        — non-disclosing single read
- POST /api/claw/alerts/{alert_id}/status — reversible status update

Identity and scope come exclusively from the signed-in session and the
canonical tenant authority; a caller can never supply or override the
workspace/owner. A foreign or missing record is observationally identical to
a missing one. Storage failures fail closed.

This module does NOT:
- create tables or new database authority (``NEW_DB_AUTHORITY=NO``)
- schedule, dispatch, or execute anything (``BACKGROUND_SCHEDULER=NO``,
  ``CRON_DISPATCH=NO``, ``AUTO_TASK_EXECUTION=NO``)
- send notifications or write to connectors (``AUTO_EXTERNAL_SEND=NO``,
  ``CONNECTOR_WRITE=NO``)
- reimplement P01/Core workflow or approval authority
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from kagent.claw_memory import (
    CONTRACT_VERSION,
    ClawAlertStatus,
    ClawMemoryError,
    ClawTaskStatus,
)

from .claw_memory_routes import (
    _NO_STORE_HEADERS,
    _error,
    _require_owner,
    _resolve_memory_workspace as _resolve_workspace,
)
from .workspace_storage import WorkspaceStorageError

MAX_INBOX_BODY_BYTES = 8 * 1024

# Explicit wire allowlists. ``ClawFollowupTask.safe_dict()`` /
# ``ClawAlert.safe_dict()`` also carry ``workspace_id`` / ``member_id`` /
# ``source_id`` / ``linked_ref`` / ``visible_to_members`` — internal scope and
# linkage identifiers that must never reach the browser.
_TASK_FIELDS = ("task_id", "title", "status", "due_date", "created_at")
_ALERT_FIELDS = ("alert_id", "kind", "severity", "title", "status", "created_at")

_TASK_STATUSES = tuple(status.value for status in ClawTaskStatus)
_ALERT_STATUSES = tuple(status.value for status in ClawAlertStatus)

_UNAVAILABLE = "작업/알림 목록을 사용할 수 없습니다."


def _project(record: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Project one store record onto the explicit public wire allowlist.

    Delegates to the contract's own ``safe_dict()`` so secret redaction
    (``redact_secrets``) and timestamp serialization stay the contract's
    responsibility, then narrows the key set — dropping the workspace/member
    scope identifiers and linkage refs the contract also emits.
    """
    safe = record.safe_dict() if hasattr(record, "safe_dict") else dict(record)
    return {field: safe.get(field) for field in fields}


def _inbox_store(request: Request) -> Any | None:
    return getattr(request.app.state, "claw_task_alert_store", None)


def _bounded_limit(request: Request, maximum: int) -> int | JSONResponse:
    raw_limit = request.query_params.get("limit")
    try:
        limit = maximum if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        return _error(400, "invalid_limit", "limit 는 정수여야 합니다.")
    if limit < 1:
        return _error(400, "invalid_limit", "limit 는 1 이상이어야 합니다.")
    return min(limit, maximum)


async def _read_json_body(request: Request) -> dict[str, Any] | JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_INBOX_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")
    return data


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _store_method(store: Any | None, name: str) -> Any | None:
    method = getattr(store, name, None) if store is not None else None
    return method if callable(method) else None


async def claw_tasks_list(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    list_fn = _store_method(_inbox_store(request), "list_tasks")
    if list_fn is None:
        return _error(503, "claw_task_alert_unavailable", _UNAVAILABLE)
    limit = _bounded_limit(request, 256)
    if isinstance(limit, JSONResponse):
        return limit
    workspace_id = await _resolve_workspace(request, uid)
    try:
        tasks = await _maybe_await(list_fn(workspace_id, limit=limit))
    except (ClawMemoryError, WorkspaceStorageError):
        return _error(503, "claw_task_alert_read_failed", _UNAVAILABLE)
    except Exception:
        return _error(503, "claw_task_alert_read_failed", _UNAVAILABLE)
    records = tasks if isinstance(tasks, (list, tuple)) else []
    return JSONResponse(
        {
            "ok": True,
            "contract_version": CONTRACT_VERSION,
            "tasks": [_project(task, _TASK_FIELDS) for task in records],
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_task_detail(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    get_fn = _store_method(_inbox_store(request), "get_task")
    if get_fn is None:
        return _error(503, "claw_task_alert_unavailable", _UNAVAILABLE)
    task_id = request.path_params.get("task_id", "")
    workspace_id = await _resolve_workspace(request, uid)
    try:
        task = await _maybe_await(get_fn(task_id, workspace_id=workspace_id))
    except (ClawMemoryError, WorkspaceStorageError):
        task = None
    except Exception:
        return _error(503, "claw_task_alert_read_failed", _UNAVAILABLE)
    if task is None:
        # Non-disclosing: a foreign task is observationally identical to a
        # missing one.
        return _error(404, "claw_task_not_found", "작업을 찾을 수 없습니다.")
    return JSONResponse(
        {"ok": True, "contract_version": CONTRACT_VERSION, "task": _project(task, _TASK_FIELDS)},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_task_status(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    set_fn = _store_method(_inbox_store(request), "set_task_status")
    if set_fn is None:
        return _error(503, "claw_task_alert_unavailable", _UNAVAILABLE)
    data = await _read_json_body(request)
    if isinstance(data, JSONResponse):
        return data
    raw_status = data.get("status")
    if not isinstance(raw_status, str) or raw_status not in _TASK_STATUSES:
        return _error(400, "invalid_status", "허용되지 않는 상태입니다.")
    task_id = request.path_params.get("task_id", "")
    workspace_id = await _resolve_workspace(request, uid)
    try:
        task = await _maybe_await(
            set_fn(task_id, ClawTaskStatus(raw_status), workspace_id=workspace_id)
        )
    except (ClawMemoryError, WorkspaceStorageError):
        return _error(404, "claw_task_not_found", "작업을 찾을 수 없습니다.")
    except Exception:
        return _error(503, "claw_task_alert_write_failed", "작업 상태를 변경할 수 없습니다.")
    if task is None:
        return _error(404, "claw_task_not_found", "작업을 찾을 수 없습니다.")
    return JSONResponse(
        {"ok": True, "contract_version": CONTRACT_VERSION, "task": _project(task, _TASK_FIELDS)},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_alerts_list(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    list_fn = _store_method(_inbox_store(request), "list_alerts")
    if list_fn is None:
        return _error(503, "claw_task_alert_unavailable", _UNAVAILABLE)
    limit = _bounded_limit(request, 256)
    if isinstance(limit, JSONResponse):
        return limit
    workspace_id = await _resolve_workspace(request, uid)
    try:
        # Member-scoped: the signed-in owner is the only member identity this
        # product can derive. Alerts visible to other members are not disclosed.
        alerts = await _maybe_await(list_fn(workspace_id, member_id=uid, limit=limit))
    except (ClawMemoryError, WorkspaceStorageError):
        return _error(503, "claw_task_alert_read_failed", _UNAVAILABLE)
    except Exception:
        return _error(503, "claw_task_alert_read_failed", _UNAVAILABLE)
    records = alerts if isinstance(alerts, (list, tuple)) else []
    return JSONResponse(
        {
            "ok": True,
            "contract_version": CONTRACT_VERSION,
            "alerts": [_project(alert, _ALERT_FIELDS) for alert in records],
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_alert_detail(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    get_fn = _store_method(_inbox_store(request), "get_alert")
    if get_fn is None:
        return _error(503, "claw_task_alert_unavailable", _UNAVAILABLE)
    alert_id = request.path_params.get("alert_id", "")
    workspace_id = await _resolve_workspace(request, uid)
    try:
        alert = await _maybe_await(get_fn(alert_id, workspace_id=workspace_id, member_id=uid))
    except (ClawMemoryError, WorkspaceStorageError):
        alert = None
    except Exception:
        return _error(503, "claw_task_alert_read_failed", _UNAVAILABLE)
    if alert is None:
        return _error(404, "claw_alert_not_found", "알림을 찾을 수 없습니다.")
    return JSONResponse(
        {"ok": True, "contract_version": CONTRACT_VERSION, "alert": _project(alert, _ALERT_FIELDS)},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_alert_status(request: Request) -> JSONResponse:
    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "인증이 필요합니다.")
    set_fn = _store_method(_inbox_store(request), "set_alert_status")
    if set_fn is None:
        return _error(503, "claw_task_alert_unavailable", _UNAVAILABLE)
    data = await _read_json_body(request)
    if isinstance(data, JSONResponse):
        return data
    raw_status = data.get("status")
    if not isinstance(raw_status, str) or raw_status not in _ALERT_STATUSES:
        return _error(400, "invalid_status", "허용되지 않는 상태입니다.")
    alert_id = request.path_params.get("alert_id", "")
    workspace_id = await _resolve_workspace(request, uid)
    try:
        alert = await _maybe_await(
            set_fn(alert_id, ClawAlertStatus(raw_status), workspace_id=workspace_id)
        )
    except (ClawMemoryError, WorkspaceStorageError):
        return _error(404, "claw_alert_not_found", "알림을 찾을 수 없습니다.")
    except Exception:
        return _error(503, "claw_task_alert_write_failed", "알림 상태를 변경할 수 없습니다.")
    if alert is None:
        return _error(404, "claw_alert_not_found", "알림을 찾을 수 없습니다.")
    return JSONResponse(
        {"ok": True, "contract_version": CONTRACT_VERSION, "alert": _project(alert, _ALERT_FIELDS)},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )
