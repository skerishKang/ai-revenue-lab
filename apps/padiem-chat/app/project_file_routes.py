from __future__ import annotations

import json
import inspect
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body, open_bounded_spooled_request
from padiem_ai_core.document_normalization import DocumentNormalizationError, MAX_BINARY_DOCUMENT_BYTES
from padiem_ai_core.document_parser_boundary import parse_binary_document_via_authority, production_worker_runtime
from .documents import DocumentValidationError, validate_document_fields
from .history import HistoryStore, validate_project_id
from .project_files import (
    BINARY_PROJECT_FILE_MEDIA,
    DEFAULT_OWNER_FILES_PAGE,
    IMAGE_PROJECT_FILE_MEDIA,
    MAX_OWNER_FILES_PAGE,
    OwnerFileCursorError,
    ProjectFileLimitError,
    ProjectFileStore,
    _extracted_media_type,
    decode_owner_file_cursor,
    encode_owner_file_cursor,
    image_media_type_matches,
    validate_file_id,
)

def _project_original_object_key(user_id: str, project_id: str, file_id: str) -> str:
    # All identifiers originate from an authenticated session and validated IDs.
    return f"projects/{user_id}/{project_id}/originals/{file_id}"


async def _r2_call(bucket, method: str, *args, **kwargs):
    result = getattr(bucket, method)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


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


