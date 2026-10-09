"""Authenticated B66 customer template source custody routes (#3884 Slice 1).

    POST /api/b66/template-sources            (upload original, JSON+base64)
    GET  /api/b66/template-sources            (owner-scoped list)
    GET  /api/b66/template-sources/{id}       (authenticated original download)

Owner and workspace are always derived from the authenticated session and the
server-owned workspace resolution. A caller-supplied owner/workspace is rejected
rather than honoured. Records owned by another account or workspace are
indistinguishable from missing records (non-disclosing fail-closed). Object
keys and owner ids are never projected to the browser.

There is no approve/compile route in this slice: upload stores status='uploaded'
and nothing else. Same-origin + JSON content-type guarding is provided by the
central #3476 middleware; the base64 body binding follows the repository's
existing non-multipart browser contract.
"""

from __future__ import annotations

import base64
import binascii
import inspect
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .b66_template_source import (
    B66TemplateSourceError,
    MAX_B66_TEMPLATE_SOURCE_BYTES,
    MAX_TEMPLATE_SOURCE_LIST,
    sanitize_original_filename,
    validate_template_source_id,
)
from .claw_memory_routes import _resolve_memory_workspace

_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}

# Client-supplied ownership fields are never authority; their presence is an
# explicit contract violation rather than something silently ignored. Same
# contract as b66_quote_history_routes (#3405).
_CLIENT_OWNER_KEYS = {"userid", "user", "owner", "ownerid", "accountid", "tenantid",
                      "workspaceid", "workspace", "tenant"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE,
    )


def _reject_client_owner(body: Any) -> bool:
    """True when the payload tries to assert its own owner/workspace."""
    if not isinstance(body, dict):
        return False
    for key in body:
        normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
        if normalized in _CLIENT_OWNER_KEYS:
            return True
    return False


async def _owner_and_workspace(request: Request) -> tuple[str, str] | None:
    if not auth_ready(request):
        return None
    try:
        uid = current_user_id(request)
    except Exception:
        return None
    if not uid:
        return None
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        return None
    if not workspace_id:
        return None
    return uid, workspace_id


def _store(request: Request) -> Any | None:
    return getattr(request.app.state, "b66_template_source_store", None)


async def _call(fn, **kwargs):
    value = fn(**kwargs)
    return await value if inspect.isawaitable(value) else value


def _decode_payload(value: object) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def _content_disposition(filename: str) -> str:
    safe = filename.replace("\\", "").replace('"', "")
    ascii_fallback = safe if safe and safe.isascii() else "download.bin"
    quoted = ascii_fallback.replace('"', "")
    try:
        encoded = filename.encode("utf-8")
    except Exception:  # pragma: no cover - str always encodes
        return f'attachment; filename="{quoted}"'
    from urllib.parse import quote

    star = quote(filename, safe="")
    return f'attachment; filename="{quoted}"; filename*=UTF-8\'\'{star}'


