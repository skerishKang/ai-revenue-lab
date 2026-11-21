"""#8193: in-memory, read-only view of each PC's last self-recovery.

No database writes: the local agent reports one bounded result per recovery
through the existing signed notify key, and the admin console reads the latest
result from process memory. A host restart simply clears the view.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import read_bounded_request_body
from .central_model_control_routes import _central_admin
from .ops_notify_event import KEY_HEADER, authorized
import json

_FIELDS = {"node", "at", "action", "detail", "result"}
_MAX_NODE = 60
_MAX_TEXT = 80
_HEADERS = {"Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff"}
_lock = threading.Lock()
_reports: dict[str, dict[str, Any]] = {}


def _response(payload, status=200):
    return JSONResponse(payload, status_code=status, headers=dict(_HEADERS))


def reset_for_test() -> None:
    with _lock:
        _reports.clear()


def latest(node: str | None = None) -> dict[str, Any]:
    with _lock:
        rows = [dict(row) for row in _reports.values()]
    rows.sort(key=lambda row: row["at"], reverse=True)
    return {"ok": True, "reports": rows if node is None else
            [row for row in rows if row["node"] == node]}


async def report_self_heal(request):
    """Signed loopback POST from the local agent, one bounded result."""

    if not authorized("pc", request.headers.get(KEY_HEADER)):
        return _response({"ok": False, "error": {"code": "self_heal_unauthorized"}}, 401)
    try:
        raw = await read_bounded_request_body(request, max_bytes=2048)
        payload = json.loads(raw)
    except Exception:
        return _response({"ok": False, "error": {"code": "self_heal_invalid"}}, 400)
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        return _response({"ok": False, "error": {"code": "self_heal_invalid"}}, 400)
    node, action, detail, result = (payload["node"], payload["action"],
                                    payload["detail"], payload["result"])
    for value in (node, action, detail, result):
        if not isinstance(value, str) or not 0 < len(value) <= _MAX_TEXT:
            return _response({"ok": False, "error": {"code": "self_heal_invalid"}}, 400)
    if len(node) > _MAX_NODE or not isinstance(payload["at"], (int, float)):
        return _response({"ok": False, "error": {"code": "self_heal_invalid"}}, 400)
    stamp = datetime.fromtimestamp(payload["at"], timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    with _lock:
        _reports[node] = {"node": node, "at": stamp, "action": action,
                          "detail": detail, "result": result}
    return _response({"ok": True})


async def admin_self_heal(request):
    """Admin console read, central-admin gate only."""

    denied = await _central_admin(request)
    if denied is not None:
        return denied
    if not auth_ready(request) or not current_user_id(request):
        return _response({"ok": False, "error": {"code": "unauthorized"}}, 401)
    if set(request.query_params) - {"node"}:
        return _response({"ok": False, "error": {"code": "self_heal_invalid"}}, 400)
    return _response(latest(request.query_params.get("node")))


def routes():
    from starlette.routing import Route

    return [
        Route("/api/ops/pc/self-heal", report_self_heal, methods=["POST"]),
        Route("/api/ops/pc/self-heal", admin_self_heal, methods=["GET"]),
    ]
