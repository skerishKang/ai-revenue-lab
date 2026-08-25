from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .documents import DocumentValidationError, validate_document_fields
from .history import HistoryStore, validate_project_id
from .project_files import ProjectFileLimitError, ProjectFileStore, validate_file_id

MAX_PROJECT_FILE_BODY_BYTES = 160_000


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "project_files_unavailable", "message": "프로젝트 파일을 현재 사용할 수 없습니다."}},
        status_code=503,
    )


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "unauthorized", "message": "프로젝트 파일을 사용하려면 로그인이 필요합니다."}},
        status_code=401,
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "project_file_not_found", "message": "프로젝트 파일을 찾을 수 없습니다."}},
        status_code=404,
    )


async def _identity(request: Request):
    if not auth_ready(request) or request.app.state.project_file_store is None:
        return None, None, _unavailable()
    uid = current_user_id(request)
    if uid is None:
        return None, None, _unauthorized()
    try:
        pid = validate_project_id(request.path_params.get("project_id"))
    except ValueError:
        pid = None
    if pid is None:
        return None, None, _not_found()
    history: HistoryStore = request.app.state.history_store
    try:
        project = await history.get_project(uid, pid)
    except Exception:
        return None, None, _unavailable()
    if project is None:
        return None, None, _not_found()
    return uid, pid, None


async def project_files_collection(request: Request) -> JSONResponse:
    uid, pid, error = await _identity(request)
    if error is not None:
        return error
    store: ProjectFileStore = request.app.state.project_file_store

    if request.method == "GET":
        try:
            files = await store.list_files(uid, pid)
        except Exception:
            return _unavailable()
        return JSONResponse({"files": [item.public_dict() for item in files]})

    body = await request.body()
    if len(body) > MAX_PROJECT_FILE_BODY_BYTES:
        return JSONResponse({"error": {"code": "invalid_document", "message": "문서 요청이 너무 큽니다."}}, status_code=413)
    try:
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict) or set(raw) != {"name", "media_type", "text"}:
            raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
        document = validate_document_fields(raw.get("name"), raw.get("media_type"), raw.get("text"))
        created = await store.create_file(uid, pid, document.name, document.media_type, document.text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, DocumentValidationError) as exc:
        return JSONResponse({"error": {"code": "invalid_document", "message": str(exc) or "문서 형식이 올바르지 않습니다."}}, status_code=422)
    except ProjectFileLimitError as exc:
        return JSONResponse({"error": {"code": "project_file_limit", "message": str(exc)}}, status_code=422)
    except Exception:
        return _unavailable()
    return JSONResponse({"file": created.public_dict()}, status_code=201)


async def project_file_detail(request: Request):
    uid, pid, error = await _identity(request)
    if error is not None:
        return error
    try:
        fid = validate_file_id(request.path_params.get("file_id"))
    except ValueError:
        fid = None
    if fid is None:
        return _not_found()
    store: ProjectFileStore = request.app.state.project_file_store

    if request.method == "GET":
        try:
            record = await store.get_file(uid, pid, fid)
        except Exception:
            return _unavailable()
        if record is None:
            return _not_found()
        return JSONResponse({"file": record.public_dict()})

    try:
        deleted = await store.delete_file(uid, pid, fid)
    except Exception:
        return _unavailable()
    if not deleted:
        return _not_found()
    return Response(status_code=204)
