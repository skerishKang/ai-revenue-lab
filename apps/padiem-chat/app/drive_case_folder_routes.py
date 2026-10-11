"""Owner-gated Project Drive case-folder routes (#3190).

Authority order is fixed and enforced before any Engine call:

    auth_ready
    -> current_user_id
    -> validate_project_id
    -> history_store.get_project(uid, project_id)        (owner gate)
    -> identity_shadow_store.load_projection(uid)        (canonical session)
    -> shadow.auth_session_id
    -> control_plane_identity_authority.resolve_connector_workspace(session_id)
    -> app.state.drive_case_folder_engine_client

The browser never supplies ``workspace_ref``, ``binding_ref``, ``actor_ref``,
``app_id``, ``agent_id``, ``scope``, ``tenant_id``, ``subject_id`` or a
``DriveGrant``: the canonical workspace comes only from the server-side identity
shadow plus the Control Plane identity authority. A foreign project returns the
same 404 as an unknown one, and a missing Engine client fails closed with 503
(no fallback).

``folder_id`` remains selection intent only: the Engine re-fetches canonical
Drive metadata and re-validates the folder before persisting.
"""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .drive_case_folder_engine import DriveCaseFolderEngineError
from .history import HistoryStore, validate_project_id

MAX_FOLDER_QUERY_CHARS = 200
MAX_FOLDER_ID_CHARS = 200
MAX_PUT_BODY_BYTES = 4_000

_ALLOWED_FOLDER_QUERY_KEYS = frozenset({"query"})


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


def _unavailable(code: str = "drive_case_folder_unavailable") -> JSONResponse:
    return _error(code, "Drive 사건 폴더 기능을 사용할 수 없습니다.", 503)


def _unauthorized() -> JSONResponse:
    return _error("unauthorized", "로그인이 필요합니다.", 401)


def _not_found() -> JSONResponse:
    return _error("project_not_found", "프로젝트를 찾을 수 없습니다.", 404)


def _invalid(code: str, message: str) -> JSONResponse:
    return _error(code, message, 400)


def _generic_failure() -> JSONResponse:
    return _error(
        "drive_case_folder_failed",
        "Drive 사건 폴더 요청을 처리하지 못했습니다.",
        502,
    )


def _engine_error(exc: DriveCaseFolderEngineError) -> JSONResponse:
    """Map the bounded Engine client error onto the route taxonomy.

    Only the reviewed error type is trusted; an unexpected exception never has
    its attributes read, so it cannot inject a product response.
    """

    status_code = int(exc.status_code or 502)
    if status_code not in (400, 401, 403, 404, 409, 413, 415, 422, 502, 503):
        status_code = 502
    return _error(exc.code, exc.safe_message, status_code)


async def _resolve_context(request: Request):
    """Return (uid, project_id, workspace_ref, engine_client, error_response)."""

    if not auth_ready(request):
        return None, None, None, None, _unavailable()
    uid = current_user_id(request)
    if uid is None:
        return None, None, None, None, _unauthorized()

    try:
        pid = validate_project_id(request.path_params.get("project_id"))
    except ValueError:
        pid = None
    if pid is None:
        return None, None, None, None, _not_found()

    history: HistoryStore | None = getattr(request.app.state, "history_store", None)
    if history is None:
        return None, None, None, None, _unavailable()
    try:
        project = await history.get_project(uid, pid)
    except Exception:
        return None, None, None, None, _unavailable()
    if project is None:
        # A foreign project is never distinguished from an unknown one.
        return None, None, None, None, _not_found()

    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    if shadow_store is None or not callable(getattr(shadow_store, "load_projection", None)):
        return None, None, None, None, _unavailable("identity_workspace_unavailable")
    try:
        shadow = await shadow_store.load_projection(uid)
    except Exception:
        return None, None, None, None, _unavailable("identity_workspace_unavailable")
    session_id = getattr(shadow, "auth_session_id", None) if shadow is not None else None
    if not isinstance(session_id, str) or not session_id:
        return None, None, None, None, _unavailable("identity_workspace_unavailable")

    identity_authority = getattr(request.app.state, "control_plane_identity_authority", None)
    resolver = getattr(identity_authority, "resolve_connector_workspace", None) if identity_authority else None
    if not callable(resolver):
        return None, None, None, None, _unavailable("identity_workspace_unavailable")
    try:
        workspace_ref = await resolver(session_id=session_id)
    except Exception:
        return None, None, None, None, _unavailable("identity_workspace_unavailable")
    if not isinstance(workspace_ref, str) or not workspace_ref:
        return None, None, None, None, _unavailable("identity_workspace_unavailable")

    client = getattr(request.app.state, "drive_case_folder_engine_client", None)
    if client is None:
        return None, None, None, None, _unavailable()
    return uid, pid, workspace_ref, client, None


async def drive_case_folder_status(request: Request) -> JSONResponse:
    uid, pid, workspace_ref, client, error = await _resolve_context(request)
    if error is not None:
        return error
    try:
        body = await client.status(workspace_ref=workspace_ref, project_id=pid)
    except DriveCaseFolderEngineError as exc:
        return _engine_error(exc)
    except Exception:
        return _generic_failure()
    return JSONResponse(
        {
            "configured": bool(body.get("configured")),
            "space_kind": body.get("space_kind"),
            "updated_at": body.get("updated_at"),
        }
    )


