from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .history import HistoryStore, validate_conversation_id, validate_project_id
from .saved_outputs import (
    SavedOutputLimitError,
    SavedOutputStore,
    validate_output_content,
    validate_output_id,
    validate_output_title,
)

MAX_OUTPUT_BODY_BYTES = 96_000


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "saved_outputs_unavailable", "message": "저장한 답변을 현재 사용할 수 없습니다."}},
        status_code=503,
    )


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "unauthorized", "message": "저장한 답변을 사용하려면 로그인이 필요합니다."}},
        status_code=401,
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "saved_output_not_found", "message": "저장한 답변을 찾을 수 없습니다."}},
        status_code=404,
    )


def _provenance_not_found() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "provenance_not_found", "message": "연결된 대화 또는 프로젝트를 확인할 수 없습니다."}},
        status_code=404,
    )


async def _json_body(request: Request) -> dict:
    body = await request.body()
    if len(body) > MAX_OUTPUT_BODY_BYTES:
        raise ValueError("저장할 답변 요청이 너무 큽니다.")
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("저장할 답변 요청 형식이 올바르지 않습니다.") from exc
    if not isinstance(raw, dict):
        raise ValueError("저장할 답변 요청 형식이 올바르지 않습니다.")
    return raw


def _stores(request: Request) -> tuple[HistoryStore | None, SavedOutputStore | None]:
    return request.app.state.history_store, getattr(request.app.state, "saved_output_store", None)


async def _verified_provenance(
    history: HistoryStore,
    user_id: str,
    conversation_id: str | None,
    project_id: str | None,
) -> tuple[str | None, str | None] | None:
    effective_project_id = project_id
    if conversation_id is not None:
        conversation = await history.get_conversation(user_id, conversation_id)
        if conversation is None:
            return None
        stored_project = conversation.get("project_id")
        if stored_project is not None and not isinstance(stored_project, str):
            return None
        if project_id is not None and project_id != stored_project:
            return None
        if project_id is None:
            effective_project_id = stored_project
    if effective_project_id is not None:
        project = await history.get_project(user_id, effective_project_id)
        if project is None:
            return None
    return conversation_id, effective_project_id


async def outputs_collection(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _unavailable()
    uid = current_user_id(request)
    if uid is None:
        return _unauthorized()
    history, output_store = _stores(request)
    if history is None or output_store is None:
        return _unavailable()

    if request.method == "GET":
        try:
            outputs = await output_store.list_outputs(uid)
        except Exception:
            return _unavailable()
        return JSONResponse({"outputs": [item.summary_dict() for item in outputs]})

    try:
        raw = await _json_body(request)
        if set(raw) - {"title", "content", "conversation_id", "project_id"}:
            raise ValueError("지원하지 않는 저장 요청 항목이 있습니다.")
        if "title" not in raw or "content" not in raw:
            raise ValueError("저장할 답변 제목과 내용이 필요합니다.")
        title = validate_output_title(raw.get("title"))
        content = validate_output_content(raw.get("content"))
        conversation_id = validate_conversation_id(raw.get("conversation_id"))
        project_id = validate_project_id(raw.get("project_id"))
        verified = await _verified_provenance(history, uid, conversation_id, project_id)
        if verified is None:
            return _provenance_not_found()
        conversation_id, project_id = verified
        saved = await output_store.create_output(uid, title, content, conversation_id, project_id)
    except SavedOutputLimitError as exc:
        return JSONResponse({"error": {"code": "saved_output_limit", "message": str(exc)}}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": {"code": "invalid_saved_output", "message": str(exc)}}, status_code=422)
    except Exception:
        return _unavailable()
    return JSONResponse({"output": saved.detail_dict()}, status_code=201)


async def output_detail(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _unavailable()
    uid = current_user_id(request)
    if uid is None:
        return _unauthorized()
    _, output_store = _stores(request)
    if output_store is None:
        return _unavailable()
    try:
        output_id = validate_output_id(request.path_params.get("output_id"))
    except ValueError:
        output_id = None
    if output_id is None:
        return _not_found()

    if request.method == "GET":
        try:
            saved = await output_store.get_output(uid, output_id)
        except Exception:
            return _unavailable()
        if saved is None:
            return _not_found()
        return JSONResponse({"output": saved.detail_dict()})

    if request.method == "PATCH":
        try:
            raw = await _json_body(request)
            if set(raw) != {"title"}:
                raise ValueError("제목만 수정할 수 있습니다.")
            title = validate_output_title(raw.get("title"))
            saved = await output_store.update_output_title(uid, output_id, title)
        except ValueError as exc:
            return JSONResponse({"error": {"code": "invalid_saved_output", "message": str(exc)}}, status_code=422)
        except Exception:
            return _unavailable()
        if saved is None:
            return _not_found()
        return JSONResponse({"output": saved.detail_dict()})

    try:
        deleted = await output_store.delete_output(uid, output_id)
    except Exception:
        return _unavailable()
    if not deleted:
        return _not_found()
    return JSONResponse({"deleted": True, "id": output_id})
