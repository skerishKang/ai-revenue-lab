from __future__ import annotations

import json
import inspect
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body, open_bounded_spooled_request
from padiem_ai_core.document_normalization import DocumentNormalizationError, MAX_BINARY_DOCUMENT_BYTES
from padiem_ai_core.document_parser_boundary import (
    parse_binary_document_via_authority_async,
    production_worker_runtime,
)
from .documents import DocumentValidationError, validate_document_fields
from .history import HistoryStore, validate_project_id
from .request_contract import COUNTRIES
from .project_files import (
    BINARY_PROJECT_FILE_MEDIA,
    DEFAULT_OWNER_FILES_PAGE,
    IMAGE_PROJECT_FILE_MEDIA,
    MAX_OWNER_FILES_PAGE,
    OwnerFileCursorError,
    ProjectFileLimitError,
    ProjectFileStore,
    UTIL_DOC_KINDS,
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


class OriginalStorageUnavailable(RuntimeError):
    """The original-bytes bucket is not bound; the row cannot keep its original."""


async def save_binary_project_file(request: Request, *, uid: str, pid: str, name: str, media_type: str, data):
    """Store one binary project file through the unchanged save flow.

    *data* is a seekable binary file (the direct route's spool or the tus
    completion file); the helper seeks as needed. Shared by both entry points so
    the tus hand-off keeps the same parsing authority, row creation and
    original-bytes object storage (docs/research/LARGE_UPLOAD_1GB_DESIGN_20261101.md
    A안 1단계). Raises the validation errors the collection route already maps
    (DocumentValidationError · DocumentNormalizationError · ValueError ·
    ProjectFileLimitError) and OriginalStorageUnavailable for storage outages.
    """
    store: ProjectFileStore = request.app.state.project_file_store
    image_body = None
    if media_type in IMAGE_PROJECT_FILE_MEDIA:
        # #5728 — an image is preserved byte-for-byte: no document
        # parser runs, the stored record keeps its original
        # media_type and an empty text body, and the owner re-reads
        # the exact original through the /original route. The
        # declared type must still match the actual bytes — the
        # same honesty the document path enforces through its
        # parser's format checks.
        image_body = data.read()
        if not image_media_type_matches(media_type, image_body[:12]):
            raise DocumentValidationError("이미지 형식이 일치하지 않습니다.")
        created = await store.create_file(uid, pid, name, media_type, "")
    else:
        # Local Core PDF parsing can use the seekable file directly.
        # The Worker isolated-parser wire contract still requires bytes.
        source = data if media_type == "application/pdf" and not production_worker_runtime() else data.read()
        parsed = await parse_binary_document_via_authority_async(
            name=name, media_type=media_type, payload=source,
        )
        created = await store.create_file(
            uid, pid, parsed.name, _extracted_media_type(parsed.media_type), parsed.text,
        )
    workspace_store = getattr(request.app.state, "workspace_document_store", None)
    bucket = getattr(workspace_store, "r2_bucket", None)
    if bucket is None:
        await store.delete_file(uid, pid, created.id)
        raise OriginalStorageUnavailable()
    try:
        if image_body is not None:
            # The image bytes were already read whole for the
            # magic check; storing them avoids a second pass.
            await _r2_call(
                bucket, "put", _project_original_object_key(uid, pid, created.id),
                image_body, httpMetadata={"contentType": media_type},
            )
        else:
            data.seek(0)
            # #6579 step 2: a 1 GiB original must not become one `bytes` object.
            # A bound store that offers a streaming write gets the file itself
            # (moved when it shares the filesystem, bounded blocks otherwise).
            # The Cloudflare binding is bytes-only today, so it keeps the exact
            # contract this route already had — the original is never dropped or
            # half-written either way.
            key = _project_original_object_key(uid, pid, created.id)
            write_stream = getattr(bucket, "put_stream", None)
            if callable(write_stream):
                written = write_stream(key, data, {"contentType": media_type})
                if inspect.isawaitable(written):
                    await written
            else:
                # R2 Python binding receives bytes; avoid a second parse-time
                # copy for PDFs while preserving the existing storage contract.
                await _r2_call(
                    bucket, "put", key, data.read(),
                    httpMetadata={"contentType": media_type},
                )
    except Exception:
        await store.delete_file(uid, pid, created.id)
        raise OriginalStorageUnavailable() from None
    return created


#: #5882 PR-E — the request body bound follows the row's own ceiling instead of
#: the former arbitrary 160,000 bytes. The body carries exactly one row's text in
#: JSON, so it is the D1 per-row byte limit (project_files.PROJECT_FILE_MAX_TEXT_BYTES
#: = 2_097_152) plus a 256 KiB envelope for the id/name/media-type keys. A body
#: past the row limit could never be stored, so refusing it here only turns a D1
#: error into the route's own Korean guidance. Kept as a literal so the platform
#: integration contract can read it without executing this module.
MAX_PROJECT_FILE_BODY_BYTES = 2_359_296


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


def _parse_project_file_item(raw: dict[str, Any]) -> tuple[str, str, str, str, str]:
    if not isinstance(raw, dict):
        raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
    if set(raw) - {"name", "media_type", "text", "country", "doc_kind"}:
        raise ValueError("Project text documents require name, media_type and text; binary files use raw upload.")
    if not {"name", "media_type", "text"} <= set(raw):
        raise ValueError("Project text documents require name, media_type and text; binary files use raw upload.")
    # #6046 — 국가는 필수가 아니다. 없으면 kr(기존 문서와 같은 규칙).
    country = raw.get("country", "kr")
    if not isinstance(country, str) or country not in COUNTRIES:
        raise ValueError("국가 식별자가 올바르지 않습니다.")
    # #5731 — 종류는 저장하는 화면이 남기는 표시다. 모르는 값은 거절하고,
    # 없는 값은 ''(기타)로 남겨 예전 문서와 섞이지 않게 한다.
    doc_kind = raw.get("doc_kind", "")
    if not isinstance(doc_kind, str) or (doc_kind and doc_kind not in UTIL_DOC_KINDS):
        raise ValueError("문서 종류가 올바르지 않습니다.")
    document = validate_document_fields(raw.get("name"), raw.get("media_type"), raw.get("text"))
    return document.name, document.media_type, document.text, country, doc_kind


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
        country_filter = request.query_params.get("country")
        if country_filter is not None and country_filter not in COUNTRIES:
            return JSONResponse(
                {"error": {"code": "invalid_country", "message": "국가 식별자가 올바르지 않습니다."}},
                status_code=400,
            )
        try:
            # 국가 필터를 요구한 경우에만 인자를 넘긴다: 필터 없는 호출은 오늘과 같은 호출 계약이다.
            if country_filter is None:
                files = await store.list_files(uid, pid)
            else:
                files = await store.list_files(uid, pid, country=country_filter)
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
                created = await save_binary_project_file(
                    request, uid=uid, pid=pid, name=name, media_type=media_type, data=spool,
                )
                return JSONResponse({"file": created.public_dict()}, status_code=201)
        except RequestBodyTooLarge:
            return JSONResponse({"error": {"code": "invalid_document"}}, status_code=413)
        except (ValueError, DocumentNormalizationError, DocumentValidationError, ProjectFileLimitError) as exc:
            if media_type == "application/hwp+zip":
                from .binary_documents import guidance_for_reason_code
                message = guidance_for_reason_code(getattr(exc, "code", ""), media_type)
                message = message or "HWPX 파일을 읽지 못했습니다. 파일을 확인해 주세요."
            else:
                message = str(exc)
            return JSONResponse({"error": {"code": "invalid_document", "message": message}}, status_code=422)
        except Exception:
            return _unavailable()
    try:
        body = await read_bounded_request_body(
            request, max_bytes=MAX_PROJECT_FILE_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_document",
                    # #5882 PR-E — the platform bound is now stated with the way out
                    # instead of a bare "too large".
                    "message": "본문이 너무 길어요 — 내용을 나눠서 올리거나, 원본 파일을 첨부로 올려 주세요.",
                }
            },
            status_code=413,
        )
    try:
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("프로젝트 문서 요청 형식이 올바르지 않습니다.")
        name, media_type, text, country, doc_kind = _parse_project_file_item(raw)
        # #5731 — 같은 이름이 이미 그 종류로 있으면 조용히 하나 더 쌓지 않는다.
        # 화면은 이 409를 받아 [덮어쓸까요 / 새 이름으로 저장]을 묻는다.
        if doc_kind:
            same = await store.find_current_by_name(uid, pid, name, doc_kind)
            if same is not None:
                return JSONResponse(
                    {"error": {
                        "code": "name_conflict",
                        "message": "같은 이름의 글이 이미 있습니다.",
                        "existing": {"id": same.id, "name": same.name},
                    }},
                    status_code=409,
                )
        # 기본값(kr/종류 없음)은 인자를 생략한다: 기존 저장소 대역·스키마와 호출 계약이
        # 오늘과 같아지고, 국가·종류를 쓰는 저장만 새 컬럼을 요구한다.
        extra: dict[str, Any] = {}
        if country != "kr":
            extra["country"] = country
        if doc_kind:
            extra["doc_kind"] = doc_kind
        created = await store.create_file(uid, pid, name, media_type, text, **extra)
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
            record.media_type not in {"extracted/pdf", "extracted/docx", "extracted/hwpx"}
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
            media = {"extracted/pdf": "application/pdf", "extracted/docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "extracted/hwpx": "application/hwp+zip"}[record.media_type]
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

    if request.method == "PUT":
        # #5731 — 덮어쓰기는 새 본문으로 기존 행을 갱신하고, 밀려난 본문을
        # 같은 프로젝트 파일(`<이름> (이전 N)`)로 남긴다. 종류는 보낼 수 있으면
        # 쓰고, 없으면 기존 행의 종류를 그대로 지킨다.
        try:
            body = await read_bounded_request_body(
                request, max_bytes=MAX_PROJECT_FILE_BODY_BYTES,
            )
            raw = json.loads(body.decode("utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                raise ValueError("본문 형식이 올바르지 않습니다.")
            doc_kind = raw.get("doc_kind", "")
            if not isinstance(doc_kind, str) or (doc_kind and doc_kind not in UTIL_DOC_KINDS):
                raise ValueError("문서 종류가 올바르지 않습니다.")
            record = await store.get_file(uid, pid, fid)
            if record is None:
                return _not_found()
            if record.media_type != "text/plain":
                return JSONResponse(
                    {"error": {"code": "invalid_document",
                     "message": "글 문서만 덮어쓸 수 있습니다."}},
                    status_code=422,
                )
            replaced = await store.replace_text(
                uid, pid, fid, raw["text"], doc_kind=doc_kind or record.doc_kind,
            )
        except RequestBodyTooLarge:
            return JSONResponse(
                {"error": {"code": "invalid_document",
                 "message": "본문이 너무 길어요 — 내용을 나눠서 올리거나, 원본 파일을 첨부로 올려 주세요."}},
                status_code=413,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, DocumentValidationError) as exc:
            return JSONResponse(
                {"error": {"code": "invalid_document", "message": str(exc) or "본문 형식이 올바르지 않습니다."}},
                status_code=422,
            )
        except ProjectFileLimitError as exc:
            return JSONResponse({"error": {"code": "project_file_limit", "message": str(exc)}}, status_code=422)
        except Exception:
            return _unavailable()
        if replaced is None:
            return _not_found()
        updated, version = replaced
        return JSONResponse({
            "file": updated.public_dict(),
            "previous": version.public_dict() if version is not None else None,
        })

    try:
        # An original exists only for the new raw-binary project upload path.
        record = await store.get_file(uid, pid, fid)
        if record is None:
            return _not_found()
        if record.media_type in {"extracted/pdf", "extracted/docx", "extracted/hwpx"} or record.media_type in IMAGE_PROJECT_FILE_MEDIA:
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
