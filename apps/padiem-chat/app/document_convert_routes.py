"""PDF to Markdown utility routes (#5568).

One signed-in owner, one work ledger, one conversion per request. The browser
drives the ledger item by item, so a multi-file upload shows per-file progress,
keeps the files that already succeeded when one fails, and survives navigating
away — the state lives in D1 and R2, not in the page.

Storage reuses the private workspace R2 binding and the existing bounded binary
upload reader; the conversion reuses Core's reviewed pypdf boundary through
``padiem_ai_core.pdf_markdown``. No new binding, account system or job engine.

The hot upload path stays at the magic check + R2 + D1: it does not run the
expensive pypdf inspection, so a PDF upload cannot push the Worker past its
resource budget (#5568 production 503). The page count and native-text state
are deferred to the explicit conversion step, which is the only pypdf site on
this surface. A magic-valid but unreadable body is a queued item that fails at
conversion time.
"""

from __future__ import annotations

import inspect
import io
import json
import zipfile
from urllib.parse import quote, unquote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import (
    RequestBodyTooLarge,
    open_bounded_spooled_request,
    read_bounded_request_body,
)
from .document_convert_store import (
    D1DocumentConvertStore,
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_REVIEWED,
    JOB_STATUS_WORKING,
    MAX_DOCUMENT_JOBS_PAGE,
    markdown_object_key,
    validate_item_id,
    validate_job_id,
)
from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    DocumentNormalizationError,
    _read_member_bounded,
    validate_ooxml_member_name,
)
from padiem_ai_core.pdf_markdown import (
    CONVERT_MODE_FAST,
    CONVERT_MODE_PRECISE,
    ConversionNotices,
    PRECISE_MODE_UNAVAILABLE,
    SUPPORTED_CONVERT_MODES,
    convert_pdf_to_markdown,
)

PDF_MEDIA_TYPE = "application/pdf"
ZIP_MEDIA_TYPE = "application/zip"
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"
#: Raw uploads travel as an octet stream with the document type declared in
#: ``X-Padiem-Media-Type``, which is the binary upload convention this app's
#: same-origin guard already exempts by exact route shape.
UPLOAD_MEDIA_TYPE = "application/octet-stream"
UPLOAD_MEDIA_TYPES = frozenset({PDF_MEDIA_TYPE, ZIP_MEDIA_TYPE})
MAX_JOB_BODY_BYTES = 4_096
_NO_STORE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}

#: Core stays locale-free, so the sentence is owned here. It states the absence and
#: states that nothing was guessed — the page is never silently left blank.
_PRODUCT_NOTICES = ConversionNotices(
    unreadable_page=(
        "이 페이지에는 추출 가능한 텍스트 레이어가 없습니다. 정밀 변환(OCR)은 이 제품에 "
        "연결되어 있지 않아 내용을 추측해 채우지 않았습니다."
    ),
)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _unauthorized() -> JSONResponse:
    return _error("unauthorized", "문서 변환을 사용하려면 로그인이 필요합니다.", 401)


def _unavailable() -> JSONResponse:
    return _error("document_convert_unavailable", "문서 변환을 현재 사용할 수 없습니다.", 503)


def _not_found() -> JSONResponse:
    return _error("document_convert_not_found", "변환 작업을 찾을 수 없습니다.", 404)


async def _r2_call(bucket, method: str, *args, **kwargs):
    result = getattr(bucket, method)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _bucket(request: Request):
    store = getattr(request.app.state, "workspace_document_store", None)
    return getattr(store, "r2_bucket", None)


async def _object_bytes(obj) -> bytes:
    """Read one R2 object fully, accepting the native and JS object shapes."""

    if obj is None:
        return b""
    body = getattr(obj, "body", None)
    if isinstance(body, (bytes, bytearray, memoryview)):
        return bytes(body)
    read_bytes = getattr(body, "bytes", None)
    if callable(read_bytes):
        payload = read_bytes()
        if inspect.isawaitable(payload):
            payload = await payload
        return bytes(payload)
    if body is not None and hasattr(body, "__aiter__"):
        collected = bytearray()
        async for chunk in body:
            collected.extend(chunk)
        return bytes(collected)
    array_buffer = getattr(obj, "arrayBuffer", None)
    if callable(array_buffer):
        payload = array_buffer()
        if inspect.isawaitable(payload):
            payload = await payload
        as_bytes = getattr(payload, "to_bytes", None)
        return as_bytes() if callable(as_bytes) else bytes(payload)
    return bytes(body if body is not None else obj)


