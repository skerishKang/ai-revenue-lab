from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .binary_documents import BinaryDocumentValidationError, parse_binary_document_item
from .documents import DocumentValidationError, validate_document_fields
from .history import HistoryStore, validate_project_id
from .project_files import (
    BINARY_PROJECT_FILE_MEDIA,
    DEFAULT_OWNER_FILES_PAGE,
    MAX_OWNER_FILES_PAGE,
    OwnerFileCursorError,
    ProjectFileLimitError,
    ProjectFileStore,
    _extracted_media_type,
    decode_owner_file_cursor,
    encode_owner_file_cursor,
    validate_file_id,
)

MAX_PROJECT_FILE_BODY_BYTES = 160_000
MAX_BINARY_PROJECT_FILE_BASE64_BYTES = ((2 * 1024 * 1024 + 2) // 3) * 4 + 4  # 2 MiB binary cap, base64-expanded


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


def _parse_project_file_item(raw: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(raw, dict):
        raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
    keys = set(raw)
    text_item = keys == {"name", "media_type", "text"}
    binary_item = keys == {"name", "media_type", "base64"}
    if not text_item and not binary_item:
        raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
    if text_item:
        document = validate_document_fields(raw.get("name"), raw.get("media_type"), raw.get("text"))
        return document.name, document.media_type, document.text
    name = raw.get("name")
    media_type = raw.get("media_type")
    if media_type not in BINARY_PROJECT_FILE_MEDIA:
        raise BinaryDocumentValidationError("PDF, DOCX 문서만 이 형식으로 첨부할 수 있습니다.")
    try:
        document = parse_binary_document_item({"type": "document", "name": name, "media_type": media_type, "base64": raw.get("base64")})
    except BinaryDocumentValidationError as exc:
        raise ValueError(str(exc)) from exc
    return document.name, _extracted_media_type(document.media_type), document.text


def _bad_request(field: str) -> JSONResponse:
    messages = {
        "limit": "요청 페이지 크기가 올바르지 않습니다.",
        "cursor": "요청 이어읽기 값이 올바르지 않습니다.",
    }
    return JSONResponse(
        {"error": {"code": f"invalid_{field}", "message": messages[field]}},
        status_code=400,
    )


def _parse_owner_files_limit(raw: str | None) -> int:
    if raw is None or raw == "":
        return DEFAULT_OWNER_FILES_PAGE
    if not raw.isdecimal():
        raise ValueError("limit")
    value = int(raw)
    if value < 1 or value > MAX_OWNER_FILES_PAGE:
        raise ValueError("limit")
    return value


async def owner_files_collection(request: Request) -> JSONResponse:
    """#4489 — one bounded keyset page over every file the signed-in owner stored.

    Read-only and owner-scoped: the verified session user is the only selector, so no
    caller-supplied account, project list or product scope can widen the result. A cursor
    that cannot be decoded is refused instead of being silently treated as a first page,
    and there is deliberately no per-project fan-out fallback — a partial read must never
    be presented as this account's whole history.
    """
    if not auth_ready(request) or request.app.state.project_file_store is None:
        return _unavailable()
    uid = current_user_id(request)
    if uid is None:
        return _unauthorized()
    store: ProjectFileStore = request.app.state.project_file_store
    list_owner_files = getattr(store, "list_owner_files", None)
    if not callable(list_owner_files):
        return _unavailable()
    params = request.query_params
    try:
        limit = _parse_owner_files_limit(params.get("limit"))
    except ValueError:
        return _bad_request("limit")
    cursor = params.get("cursor")
    after = None
    if cursor not in (None, ""):
        try:
            after = decode_owner_file_cursor(cursor)
        except OwnerFileCursorError:
            return _bad_request("cursor")
    try:
        rows = await list_owner_files(uid, after=after, limit=limit + 1)
    except Exception:
        return _unavailable()
    has_more = len(rows) > limit
    page = rows[:limit]
    return JSONResponse({
        "files": [item.public_dict() for item in page],
        "next_cursor": encode_owner_file_cursor(page[-1]) if has_more and page else None,
        "has_more": has_more,
        "limit": limit,
    })


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

    try:
        body = await read_bounded_request_body(
            request,
            max_bytes=MAX_BINARY_PROJECT_FILE_BASE64_BYTES,
        )
    except RequestBodyTooLarge:
        return JSONResponse({"error": {"code": "invalid_document", "message": "문서 요청이 너무 큽니다."}}, status_code=413)
    try:
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
        name, media_type, text = _parse_project_file_item(raw)
        created = await store.create_file(uid, pid, name, media_type, text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, DocumentValidationError, BinaryDocumentValidationError) as exc:
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
