"""PADIEM-owned GitHub App connection. No owner-selected scopes or token exposure."""
from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlencode
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from .auth import SESSION_COOKIE
from .auth_routes import auth_ready, current_user_id
from .github_oauth_provider import GITHUB_CLIENT_ID
from .same_origin_guard import expected_browser_origin

STATE_COOKIE = "padiem_claw_github_oauth_state"
CALLBACK_PATH = "/api/connectors/github/callback"
HEADERS = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}

def _error(code: str, status: int = 503) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status, headers=HEADERS)

def _ports(request: Request):
    state = request.app.state
    return getattr(state, "github_oauth_store", None), getattr(state, "github_oauth_provider", None)

async def _owner(request: Request) -> str | None:
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    if not uid or store is None:
        return None
    try:
        return uid if await store.get_user(uid) is not None else None
    except Exception:
        return None

def _callback(request: Request) -> str | None:
    origin = expected_browser_origin(request.app.state.settings)
    return origin.rstrip("/") + CALLBACK_PATH if isinstance(origin, str) and origin.startswith("https://") else None

def _clear(response: Response):
    response.delete_cookie(STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response

async def github_start(request: Request) -> Response:
    uid = await _owner(request)
    store, provider = _ports(request)
    callback = _callback(request)
    if not uid:
        return _error("authentication_required", 401)
    if not store or not provider or not callback or request.query_params:
        return _error("github_connector_unavailable")
    session = request.cookies.get(SESSION_COOKIE)
    if not session:
        return _error("authentication_required", 401)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    try:
        await store.begin(user_id=uid, session=session, state=state, verifier=verifier)
    except Exception:
        return _error("github_state_unavailable")
    params = {"client_id": GITHUB_CLIENT_ID, "redirect_uri": callback,
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    response = RedirectResponse("https://github.com/login/oauth/authorize?" + urlencode(params), status_code=303,
                                headers=HEADERS)
    response.set_cookie(STATE_COOKIE, state, max_age=600, path="/", secure=True,
                        httponly=True, samesite="lax")
    return response

async def github_callback(request: Request) -> Response:
    uid = await _owner(request)
    store, provider = _ports(request)
    callback = _callback(request)
    state, code, session = (request.query_params.get("state"), request.query_params.get("code"),
                            request.cookies.get(SESSION_COOKIE))
    cookie = request.cookies.get(STATE_COOKIE)
    if not uid or not session:
        return _clear(_error("authentication_required", 401))
    if not store or not provider or not callback:
        return _clear(_error("github_connector_unavailable"))
    if not (isinstance(state, str) and 16 <= len(state) <= 128 and cookie
            and hmac.compare_digest(cookie, state) and isinstance(code, str) and 1 <= len(code) <= 4096
            and len(request.query_params) == 2):
        return _clear(_error("github_oauth_state_invalid", 400))
    try:
        verifier = await store.consume(user_id=uid, session=session, state=state)
        if not verifier:
            return _clear(_error("github_oauth_state_invalid", 400))
        tokens = await provider.exchange(code=code, verifier=verifier, callback_url=callback)
        github_id, login = await provider.viewer(tokens["access_token"])
        installation_id = await provider.installation(tokens["access_token"])
        await store.save(user_id=uid, github_user_id=github_id, login=login,
                         installation_id=installation_id, **tokens)
    except Exception:
        return _clear(_error("github_oauth_exchange_failed"))
    return _clear(RedirectResponse("/?claw-github=connected", status_code=303, headers=HEADERS))

async def _credentials(request: Request):
    uid = await _owner(request)
    store, provider = _ports(request)
    if not uid:
        return None, None, None, "authentication_required"
    if not store or not provider:
        return uid, None, None, "github_connector_unavailable"
    try:
        status = await store.status(uid)
        if status is None:
            return uid, None, None, None
        tokens = await store.token_pair(uid)
        if not tokens:
            return uid, None, None, "github_credential_unavailable"
        if tokens["access_expires_at"] <= int(time.time()) + 60:
            fresh = await provider.refresh(refresh_token=tokens["refresh_token"])
            gh_id, login = await provider.viewer(fresh["access_token"])
            installation_id = await provider.installation(fresh["access_token"])
            if login != status["login"] or installation_id != status["installation_id"]:
                return uid, None, None, "github_identity_changed"
            await store.save(user_id=uid, github_user_id=gh_id, login=login,
                             installation_id=installation_id, **fresh)
            tokens = fresh
        actual_id = await provider.installation(tokens["access_token"])
        if actual_id != status["installation_id"]:
            return uid, None, None, "github_installation_changed"
        return uid, tokens["access_token"], status, None
    except Exception:
        return uid, None, None, "github_authority_unavailable"

async def github_status(request: Request):
    uid, token, state, err = await _credentials(request)
    if err == "authentication_required":
        return _error(err, 401)
    if err:
        return _error(err)
    if state is None:
        return JSONResponse({"ok": True, "state": "off"}, headers=HEADERS)
    return JSONResponse({"ok": True, "state": "on", "login": state["login"]}, headers=HEADERS)

async def github_repositories(request: Request):
    uid, token, state, err = await _credentials(request)
    if err:
        return _error(err, 401 if err == "authentication_required" else 503)
    if not state or not token:
        return _error("github_not_connected", 409)
    _, provider = _ports(request)
    try:
        repos = await provider.repositories(token, state["installation_id"])
    except Exception:
        return _error("github_repositories_unavailable")
    return JSONResponse({"ok": True, "repositories": repos}, headers=HEADERS)

async def github_disconnect(request: Request):
    if request.query_params or request.headers.get("content-length") not in (None, "", "0"):
        return _error("github_disconnect_payload_not_allowed", 400)
    if request.headers.get("transfer-encoding"):
        return _error("github_disconnect_payload_not_allowed", 400)
    origin = expected_browser_origin(request.app.state.settings)
    if not origin or request.headers.get("origin") != origin:
        return _error("github_disconnect_origin_rejected", 403)
    uid = await _owner(request)
    store, provider = _ports(request)
    if not uid:
        return _error("authentication_required", 401)
    if not store:
        return _error("github_connector_unavailable")
    try:
        await store.disconnect(uid)
    except Exception:
        return _error("github_disconnect_failed")
    # Local credential revocation is authoritative; user may separately revoke GitHub App access.
    return JSONResponse({"ok": True, "state": "off"}, headers=HEADERS)
