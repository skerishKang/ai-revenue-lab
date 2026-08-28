from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .history import HistoryStore, validate_project_fields, validate_project_id

MAX_PROJECT_BODY_BYTES = 8192


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "projects_unavailable", "message": "프로젝트를 현재 사용할 수 없습니다."}},
        status_code=503,
    )


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "unauthorized", "message": "프로젝트를 사용하려면 로그인이 필요합니다."}},
        status_code=401,
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "project_not_found", "message": "프로젝트를 찾을 수 없습니다."}},
        status_code=404,
    )


async def _json_body(request: Request) -> dict:
    body = await request.body()
    if len(body) > MAX_PROJECT_BODY_BYTES:
        raise ValueError("프로젝트 요청이 너무 큽니다.")
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("프로젝트 요청 형식이 올바르지 않습니다.") from exc
    if not isinstance(raw, dict):
        raise ValueError("프로젝트 요청 형식이 올바르지 않습니다.")
    return raw


async def projects_collection(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _unavailable()
    uid = current_user_id(request)
    if uid is None:
        return _unauthorized()
    store: HistoryStore = request.app.state.history_store

    if request.method == "GET":
        try:
            projects = await store.list_projects(uid)
        except Exception:
            return _unavailable()
        return JSONResponse({"projects": [item.public_dict() for item in projects]})

    try:
        raw = await _json_body(request)
        if set(raw) - {"name", "instructions"}:
            raise ValueError("지원하지 않는 프로젝트 요청 항목이 있습니다.")
        if "name" not in raw:
            raise ValueError("프로젝트 이름이 필요합니다.")
        name, instructions = validate_project_fields(raw.get("name"), raw.get("instructions", ""))
        project = await store.create_project(uid, name, instructions)
    except ValueError as exc:
        return JSONResponse({"error": {"code": "invalid_project", "message": str(exc)}}, status_code=422)
    except Exception:
        return _unavailable()
    return JSONResponse({"project": project.public_dict()}, status_code=201)


async def project_detail(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _unavailable()
    uid = current_user_id(request)
    if uid is None:
        return _unauthorized()
    try:
        project_id = validate_project_id(request.path_params.get("project_id"))
    except ValueError:
        project_id = None
    if project_id is None:
        return _not_found()
    store: HistoryStore = request.app.state.history_store

    if request.method == "DELETE":
        try:
            project = await store.get_project(uid, project_id)
            if project is None:
                return _not_found()
            file_store = request.app.state.project_file_store
            if file_store is None:
                return _unavailable()
            files = await file_store.list_files(uid, project_id)
            if files:
                return JSONResponse(
                    {"error": {"code": "project_has_files", "message": "프로젝트 파일을 먼저 삭제해 주세요."}},
                    status_code=409,
                )
            deleted = await store.delete_project(uid, project_id)
        except Exception:
            return _unavailable()
        if not deleted:
            return _not_found()
        return JSONResponse({"deleted": True, "project_id": project_id})

    if request.method == "GET":
        try:
            project = await store.get_project(uid, project_id)
            if project is None:
                return _not_found()
            conversations = await store.list_project_conversations(uid, project_id)
        except Exception:
            return _unavailable()
        return JSONResponse({
            "project": project.public_dict(),
            "conversations": conversations,
        })

    try:
        current = await store.get_project(uid, project_id)
        if current is None:
            return _not_found()
        raw = await _json_body(request)
        if not raw or set(raw) - {"name", "instructions"}:
            raise ValueError("지원하지 않는 프로젝트 요청 항목이 있습니다.")
        name = raw.get("name", current.name)
        instructions = raw.get("instructions", current.instructions)
        clean_name, clean_instructions = validate_project_fields(name, instructions)
        updated = await store.update_project(uid, project_id, clean_name, clean_instructions)
    except ValueError as exc:
        return JSONResponse({"error": {"code": "invalid_project", "message": str(exc)}}, status_code=422)
    except Exception:
        return _unavailable()
    if updated is None:
        return _not_found()
    return JSONResponse({"project": updated.public_dict()})
