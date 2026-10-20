"""#5222 account-scoped last selected AI tier.

One signed-in account, one stored tier. The browser never names the account:
the row is always keyed by the canonical product user id that the existing
signed session already resolved, so an account switch can neither inherit nor
forge another account's selection.

The stored value is a **preference**, not authority. Reading it re-verifies the
member grade and the administrator gate on the server, and writing it re-runs
the same existing central gates (``selected_grade_denial`` /
``selected_admin_denial``) that already guard every model request. A stored
tier that the account may no longer use is reported as unavailable and is
never handed back as an executable tier.
"""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .account_model_selection_store import SELECTABLE_TIERS
from .auth_routes import current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .member_grade_access import (
    GRADES,
    selected_admin_denial,
    selected_grade_denial,
    verified_member_grade,
)

MODEL_SELECTION_PATH = "/api/account/model-selection"

_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
_BODY_LIMIT = 256


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE,
    )


def _unauthorized() -> JSONResponse:
    return _error(401, "unauthorized", "로그인이 필요합니다.")


def _unavailable() -> JSONResponse:
    return _error(503, "model_selection_unavailable", "AI 등급 저장을 현재 사용할 수 없습니다.")


async def allowed_tiers(request: Request, user_id: str) -> list[str]:
    """The tiers this account may use right now, from the server-side grade."""
    grade = await verified_member_grade(request, user_id)
    index = GRADES.index(grade) if grade in GRADES else 0
    return list(GRADES[: index + 1])


async def admin_state(request: Request, user_id: str) -> bool | None:
    """``True`` verified administrator, ``False`` verified not one, ``None`` unknown.

    The existing central administrator gate answers all three cases and is the
    only authority used here. A temporarily unavailable authority is reported
    as unknown so the browser can keep the stored preference without ever
    presenting the administrator lane as executable.
    """
    denial = await selected_admin_denial(request, user_id)
    if denial is None:
        return True
    if getattr(denial, "status_code", None) == 403:
        return False
    return None


def _selection_payload(
    selection: dict[str, str] | None,
    tiers: list[str],
    admin: bool | None,
) -> dict[str, object]:
    stored_tier = selection["tier"] if selection else None
    restorable = None
    if stored_tier in tiers:
        restorable = stored_tier
    elif stored_tier == "admin" and admin is True:
        restorable = "admin"
    return {
        "ok": True,
        "selection": selection,
        "stored_tier": stored_tier,
        "restorable_tier": restorable,
        "allowed_tiers": tiers,
        "admin_available": admin,
    }


async def account_model_selection_get(request: Request) -> JSONResponse:
    user_id = current_user_id(request)
    if not user_id:
        return _unauthorized()
    store = getattr(request.app.state, "account_model_selection_store", None)
    if store is None:
        return _unavailable()
    try:
        selection = await store.load(user_id)
    except Exception:
        return _unavailable()
    try:
        tiers = await allowed_tiers(request, user_id)
        admin = await admin_state(request, user_id)
    except Exception:
        return _unavailable()
    return JSONResponse(_selection_payload(selection, tiers, admin), headers=_NO_STORE)


async def account_model_selection_put(request: Request) -> JSONResponse:
    user_id = current_user_id(request)
    if not user_id:
        return _unauthorized()
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")
    try:
        body = await read_bounded_request_body(request, max_bytes=_BODY_LIMIT)
    except RequestBodyTooLarge:
        return _error(413, "model_selection_request_too_large", "요청이 너무 큽니다.")
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _error(400, "invalid_json", "요청 형식이 올바르지 않습니다.")
    if not isinstance(data, dict) or set(data) != {"tier"}:
        return _error(400, "invalid_model_selection_shape", "AI 등급 요청 형식이 올바르지 않습니다.")
    tier = data["tier"]
    if not isinstance(tier, str) or tier.lower() not in SELECTABLE_TIERS:
        return _error(422, "invalid_tier", "지원하지 않는 AI 등급입니다.")
    tier = tier.lower()
    # The same existing central gates that guard a model request guard the
    # stored preference: a tier the account may not use is never stored.
    if tier == "admin":
        denial = await selected_admin_denial(request, user_id)
    else:
        denial = await selected_grade_denial(request, user_id, tier)
    if denial is not None:
        return denial
    store = getattr(request.app.state, "account_model_selection_store", None)
    if store is None:
        return _unavailable()
    try:
        selection = await store.save(user_id, tier)
    except Exception:
        return _unavailable()
    try:
        tiers = await allowed_tiers(request, user_id)
        admin = await admin_state(request, user_id)
    except Exception:
        tiers = [tier]
        admin = None
    return JSONResponse(_selection_payload(selection, tiers, admin), headers=_NO_STORE)
