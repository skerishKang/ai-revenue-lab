from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .history import HistoryStore, validate_conversation_id, validate_project_id
from .history import PRODUCT_SCOPE_CHAT
from .saved_outputs import (
    MAX_OUTPUT_LIST,
    ListCursorError,
    SavedOutputStore,
    validate_output_content,
    validate_output_id,
    validate_output_title,
)

# 행 한도(saved_outputs.MAX_OUTPUT_ROW_BYTES = 2MB, D1 2MiB 정합)와 정렬 — 2026-11-02 한도 감사 "바로 바꿔도 되는 것" 1번.
MAX_OUTPUT_BODY_BYTES = 2_000_000


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
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_OUTPUT_BODY_BYTES)
    except RequestBodyTooLarge as exc:
        raise ValueError("저장할 답변 요청이 너무 큽니다.") from exc
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
        conversation = await history.get_conversation(user_id, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
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
        # #5882: 목록은 페이지로 이어진다. 커서 없는 호출은 예전 그대로 첫 페이지(100건)를
        # 받고, 추가 키 next_cursor 는 모르는 클라이언트가 그냥 무시한다.
        raw_limit = request.query_params.get("limit")
        limit = MAX_OUTPUT_LIST
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": {"code": "invalid_limit", "message": "limit 은 정수여야 합니다."}},
                    status_code=400,
                )
            if limit < 1:
                return JSONResponse(
                    {"error": {"code": "invalid_limit", "message": "limit 은 1 이상이어야 합니다."}},
                    status_code=400,
                )
        raw_cursor = request.query_params.get("cursor")
        cursor = raw_cursor.strip() if isinstance(raw_cursor, str) else None
        if not cursor:
            cursor = None
        page_fn = getattr(output_store, "list_outputs_page", None)
        try:
            if callable(page_fn):
                outputs, next_cursor = await page_fn(uid, limit=limit, cursor=cursor)
            else:
                outputs, next_cursor = await output_store.list_outputs(uid), None
        except ListCursorError:
            return JSONResponse(
                {
                    "error": {
                        "code": "invalid_cursor",
                        "message": "목록을 이어 볼 위치가 올바르지 않습니다. 처음부터 다시 열어 주세요.",
                    }
                },
                status_code=400,
            )
        except Exception:
            return _unavailable()
        return JSONResponse({
            "outputs": [item.summary_dict() for item in outputs],
            "next_cursor": next_cursor,
        })

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
