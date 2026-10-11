"""Public anonymous reader entry for Living Fiction.

Public visitors receive isolated reader sessions without requiring a pre-issued
invite credential. Editorial/admin authentication remains separate.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app import auth
from app import reader_repository as reader_repo
from app.config import settings
from app.web import READER_COOKIE, READER_PREAUTH_COOKIE, _verify_request_origin, get_db


def register_public_reader_entry(app: FastAPI) -> None:
    """Register public reader entry before legacy invite-only POST handling."""

    @app.post("/public-access")
    async def public_reader_access_post(
        request: Request,
        conn=Depends(get_db),
        csrf_token: str = Form(...),
    ):
        _verify_request_origin(request)

        cookie_value = request.cookies.get(READER_PREAUTH_COOKIE)
        if not auth.verify_preauth_csrf(
            settings.session_hmac_key,
            auth.CSRF_READER_PREAUTH,
            cookie_value,
            csrf_token,
        ):
            raise HTTPException(status_code=403, detail="CSRF verification failed")

        reader = reader_repo.create_reader(conn, display_name="공개 독자")
        token = auth.create_reader_session(conn, reader.id, settings.session_hmac_key)

        response = RedirectResponse(url="/read", status_code=status.HTTP_303_SEE_OTHER)
        auth.set_reader_cookie(response, token, settings.is_production)
        auth.clear_preauth_cookie(
            response, READER_PREAUTH_COOKIE, auth.READER_PREAUTH_COOKIE_PATH
        )
        return response