async def _identity(request: Request):
    """Verified owner plus the state this route set needs, or an HTTP refusal."""

    if not auth_ready(request):
        return None, None, None, _unauthorized()
    uid = current_user_id(request)
    if uid is None:
        return None, None, None, _unauthorized()
    ledger = getattr(request.app.state, "document_convert_store", None)
    if not isinstance(ledger, D1DocumentConvertStore):
        return None, None, None, _unavailable()
    bucket = _bucket(request)
    if bucket is None:
        return None, None, None, _unavailable()
    return uid, ledger, bucket, None


def _attachment_headers(filename: str, *, inline: bool = False) -> dict[str, str]:
    disposition = "inline" if inline else "attachment"
    return {
        **_NO_STORE,
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}",
    }


def _stem(name: str) -> str:
    cleaned = (name or "").replace("\r", "").replace("\n", "").replace('"', "'").strip()
    base = cleaned[:120].rsplit(".", 1)[0] if "." in cleaned[:120] else cleaned[:116]
    return base or "document"


def _markdown_name(name: str) -> str:
    return f"{_stem(name)}.md"


async def convert_jobs_collection(request: Request):
    """POST opens one work ledger; GET lists the owner's recent ledgers."""

    uid, ledger, _bucket_ref, error = await _identity(request)
    if error is not None:
        return error
    if request.method == "GET":
        raw_limit = request.query_params.get("limit")
        limit = MAX_DOCUMENT_JOBS_PAGE
        if raw_limit not in (None, ""):
            if not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= MAX_DOCUMENT_JOBS_PAGE:
                return _error("invalid_limit", "요청 페이지 크기가 올바르지 않습니다.", 400)
            limit = int(raw_limit)
        try:
            jobs = await ledger.list_jobs(uid, limit=limit)
        except Exception:
            return _unavailable()
        return JSONResponse({"jobs": [job.public_dict() for job in jobs], "limit": limit})

    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_JOB_BODY_BYTES)
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict) or set(raw) - {"mode"}:
            raise ValueError("shape")
        mode = raw.get("mode") or CONVERT_MODE_FAST
        if mode == CONVERT_MODE_PRECISE:
            return precise_mode_unavailable()
        if mode not in SUPPORTED_CONVERT_MODES:
            raise ValueError("mode")
    except RequestBodyTooLarge:
        return _error("invalid_request", "요청이 너무 큽니다.", 413)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _error("invalid_request", '요청은 {"mode": "fast"|"verify"} 형식이어야 합니다.', 422)
    try:
        job = await ledger.create_job(uid, mode=mode)
    except Exception:
        return _unavailable()
    return JSONResponse({"job": job.public_dict()}, status_code=201)


def precise_mode_unavailable() -> JSONResponse:
    """정밀 변환 is refused with the engine's own code, never faked as running."""

    return _error(
        PRECISE_MODE_UNAVAILABLE,
        "정밀 변환(OCR)은 현재 이 제품에 연결되어 있지 않습니다. 빠른 변환과 검증 변환을 사용하세요.",
        422,
    )


async def _resolve_job(request: Request):
    uid, ledger, bucket, error = await _identity(request)
    if error is not None:
        return None, None, None, None, error
    try:
        job_id = validate_job_id(request.path_params.get("job_id"))
    except ValueError:
        job_id = None
    if job_id is None:
        return None, None, None, None, _not_found()
    try:
        job = await ledger.get_job(uid, job_id)
    except Exception:
        return None, None, None, None, _unavailable()
    if job is None:
        return None, None, None, None, _not_found()
    return uid, ledger, bucket, job, None


def _pdf_members(spool):
    """Yield every member of an uploaded archive, path-checked and inflate-bounded.

    Member names go through the repository's one archive path-safety predicate and
    every read goes through the canonical bounded member reader, so a declared
    size cannot be amplified by the deflate stream past the byte ceiling a single
    document upload already carries. A member that is not a PDF is still yielded;
    the upload loop rejects it with ``pdf_magic_mismatch`` so the caller sees
    what was not converted.
    """

    with zipfile.ZipFile(spool) as archive:
        inflated = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            member_name = validate_ooxml_member_name(info.filename)
            payload = _read_member_bounded(
                archive, info, max_bytes=MAX_BINARY_DOCUMENT_BYTES
            )
            inflated += len(payload)
            if inflated > MAX_BINARY_DOCUMENT_BYTES:
                raise DocumentNormalizationError(
                    "archive_expansion_limit",
                    "The archive expands past the bytes one document upload may carry.",
                )
            yield member_name.rsplit("/", 1)[-1], payload


async def convert_job_files(request: Request):
    """Upload one PDF, or a ZIP of PDFs, into an existing work ledger."""

    uid, ledger, bucket, job, error = await _resolve_job(request)
    if error is not None:
        return error
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    declared_media = request.headers.get("x-padiem-media-type")
    encoded_name = request.headers.get("x-padiem-filename")
    if (
        media_type != UPLOAD_MEDIA_TYPE
        or declared_media not in UPLOAD_MEDIA_TYPES
        or not encoded_name
        or len(encoded_name) > 512
    ):
        return _error("invalid_document", "PDF 또는 ZIP 파일만 업로드할 수 있습니다.", 422)
    upload_kind = declared_media
    try:
        upload_name = unquote(encoded_name, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return _error("invalid_document", "파일 이름이 올바르지 않습니다.", 422)
    created = []
    rejected: list[dict[str, str]] = []
    try:
        async with open_bounded_spooled_request(
            request, max_bytes=MAX_BINARY_DOCUMENT_BYTES
        ) as spool:
            if upload_kind == ZIP_MEDIA_TYPE:
                members = _pdf_members(spool)
            else:
                single = spool.read()
                members = iter([(upload_name, single)])
            for name, payload in members:
                if not payload.startswith(b"%PDF-"):
                    rejected.append({"name": name[:120], "code": "pdf_magic_mismatch"})
                    continue
                item = None
                try:
                    # #5568 CPU offload: keep the hot upload path at the magic
                    # check + R2 + D1. The expensive pypdf inspection (page
                    # count, native-text state) is deferred to the explicit
                    # conversion step, so a PDF upload cannot push the Worker
                    # past its resource budget. A magic-valid but unreadable
                    # body becomes a queued item that fails at conversion time,
                    # exactly as the module contract already describes.
                    item = await ledger.add_item(
                        uid, job.id, name=name, page_count=0, probe=None
                    )
                    await _r2_call(
                        bucket, "put", item.original_key, payload,
                        httpMetadata={"contentType": PDF_MEDIA_TYPE},
                    )
                except Exception:
                    if item is not None:
                        await _discard(ledger, bucket, uid, item.id, item.original_key)
                    return _unavailable()
                created.append(item)
    except RequestBodyTooLarge:
        return _error("document_too_large", "파일이 너무 큽니다.", 413)
    except DocumentNormalizationError as exc:
        return _error(exc.code, "업로드한 문서를 읽을 수 없습니다.", 422)
    except zipfile.BadZipFile:
        return _error("invalid_archive", "압축 파일을 열 수 없습니다.", 422)
    except Exception:
        return _unavailable()
    if not created and not rejected:
        return _error("empty_archive", "변환할 PDF가 없습니다.", 422)
    if not created:
        return _error(
            rejected[0]["code"], "업로드한 문서를 변환 대상으로 읽을 수 없습니다.", 422
        )
    try:
        refreshed = await ledger.refresh_job(uid, job.id)
    except Exception:
        refreshed = None
    return JSONResponse(
        {
            "job": (refreshed or job).public_dict(),
            "items": [item.public_dict() for item in created],
            "rejected": rejected,
        },
        status_code=201,
    )


async def _discard(
    ledger, bucket, uid: str, item_id: str, original_key: str) -> None:
    """Roll back a half-written item so no ledger row points at absent bytes."""

    try:
        await ledger.delete_item(uid, item_id)
    except Exception:
        pass
    try:
        await _r2_call(bucket, "delete", original_key)
    except Exception:
        pass


async def _resolve_item(request: Request):
    uid, ledger, bucket, error = await _identity(request)
    if error is not None:
        return None, None, None, None, None, error
    try:
        item_id = validate_item_id(request.path_params.get("item_id"))
    except ValueError:
        item_id = None
    if item_id is None:
        return None, None, None, None, None, _not_found()
    try:
        item = await ledger.get_item(uid, item_id)
    except Exception:
        return None, None, None, None, None, _unavailable()
    if item is None:
        return None, None, None, None, None, _not_found()
    try:
        job = await ledger.get_job(uid, item.job_id)
    except Exception:
        return None, None, None, None, None, _unavailable()
    if job is None:
        return None, None, None, None, None, _not_found()
    return uid, ledger, bucket, item, job, None


async def convert_item_run(request: Request):
    """Convert one queued item with the adopted engine and store its Markdown."""

    resolved = await _resolve_item(request)
    if resolved[-1] is not None:
        return resolved[-1]
    uid, ledger, bucket, item, job, _error = resolved
    if item.markdown_key is not None:
        return JSONResponse({"item": item.public_dict(), "job": job.public_dict()})
    try:
        working = await ledger.set_item_status(uid, item.id, JOB_STATUS_WORKING)
    except Exception:
        return _unavailable()
    if working is None:
        return _unavailable()
    try:
        obj = await _r2_call(bucket, "get", item.original_key)
        payload = await _object_bytes(obj)
        result = convert_pdf_to_markdown(
            name=item.name, media_type=PDF_MEDIA_TYPE, payload=payload,
            mode=job.mode, notices=_PRODUCT_NOTICES,
        )
    except DocumentNormalizationError as exc:
        return await _fail(ledger, uid, item, job, exc.code, 422)
    except Exception:
        return await _fail(ledger, uid, item, job, "convert_failed", 503)
    key = markdown_object_key(uid, job.id, item.id)
    try:
        await _r2_call(
            bucket, "put", key, result.markdown.encode("utf-8"),
            httpMetadata={"contentType": "text/markdown"},
        )
        done = await ledger.complete_item(
            uid,
            item.id,
            status=JOB_STATUS_REVIEWED,
            page_count=result.page_count,
            character_count=len(result.markdown),
            markdown_key=key,
            report=result.public_dict(),
            error_code=None,
        )
        refreshed = await ledger.refresh_job(uid, job.id)
    except Exception:
        try:
            await _r2_call(bucket, "delete", key)
        except Exception:
            pass
        return await _fail(ledger, uid, item, job, "convert_store_unavailable", 503)
    if done is None:
        return _unavailable()
    return JSONResponse({"item": done.public_dict(), "job": (refreshed or job).public_dict()})


async def _fail(ledger, uid: str, item, job, code: str, status: int) -> JSONResponse:
    """Mark only this item failed; the ledger keeps every result that did succeed."""

    try:
        failed = await ledger.complete_item(
            uid,
            item.id,
            status=JOB_STATUS_FAILED,
            page_count=item.page_count,
            character_count=0,
            markdown_key=None,
            report=None,
            error_code=code,
        )
        refreshed = await ledger.refresh_job(uid, job.id)
    except Exception:
        return _unavailable()
    return JSONResponse(
        {
            "item": (failed or item).public_dict(),
            "job": (refreshed or job).public_dict(),
        },
        status_code=status,
    )


async def convert_item_review(request: Request):
    """검토 완료 — the owner accepted this result, so the item reaches 완료."""

    resolved = await _resolve_item(request)
    if resolved[-1] is not None:
        return resolved[-1]
    uid, ledger, _bucket, item, job, _error = resolved
    if item.markdown_key is None:
        return _not_found()
    try:
        updated = await ledger.set_item_status(uid, item.id, JOB_STATUS_DONE)
        refreshed = await ledger.refresh_job(uid, job.id)
    except Exception:
        return _unavailable()
    if updated is None:
        return _unavailable()
    return JSONResponse({"item": updated.public_dict(), "job": (refreshed or job).public_dict()})


async def _stream_object(bucket, key: str, media_type: str, headers: dict[str, str]):
    try:
        obj = await _r2_call(bucket, "get", key)
    except Exception:
        return _unavailable()
    if obj is None:
        return _not_found()
    body = getattr(obj, "body", None)

    async def chunks():
        if body is not None and hasattr(body, "__aiter__"):
            async for chunk in body:
                yield bytes(chunk)
        elif body is not None and hasattr(body, "getReader"):
            reader = body.getReader()
            try:
                while True:
                    chunk = reader.read()
                    if inspect.isawaitable(chunk):
                        chunk = await chunk
                    if chunk.get("done"):
                        break
                    yield bytes(chunk["value"])
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

    return StreamingResponse(chunks(), media_type=media_type, headers=headers)


async def convert_item_markdown(request: Request):
    """Read or download one converted item's Markdown — never by a raw R2 key."""

    resolved = await _resolve_item(request)
    if resolved[-1] is not None:
        return resolved[-1]
    _uid, _ledger, bucket, item, _job, _error = resolved
    if item.markdown_key is None:
        return _not_found()
    return await _stream_object(
        bucket,
        item.markdown_key,
        MARKDOWN_MEDIA_TYPE,
        _attachment_headers(
            _markdown_name(item.name), inline=request.query_params.get("display") == "inline"
        ),
    )


async def convert_item_original(request: Request):
    """Stream the preserved original PDF back to its own owner."""

    resolved = await _resolve_item(request)
    if resolved[-1] is not None:
        return resolved[-1]
    _uid, _ledger, bucket, item, _job, _error = resolved
    return await _stream_object(
        bucket,
        item.original_key,
        PDF_MEDIA_TYPE,
        _attachment_headers(
            f"{_stem(item.name)}.pdf", inline=request.query_params.get("display") == "inline"
        ),
    )


async def convert_item_detail(request: Request):
    """One item's own state and bounded report — what Screen B reviews."""

    resolved = await _resolve_item(request)
    if resolved[-1] is not None:
        return resolved[-1]
    _uid, _ledger, _bucket, item, job, _error = resolved
    return JSONResponse({"item": item.public_dict(), "job": job.public_dict()})


async def convert_item_delete(request: Request):
    """Drop one item's rows and objects; the ledger and its other results stay."""

    resolved = await _resolve_item(request)
    if resolved[-1] is not None:
        return resolved[-1]
    uid, ledger, bucket, item, job, _error = resolved
    try:
        removed = await ledger.delete_item(uid, item.id)
    except Exception:
        return _unavailable()
    if not removed:
        return _not_found()
    for key in (item.original_key, item.markdown_key):
        if key:
            try:
                await _r2_call(bucket, "delete", key)
            except Exception:
                pass
    try:
        refreshed = await ledger.refresh_job(uid, job.id)
    except Exception:
        refreshed = None
    return JSONResponse({"job": (refreshed or job).public_dict()})


async def convert_job_detail(request: Request):
    resolved = await _resolve_job(request)
    if resolved[-1] is not None:
        return resolved[-1]
    uid, ledger, _bucket, job, _error = resolved
    try:
        items = await ledger.list_items(uid, job.id)
    except Exception:
        return _unavailable()
    return JSONResponse({"job": job.public_dict(), "items": [item.public_dict() for item in items]})


async def convert_job_archive(request: Request):
    """One ZIP of every converted Markdown in the ledger, plus a bounded manifest."""

    resolved = await _resolve_job(request)
    if resolved[-1] is not None:
        return resolved[-1]
    uid, ledger, bucket, job, _error = resolved
    try:
        items = await ledger.list_items(uid, job.id)
    except Exception:
        return _unavailable()
    converted = [item for item in items if item.markdown_key is not None]
    if not converted:
        return _not_found()
    bundle = io.BytesIO()
    used_names: set[str] = set()
    manifest: list[dict[str, object]] = []
    try:
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in converted:
                obj = await _r2_call(bucket, "get", item.markdown_key)
                if obj is None:
                    continue
                payload = await _object_bytes(obj)
                base = _markdown_name(item.name)
                member = base
                counter = 2
                while member in used_names:
                    member = f"{base[:-3]}-{counter}.md"
                    counter += 1
                used_names.add(member)
                archive.writestr(validate_ooxml_member_name(member), payload)
                report = item.report or {}
                manifest.append({
                    "member": member,
                    "name": item.name,
                    "page_count": item.page_count,
                    "character_count": item.character_count,
                    "status": item.status,
                    "mode": job.mode,
                    "warnings": report.get("warnings", []),
                    "mismatches": report.get("mismatches", []),
                })
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "job_id": job.id,
                        "mode": job.mode,
                        "converted": len(manifest),
                        "failed": [
                            {"name": item.name, "code": item.error_code}
                            for item in items
                            if item.status == JOB_STATUS_FAILED
                        ],
                        "files": manifest,
                    },
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )
    except Exception:
        return _unavailable()
    return Response(
        content=bundle.getvalue(),
        media_type=ZIP_MEDIA_TYPE,
        headers=_attachment_headers(f"pdf-to-markdown-{job.id}.zip"),
    )
