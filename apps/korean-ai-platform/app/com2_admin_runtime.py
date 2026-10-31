"""Loopback-only B14 management app with token login and per-session CSRF."""
from __future__ import annotations

import hmac
import os
import secrets
import stat
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

COOKIE = "b14_admin_session"
SESSION_TTL = 8 * 60 * 60


def _read_admin_token() -> bytes:
    directory = os.environ.get("B14_SECRET_DIR", "").strip()
    path = os.environ.get("B14_ADMIN_TOKEN_FILE", "").strip()
    if not path:
        if not directory:
            raise RuntimeError("B14 admin token path is not configured")
        path = str(Path(directory).parent / "admin-token")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("not a regular file")
            if os.name == "posix" and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid()):
                raise ValueError("incorrect file ownership or mode")
            token = f.read(1026).strip()
            if not (32 <= len(token) <= 1024):
                raise ValueError("invalid token length")
            return token
    except (OSError, ValueError) as exc:
        raise RuntimeError("B14 admin token file unavailable or unsafe") from exc


def create_admin_app() -> Starlette:
    from app.env_bootstrap import load_env_file
    from app.factory import _build_jinja_env, _STATIC_DIR
    from app.local_runtime import LocalRequestScopeMiddleware
    from app.pilot.com2_admin import routes as admin_routes

    load_env_file()
    token = _read_admin_token()
    sessions: dict[str, tuple[str, float]] = {}

    async def login_page(request: Request):
        return HTMLResponse(
            '<!doctype html><html lang="ko"><meta charset="utf-8"><title>관리 로그인</title>'
            '<h1>B14 관리 로그인</h1><form method="post" action="/login">'
            '<label for="token">관리 토큰</label><input type="password" id="token" '
            'name="token" required autocomplete="off"><button>로그인</button></form></html>',
            headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
        )

    async def login(request: Request):
        origin = request.headers.get("origin")
        if origin and origin not in ("http://127.0.0.1:8781", "http://localhost:8781"):
            return PlainTextResponse("Forbidden", status_code=403)
        form = await request.form()
        candidate = str(form.get("token", "")).encode("utf-8")
        if len(candidate) > 1024 or not hmac.compare_digest(candidate, token):
            return PlainTextResponse("Unauthorized", status_code=401, headers={"Cache-Control": "no-store"})
        now = time.monotonic()
        for key, (_, expires) in list(sessions.items()):
            if expires <= now:
                sessions.pop(key, None)
        if len(sessions) >= 64:
            sessions.pop(next(iter(sessions)))
        session = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        sessions[session] = (csrf, now + SESSION_TTL)
        response = RedirectResponse("/com2/admin/secrets", status_code=303)
        response.set_cookie(COOKIE, session, httponly=True, samesite="strict", max_age=SESSION_TTL, path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    def guarded(endpoint):
        async def run(request: Request):
            session_id = request.cookies.get(COOKIE, "")
            record = sessions.get(session_id)
            if not record or record[1] <= time.monotonic():
                sessions.pop(session_id, None)
                return PlainTextResponse("Unauthorized", status_code=401, headers={"Cache-Control": "no-store"})
            request.state.csrf_token = record[0]
            if request.method == "POST":
                form = await request.form()
                supplied = str(form.get("csrf_token", ""))
                if not hmac.compare_digest(supplied.encode("utf-8"), record[0].encode("ascii")):
                    return PlainTextResponse("Forbidden", status_code=403, headers={"Cache-Control": "no-store"})
            response = await endpoint(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
            return response
        return run

    protected = [Route(route.path, guarded(route.endpoint), methods=list(route.methods)) for route in admin_routes]
    app = Starlette(routes=[Route("/login", login_page, methods=["GET"]), Route("/login", login, methods=["POST"])] + protected)
    app.state.jinja_env = _build_jinja_env()
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.add_middleware(LocalRequestScopeMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    return app