async def b66_template_source_upload(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    try:
        body = await request.json()
    except Exception:
        return _error(400, "template_source_body_invalid",
                      "원본 양식 본문을 해석할 수 없습니다.")

    if _reject_client_owner(body):
        return _error(400, "template_source_owner_not_allowed",
                      "소유자 정보는 요청에 포함할 수 없습니다.")

    if not isinstance(body, dict):
        return _error(400, "template_source_body_invalid",
                      "원본 양식 본문을 해석할 수 없습니다.")

    media_type = body.get("media_type")
    raw_filename = body.get("filename")

    try:
        filename = sanitize_original_filename(raw_filename)
    except B66TemplateSourceError:
        return _error(400, "template_source_filename_invalid",
                      "원본 양식 파일 이름이 올바르지 않습니다.")

    payload = _decode_payload(body.get("content_base64"))
    if payload is None or not payload:
        return _error(400, "template_source_body_invalid",
                      "원본 양식 본문을 해석할 수 없습니다.")
    if len(payload) > MAX_B66_TEMPLATE_SOURCE_BYTES:
        return _error(400, "template_source_body_invalid",
                      "원본 양식 파일 크기가 허용 범위를 초과했습니다.")

    store = _store(request)
    put_fn = getattr(store, "put_template_source", None) if store is not None else None
    if not callable(put_fn):
        return _error(503, "template_source_unavailable",
                      "원본 양식 보관 기능을 사용할 수 없습니다.")

    try:
        saved = await _call(
            put_fn,
            user_id=uid,
            workspace_id=workspace_id,
            media_type=media_type,
            original_filename=filename,
            body=payload,
        )
    except B66TemplateSourceError as exc:
        text = str(exc)
        if "media_type" in text:
            return _error(400, "template_source_media_type_invalid",
                          "지원되지 않는 파일 형식입니다.")
        if "size" in text or "bytes" in text:
            return _error(400, "template_source_body_invalid",
                          "원본 양식 파일 크기나 내용이 올바르지 않습니다.")
        if "does not match" in text:
            return _error(400, "template_source_body_invalid",
                          "파일 내용이 선언된 형식과 일치하지 않습니다.")
        return _error(503, "template_source_storage_failed",
                      "원본 양식 저장에 실패했습니다.")
    except Exception:
        return _error(503, "template_source_storage_failed",
                      "원본 양식 저장에 실패했습니다.")

    return JSONResponse(
        {"ok": True, "template_source": saved.public_projection()},
        status_code=201,
        headers=_NO_STORE,
    )


async def b66_template_source_list(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    store = _store(request)
    list_fn = getattr(store, "list_for_owner", None) if store is not None else None
    if not callable(list_fn):
        return _error(503, "template_source_unavailable",
                      "원본 양식 보관 기능을 사용할 수 없습니다.")

    try:
        items = await _call(
            list_fn,
            user_id=uid,
            workspace_id=workspace_id,
            limit=MAX_TEMPLATE_SOURCE_LIST,
        )
    except B66TemplateSourceError:
        return _error(503, "template_source_read_failed",
                      "원본 양식 목록을 읽지 못했습니다.")
    except Exception:
        return _error(503, "template_source_read_failed",
                      "원본 양식 목록을 읽지 못했습니다.")

    return JSONResponse(
        {
            "ok": True,
            "template_sources": [item.public_projection() for item in items or []],
        },
        headers=_NO_STORE,
    )


async def b66_template_source_detail(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    uid, workspace_id = scope

    try:
        template_source_id = validate_template_source_id(
            request.path_params.get("template_source_id", "")
        )
    except B66TemplateSourceError:
        return _error(400, "template_source_id_invalid",
                      "원본 양식 ID 형식이 올바르지 않습니다.")

    store = _store(request)
    get_fn = getattr(store, "get_for_owner", None) if store is not None else None
    if not callable(get_fn):
        return _error(503, "template_source_unavailable",
                      "원본 양식 보관 기능을 사용할 수 없습니다.")

    try:
        result = await _call(
            get_fn,
            user_id=uid,
            workspace_id=workspace_id,
            template_source_id=template_source_id,
        )
    except B66TemplateSourceError:
        return _error(503, "template_source_read_failed",
                      "원본 양식을 읽지 못했습니다.")
    except Exception:
        return _error(503, "template_source_read_failed",
                      "원본 양식을 읽지 못했습니다.")

    if result is None:
        return _error(404, "template_source_not_found",
                      "요청한 원본 양식을 찾을 수 없습니다.")

    metadata, payload = result
    return Response(
        content=payload,
        media_type=metadata.media_type,
        headers={
            **_NO_STORE,
            "Content-Length": str(metadata.byte_length),
            "Content-Disposition": _content_disposition(metadata.original_filename),
        },
    )


__all__ = [
    "b66_template_source_detail",
    "b66_template_source_list",
    "b66_template_source_upload",
]
