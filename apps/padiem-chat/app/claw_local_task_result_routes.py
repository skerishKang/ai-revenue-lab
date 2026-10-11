"""#3139 — the one server-owned consumer of a Local Runner terminal result.

`POST /api/claw/runs/{run_id}/local-result` lets an authenticated owner ask the
server to reconcile one of their own Claw runs against the canonical broker. It
accepts no conversation, no command identity and no outcome: the conversation is
resolved from the run row, the command from the server-owned correlation
binding, and the outcome from the broker's read-only projection. The response
never carries command material.
"""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id

CLAW_LOCAL_TASK_RESULT_PATH = "/api/claw/runs/{run_id}/local-result"
from .claw_local_task_result_projection import LocalTaskResultError
from .history import HistoryError, HistoryForbidden

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,511}$")
_UNCONFIGURED_REASON = "local_runner_result_unconfigured"
_FAILED_REASON = "local_runner_result_failed"
_FORBIDDEN_REASON = "local_runner_result_forbidden"


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message}}, status_code=status_code)


def _run_id(raw: Any) -> str | None:
    if not isinstance(raw, str) or not _RUN_ID.fullmatch(raw.strip()):
        return None
    return raw.strip()


async def local_runner_result(request: Request) -> JSONResponse:
    """Reconcile one owner's Claw run with its canonical terminal result."""

    if not auth_ready(request) or current_user_id(request) is None:
        return _error(401, _FORBIDDEN_REASON, "인증이 필요합니다.")
    owner_id = current_user_id(request)

    run_id = _run_id(request.path_params.get("run_id"))
    if run_id is None:
        return _error(400, "invalid_run_id", "runId가 올바르지 않습니다.")

    source = getattr(request.app.state, "local_task_result_source", None)
    project = getattr(source, "project_local_runner_result", None)
    if project is None or getattr(source, "configured", True) is False:
        return _error(503, _UNCONFIGURED_REASON, "로컬 러너 결과 조회가 구성되지 않았습니다.")

    payload: dict[str, Any] | None = None
    try:
        supplied = await request.json()
    except Exception:
        supplied = None
    if isinstance(supplied, dict):
        # Only the workspace expectation may come from the caller, and it can
        # only ever *tighten* the check; the conversation, the command and the
        # outcome are all resolved server-side.
        workspace = supplied.get("workspaceId")
        if isinstance(workspace, str) and workspace.strip():
            payload = {"workspace_id": workspace.strip()[:256]}

    try:
        kwargs: dict[str, Any] = {"owner_id": owner_id, "run_id": run_id}
        if payload is not None:
            kwargs.update(payload)
        projected = project(**kwargs)
        if inspect.isawaitable(projected):
            projected = await projected
    except HistoryForbidden:
        return _error(403, _FORBIDDEN_REASON, "해당 런에 접근할 수 없습니다.")
    except LocalTaskResultError as exc:
        if exc.code == "local_task_result_workspace_mismatch":
            return _error(409, "local_runner_result_workspace_mismatch", "워크스페이스가 일치하지 않습니다.")
        if exc.code == "local_task_result_workspace_missing":
            return _error(409, "local_runner_result_workspace_missing", "런의 워크스페이스 범위가 없습니다.")
        return _error(409, "local_runner_result_conflict", "런 결과를 확정할 수 없습니다.")
    except HistoryError:
        return _error(409, "local_runner_result_conflict", "런 결과가 이미 다르게 기록되었습니다.")
    except Exception:
        # Exception text can carry identifiers or storage detail; report only
        # the bounded code.
        return _error(500, _FAILED_REASON, "로컬 러너 결과 조회에 실패했습니다.")

    if projected is None:
        return _error(404, "local_runner_result_absent", "종료된 런 결과가 없습니다.")

    return JSONResponse(
        {
            "ok": True,
            "projectionVersion": 1,
            "projection": {
                "runId": projected.get("runId"),
                "commandId": projected.get("commandId"),
                "appended": projected.get("appended") is True,
                "status": projected.get("status"),
                "reason": projected.get("reason"),
                "raw_argv": False,
                "raw_stdout": False,
                "raw_stderr": False,
                "raw_device_credential": False,
                "p01_approval_payload": False,
            },
            "now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )
