from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .auth import (
    AuthError,
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    GoogleOAuthClient,
    create_oauth_state,
    create_session_token,
    decode_session_token,
    oauth_state_cookie_kwargs,
    session_cookie_kwargs,
    verify_oauth_state,
)
from .config import Settings
from .control_plane_identity import TrustedProductAuthEvidence, bridge_trusted_product_auth
from .history import HistoryStore


def auth_ready(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    return settings.auth_mode == "google" and request.app.state.history_store is not None


def current_user_id(request: Request) -> str | None:
    settings: Settings = request.app.state.settings
    return decode_session_token(settings, request.cookies.get(SESSION_COOKIE))


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "auth_unavailable", "message": "로그인을 현재 사용할 수 없습니다."}},
        status_code=503,
    )


async def auth_status(request: Request) -> JSONResponse:
    ready = auth_ready(request)
    store: HistoryStore | None = request.app.state.history_store
    session_cookie_present = bool(request.cookies.get(SESSION_COOKIE))
    user = None
    authenticated = False
    session_state = "guest"
    if ready and store is not None:
        uid = current_user_id(request)
        if uid:
            try:
                profile = await store.get_user(uid)
            except Exception:
                # Presentation-only projection: a transient profile lookup failure
                # must not be reclassified as a valid guest or signed-in state.
                profile = None
                session_state = "unavailable"
            else:
                if profile is not None:
                    authenticated = True
                    user = profile.public_dict()
                    session_state = "signed_in"
                elif session_cookie_present:
                    session_state = "expired"
        elif session_cookie_present:
            # A browser carrying a compatibility session cookie that no longer
            # resolves may recover by signing in again. This state is never used
            # as access authority; it is only projected for truthful B62 UX.
            session_state = "expired"
    payload = {
        "ready": ready,
        "authenticated": authenticated,
        "history_ready": ready and store is not None,
        "user": user,
    }
    # Keep the legacy unavailable payload stable. Once auth is actually ready,
    # expose a bounded presentation state so the browser does not infer expiry.
    if ready:
        payload["session_state"] = session_state
    if ready and getattr(request.app.state, "project_file_store", None) is not None:
        payload["project_files_ready"] = True
    return JSONResponse(payload)


async def google_start(request: Request) -> Response:
    if not auth_ready(request):
        return _unavailable()
    settings: Settings = request.app.state.settings
    oauth: GoogleOAuthClient = request.app.state.google_oauth
    try:
        state, signed = create_oauth_state(settings)
        location = oauth.authorization_url(state)
    except AuthError as exc:
        return JSONResponse({"error": {"code": exc.code, "message": exc.user_message}}, status_code=exc.status_code)
    response = RedirectResponse(location, status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE, signed, **oauth_state_cookie_kwargs())
    return response


async def _write_identity_shadow_after_login(
    request: Request,
    *,
    product_user_id: str,
    provider_subject: str,
    authenticated_at: datetime,
    expires_at: datetime,
) -> None:
    """Best-effort shadow write; never turns migration telemetry into login authority.

    The canonical values still come only from the injected trusted Control Plane
    authority. Failure here means the later shared-authority path has no usable
    shadow and therefore fails closed; the existing B62 Google login remains
    available during the migration/shadow phase.
    """

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    if authority is None or shadow_store is None:
        return
    try:
        bridged = await bridge_trusted_product_auth(
            authority,
            TrustedProductAuthEvidence(
                product_user_id=product_user_id,
                provider="google",
                provider_subject=provider_subject,
                authenticated_at=authenticated_at,
                expires_at=expires_at,
            ),
            now=authenticated_at,
        )
        await shadow_store.save_projection(bridged)
    except Exception:
        # Shadow/parity collection is intentionally not the compatibility login
        # authority. Shared-authority consumers independently fail closed if the
        # projection/current canonical session cannot later be resolved.
        return


async def google_callback(request: Request) -> Response:
    if not auth_ready(request):
        return _unavailable()
    settings: Settings = request.app.state.settings
    query_state = request.query_params.get("state")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not verify_oauth_state(settings, query_state, cookie_state):
        return JSONResponse(
            {"error": {"code": "invalid_oauth_state", "message": "로그인 요청을 확인할 수 없습니다. 다시 로그인해 주세요."}},
            status_code=400,
        )
    code = request.query_params.get("code")
    if not isinstance(code, str) or not code.strip() or len(code) > 4096:
        return JSONResponse(
            {"error": {"code": "invalid_oauth_callback", "message": "Google 로그인 결과를 확인할 수 없습니다."}},
            status_code=400,
        )
    oauth: GoogleOAuthClient = request.app.state.google_oauth
    store: HistoryStore = request.app.state.history_store
    try:
        access_token = await oauth.exchange_code(code.strip())
        identity = await oauth.fetch_userinfo(access_token)
        profile = await store.upsert_google_user(
            identity["subject"], identity["email"], identity["name"], identity["picture"]
        )
        authenticated_epoch = int(datetime.now(timezone.utc).timestamp())
        authenticated_at = datetime.fromtimestamp(authenticated_epoch, tz=timezone.utc)
        expires_at = authenticated_at + timedelta(seconds=settings.session_max_age_seconds)
        session = create_session_token(settings, profile.id, now=authenticated_epoch)
    except AuthError as exc:
        return JSONResponse({"error": {"code": exc.code, "message": exc.user_message}}, status_code=exc.status_code)
    except Exception:
        return JSONResponse(
            {"error": {"code": "auth_storage_error", "message": "로그인 정보를 저장하지 못했습니다. 다시 시도해 주세요."}},
            status_code=503,
        )

    await _write_identity_shadow_after_login(
        request,
        product_user_id=profile.id,
        provider_subject=identity["subject"],
        authenticated_at=authenticated_at,
        expires_at=expires_at,
    )

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(SESSION_COOKIE, session, **session_cookie_kwargs(settings))
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


async def logout(request: Request) -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response
