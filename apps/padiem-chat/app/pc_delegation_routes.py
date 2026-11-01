"""Settings API and server-owned execution snapshot for PC delegation."""
from __future__ import annotations

import json

from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .pc_delegation_store import PcDelegationStoreError, validate_stored_pc_delegation


PC_DELEGATION_PATH = "/api/account/pc-delegations"
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=_NO_STORE)


def _unavailable():
    return _error(503, "pc_delegation_unavailable", "PC 작업 설정을 지금 불러오거나 저장하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")


async def load_pc_delegation(request, owner_id: str) -> dict:
    """Load for a caller-verified owner, never from a browser/model payload.

    Internal callers supply the authenticated product owner they already used
    to authorize the PC run. No settings/migration/store is 'unknown', not an
    empty delegation: the common guard then asks before changing a file.
    """
    store = getattr(request.app.state, "pc_delegation_store", None)
    if store is not None:
        try:
            stored = await store.load(owner_id)
            if not isinstance(stored, dict) or set(stored) - {"version", "rules", "updated_at"}:
                raise PcDelegationStoreError("Stored delegation snapshot is invalid")
            return validate_stored_pc_delegation({"version": stored["version"], "rules": stored["rules"]})
        except Exception:
            pass
    return {"version": 1, "available": False, "rules": []}


async def pc_delegation_get(request):
    owner_id = current_user_id(request)
    if not owner_id:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    store = getattr(request.app.state, "pc_delegation_store", None)
    if store is None:
        return _unavailable()
    try:
        settings = await store.load(owner_id)
    except Exception:
        return _unavailable()
    return JSONResponse({"ok": True, **settings}, headers=_NO_STORE)


async def pc_delegation_put(request):
    owner_id = current_user_id(request)
    if not owner_id:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    try:
        settings = validate_stored_pc_delegation(json.loads((await request.body()).decode("utf-8")))
    except (ValueError, UnicodeDecodeError, PcDelegationStoreError):
        return _error(422, "invalid_pc_delegation", "폴더, PC와 작업 종류를 확인해 주세요. 메일·메시지 발송과 외부 기록은 맡길 수 없습니다.")
    store = getattr(request.app.state, "pc_delegation_store", None)
    if store is None:
        return _unavailable()
    try:
        saved = await store.save(owner_id, settings)
    except Exception:
        return _unavailable()
    return JSONResponse({"ok": True, **saved}, headers=_NO_STORE)