def _parse_project_file_item(raw: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(raw, dict):
        raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
    if set(raw) != {"name", "media_type", "text"}:
        raise ValueError("Project text documents require name, media_type and text; binary files use raw upload.")
    document = validate_document_fields(raw.get("name"), raw.get("media_type"), raw.get("text"))
    return document.name, document.media_type, document.text


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

    is_binary_upload = request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/octet-stream"
    if is_binary_upload:
        encoded_name = request.headers.get("x-padiem-filename")
        media_type = request.headers.get("x-padiem-media-type")
        if not encoded_name or len(encoded_name) > 512 or media_type not in BINARY_PROJECT_FILE_MEDIA:
            return JSONResponse({"error": {"code": "invalid_document"}}, status_code=422)
        try:
            name = unquote(encoded_name, encoding="utf-8", errors="strict")
            async with open_bounded_spooled_request(request, max_bytes=MAX_BINARY_DOCUMENT_BYTES) as spool:
                image_body = None
                if media_type in IMAGE_PROJECT_FILE_MEDIA:
                    # #5728 — an image is preserved byte-for-byte: no document
                    # parser runs, the stored record keeps its original
                    # media_type and an empty text body, and the owner re-reads
                    # the exact original through the /original route. The
                    # declared type must still match the actual bytes — the
                    # same honesty the document path enforces through its
                    # parser's format checks.
                    image_body = spool.read()
                    if not image_media_type_matches(media_type, image_body[:12]):
                        return JSONResponse(
                            {"error": {"code": "invalid_document", "message": "이미지 형식이 일치하지 않습니다."}},
                            status_code=422,
                        )
                    created = await store.create_file(uid, pid, name, media_type, "")
                else:
                    # Local Core PDF parsing can use the seekable spool directly.
                    # The Worker isolated-parser wire contract still requires bytes.
                    source = spool if media_type == "application/pdf" and not production_worker_runtime() else spool.read()
                    parsed = parse_binary_document_via_authority(
                        name=name, media_type=media_type, payload=source,
                    )
                    created = await store.create_file(
                        uid, pid, parsed.name, _extracted_media_type(parsed.media_type), parsed.text,
                    )
                workspace_store = getattr(request.app.state, "workspace_document_store", None)
                bucket = getattr(workspace_store, "r2_bucket", None)
                if bucket is None:
                    await store.delete_file(uid, pid, created.id)
                    return _unavailable()
                try:
                    if image_body is not None:
                        # The image bytes were already read whole for the
                        # magic check; storing them avoids a second spool pass.
                        await _r2_call(
                            bucket, "put", _project_original_object_key(uid, pid, created.id),
                            image_body, httpMetadata={"contentType": media_type},
                        )
                    else:
                        spool.seek(0)
                        # R2 Python binding receives bytes; avoid a second parse-time
                        # copy for PDFs while preserving the existing storage contract.
                        await _r2_call(
                            bucket, "put", _project_original_object_key(uid, pid, created.id),
                            spool.read(), httpMetadata={"contentType": media_type},
                        )
                except Exception:
                    await store.delete_file(uid, pid, created.id)
                    return _unavailable()
                return JSONResponse({"file": created.public_dict()}, status_code=201)
        except RequestBodyTooLarge:
            return JSONResponse({"error": {"code": "invalid_document"}}, status_code=413)
        except (ValueError, DocumentNormalizationError, DocumentValidationError, ProjectFileLimitError) as exc:
            return JSONResponse({"error": {"code": "invalid_document", "message": str(exc)}}, status_code=422)
        except Exception:
            return _unavailable()
    try:
        body = await read_bounded_request_body(
            request, max_bytes=MAX_PROJECT_FILE_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        return JSONResponse({"error": {"code": "invalid_document", "message": "문서 요청이 너무 큽니다."}}, status_code=413)
    try:
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
        name, media_type, text = _parse_project_file_item(raw)
        created = await store.create_file(uid, pid, name, media_type, text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, DocumentValidationError) as exc:
        return JSONResponse({"error": {"code": "invalid_document", "message": str(exc) or "문서 형식이 올바르지 않습니다."}}, status_code=422)
    except ProjectFileLimitError as exc:
        return JSONResponse({"error": {"code": "project_file_limit", "message": str(exc)}}, status_code=422)
    except Exception:
        return _unavailable()
    return JSONResponse({"file": created.public_dict()}, status_code=201)


async def project_file_original(request: Request) -> Response:
    """Owner/project-scoped binary retrieval by opaque file ID, never by R2 key."""
    uid, pid, error = await _identity(request)
    if error is not None:
        return error
    try:
        fid = validate_file_id(request.path_params.get("file_id"))
    except ValueError:
        return _not_found()
    store: ProjectFileStore = request.app.state.project_file_store
    try:
        record = await store.get_file(uid, pid, fid)
        if record is None or (
            record.media_type not in {"extracted/pdf", "extracted/docx"}
            and record.media_type not in IMAGE_PROJECT_FILE_MEDIA
        ):
            return _not_found()
        workspace_store = getattr(request.app.state, "workspace_document_store", None)
        bucket = getattr(workspace_store, "r2_bucket", None)
        if bucket is None:
            return _unavailable()
        obj = await _r2_call(bucket, "get", _project_original_object_key(uid, pid, fid))
        if obj is None:
            return _not_found()
        if record.media_type in IMAGE_PROJECT_FILE_MEDIA:
            # #5728 — stored originals return with their exact stored type.
            media = record.media_type
        else:
            media = "application/pdf" if record.media_type == "extracted/pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        body = getattr(obj, "body", None)

        async def original_chunks():
            # Prefer R2's native streaming body, never concatenate to one payload.
            if body is not None and hasattr(body, "__aiter__"):
                async for chunk in body:
                    yield bytes(chunk)
            elif body is not None and hasattr(body, "getReader"):
                reader = body.getReader()
                try:
                    while True:
                        item = reader.read()
                        if inspect.isawaitable(item):
                            item = await item
                        if item.get("done"):
                            break
                        yield bytes(item["value"])
                finally:
                    release = getattr(reader, "releaseLock", None)
                    if callable(release):
                        release()
            else:
                array_buffer = getattr(obj, "arrayBuffer", None)
                if callable(array_buffer):
                    payload = array_buffer()
                    if inspect.isawaitable(payload):
                        payload = await payload
                    as_bytes = getattr(payload, "to_bytes", None)
                    yield as_bytes() if callable(as_bytes) else bytes(payload)
                else:
                    yield bytes(body if body is not None else obj)

        return StreamingResponse(original_chunks(), media_type=media, headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        })
    except Exception:
        return _unavailable()


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
        # The detail route is already authenticated and scoped to the current
        # owner and project. Keep collection/public projections content-free,
        # while allowing the owner to reopen the stored text document.
        return JSONResponse({"file": {**record.public_dict(), "content": record.content_text}})

    try:
        # An original exists only for the new raw-binary project upload path.
        record = await store.get_file(uid, pid, fid)
        if record is None:
            return _not_found()
        if record.media_type in {"extracted/pdf", "extracted/docx"} or record.media_type in IMAGE_PROJECT_FILE_MEDIA:
            workspace_store = getattr(request.app.state, "workspace_document_store", None)
            bucket = getattr(workspace_store, "r2_bucket", None)
            if bucket is not None:
                await _r2_call(bucket, "delete", _project_original_object_key(uid, pid, fid))
        deleted = await store.delete_file(uid, pid, fid)
    except Exception:
        return _unavailable()
    if not deleted:
        return _not_found()
    return Response(status_code=204)