async def drive_folders_collection(request: Request) -> JSONResponse:
    uid, pid, workspace_ref, client, error = await _resolve_context(request)
    if error is not None:
        return error

    query_keys = set(request.query_params.keys())
    unknown = query_keys - _ALLOWED_FOLDER_QUERY_KEYS
    if unknown:
        return _invalid("invalid_query", "허용되지 않은 검색 파라미터입니다.")
    raw_query = request.query_params.get("query")
    query: str | None = None
    if raw_query is not None:
        candidate = raw_query.strip()
        if not candidate or len(candidate) > MAX_FOLDER_QUERY_CHARS:
            return _invalid("invalid_query", "검색어가 올바르지 않습니다.")
        query = candidate

    try:
        body = await client.folders(workspace_ref=workspace_ref, project_id=pid, query=query)
    except DriveCaseFolderEngineError as exc:
        return _engine_error(exc)
    except Exception:
        return _generic_failure()
    return JSONResponse(
        {
            "folders": [
                {
                    "folder_id": item.get("folder_id"),
                    "name": item.get("name"),
                    "space_kind": item.get("space_kind"),
                    "modified_time": item.get("modified_time"),
                }
                for item in body.get("folders", [])
            ],
            "more": bool(body.get("more")),
            "exhaustive": bool(body.get("exhaustive")),
        }
    )


async def drive_case_folder_put(request: Request) -> JSONResponse:
    uid, pid, workspace_ref, client, error = await _resolve_context(request)
    if error is not None:
        return error

    try:
        body = await read_bounded_request_body(
            request,
            max_bytes=MAX_PUT_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        return _error("invalid_body", "요청 본문이 너무 큽니다.", 413)
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _invalid("invalid_body", "요청 본문이 올바르지 않습니다.")
    if not isinstance(raw, dict) or set(raw) != {"folder_id"}:
        # extra caller authority fields (workspace_ref, binding_ref, grant, ...) deny
        return _invalid("invalid_body", "허용되지 않은 필드가 포함되어 있습니다.")
    folder_id = raw.get("folder_id")
    if not isinstance(folder_id, str) or not folder_id.strip() or len(folder_id.strip()) > MAX_FOLDER_ID_CHARS:
        return _invalid("invalid_folder_id", "폴더 선택 값이 올바르지 않습니다.")

    try:
        result = await client.select(workspace_ref=workspace_ref, project_id=pid, folder_id=folder_id.strip())
    except DriveCaseFolderEngineError as exc:
        return _engine_error(exc)
    except Exception:
        return _generic_failure()
    return JSONResponse(
        {
            "configured": bool(result.get("configured")),
            "space_kind": result.get("space_kind"),
            "updated_at": result.get("updated_at"),
        }
    )


async def drive_case_folder_delete(request: Request) -> JSONResponse:
    uid, pid, workspace_ref, client, error = await _resolve_context(request)
    if error is not None:
        return error
    try:
        body = await read_bounded_request_body(request, max_bytes=1)
    except RequestBodyTooLarge:
        return _invalid("invalid_body", "요청 본문이 허용되지 않습니다.")
    if body:
        return _invalid("invalid_body", "요청 본문이 허용되지 않습니다.")
    try:
        result = await client.clear(workspace_ref=workspace_ref, project_id=pid)
    except DriveCaseFolderEngineError as exc:
        return _engine_error(exc)
    except Exception:
        return _generic_failure()
    return JSONResponse({"configured": False, "cleared": bool(result.get("cleared"))})


DRIVE_CASE_FOLDER_ROUTE_PATHS = {
    "status": "/api/projects/{project_id}/drive-case-folder",
    "folders": "/api/projects/{project_id}/drive-folders",
    "select": "/api/projects/{project_id}/drive-case-folder",
    "clear": "/api/projects/{project_id}/drive-case-folder",
}

# Reviewed pins asserted by the route security tests.
BROWSER_WORKSPACE_REF_AUTHORITY = False
BROWSER_BINDING_REF_AUTHORITY = False
BROWSER_DRIVE_GRANT_AUTHORITY = False
FOREIGN_PROJECT_EXISTENCE_DISCLOSURE = False
ENGINE_FALLBACK_WITHOUT_CLIENT = False
PRODUCTION_BINDING_ACTIVATION = False


__all__ = [
    "MAX_FOLDER_QUERY_CHARS",
    "MAX_FOLDER_ID_CHARS",
    "DRIVE_CASE_FOLDER_ROUTE_PATHS",
    "BROWSER_WORKSPACE_REF_AUTHORITY",
    "BROWSER_BINDING_REF_AUTHORITY",
    "BROWSER_DRIVE_GRANT_AUTHORITY",
    "FOREIGN_PROJECT_EXISTENCE_DISCLOSURE",
    "ENGINE_FALLBACK_WITHOUT_CLIENT",
    "drive_case_folder_status",
    "drive_folders_collection",
    "drive_case_folder_put",
    "drive_case_folder_delete",
]
