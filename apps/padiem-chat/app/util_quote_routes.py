"""#7173 PR4: the Util app's signed-in quote-draft preview.

The Util 탭's 견적서 초안 screen obeys the same signed-in rule as the other
Util tools. The draft projection itself is the existing deterministic
manual-intake preview (``claw_routes.claw_manual_intake_preview``): this
wrapper adds only the session check and delegates the request unchanged. It
never reaches the execute lane, a model/provider, a usage bucket or a stored
artifact, so it grants no execution authority.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .claw_routes import claw_manual_intake_preview

UTIL_QUOTE_PREVIEW_PATH = "/api/util/quote/preview"


async def util_quote_preview(request: Request) -> JSONResponse:
    if not auth_ready(request) or current_user_id(request) is None:
        return JSONResponse(
            {"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}},
            status_code=401,
        )
    return await claw_manual_intake_preview(request)
