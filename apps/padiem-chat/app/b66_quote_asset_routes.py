"""Authenticated read-only routes for private B66 quotation assets (#3402)."""

from __future__ import annotations

import inspect
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .b66_quote_assets import B66QuoteAssetError, validate_asset_id
from .claw_memory_routes import _resolve_memory_workspace

_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE,
    )


def _owner(request: Request) -> str | None:
    if not auth_ready(request):
        return None
    try:
        return current_user_id(request)
    except Exception:
        return None


async def b66_quote_asset_detail(request: Request) -> Response:
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")

    try:
        asset_id = validate_asset_id(request.path_params.get("asset_id", ""))
    except B66QuoteAssetError:
        return _error(400, "invalid_asset_id", "견적 자산 ID 형식이 올바르지 않습니다.")

    store: Any | None = getattr(request.app.state, "b66_quote_asset_store", None)
    get_fn = getattr(store, "get_for_owner", None) if store is not None else None
    if not callable(get_fn):
        return _error(503, "quote_asset_unavailable", "견적 자산을 사용할 수 없습니다.")

    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        value = get_fn(user_id=uid, workspace_id=workspace_id, asset_id=asset_id)
        result = await value if inspect.isawaitable(value) else value
    except B66QuoteAssetError:
        return _error(503, "quote_asset_read_failed", "견적 자산을 읽지 못했습니다.")
    except Exception:
        return _error(503, "quote_asset_read_failed", "견적 자산을 읽지 못했습니다.")

    if result is None:
        return _error(404, "quote_asset_not_found", "견적 자산을 찾을 수 없습니다.")

    metadata, body = result
    return Response(
        content=body,
        media_type=metadata.media_type,
        headers={
            **_NO_STORE,
            "Content-Length": str(metadata.byte_length),
        },
    )


__all__ = ["b66_quote_asset_detail"]
