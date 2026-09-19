from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

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
from .history import HistoryConflict, HistoryStore
from .password_auth import (
    PasswordAuthError,
    hash_password,
    normalize_display_name,
    normalize_email,
    normalize_username,
    verify_password,
    validate_password,
)


def auth_ready(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    return settings.auth_mode != "off" and request.app.state.history_store is not None


def google_auth_ready(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    return (
        settings.auth_mode in {"google", "hybrid"}
        and request.app.state.history_store is not None
    )


def password_auth_ready(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    store = request.app.state.history_store
    return (
        settings.auth_mode in {"password", "hybrid"}
        and store is not None
        and callable(getattr(store, "register_password_user", None))
        and callable(getattr(store, "find_password_credential", None))
        and callable(getattr(store, "record_password_failure", None))
        and callable(getattr(store, "reset_password_failures", None))
    )


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
        payload["methods"] = {
            "google": google_auth_ready(request),
            "password": password_auth_ready(request),
        }
    if ready and getattr(request.app.state, "project_file_store", None) is not None:
        payload["project_files_ready"] = True
    return JSONResponse(payload)


async def google_start(request: Request) -> Response:
    if not google_auth_ready(request):
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
    provider: str,
    provider_subject: str,
    authenticated_at: datetime,
    expires_at: datetime,
    ensure_personal_tenant: bool = False,
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
                provider=provider,
                provider_subject=provider_subject,
                authenticated_at=authenticated_at,
                expires_at=expires_at,
            ),
            now=authenticated_at,
            ensure_personal_tenant=ensure_personal_tenant,
        )
        await shadow_store.save_projection(bridged)
    except Exception:
        # Shadow/parity collection is intentionally not the compatibility login
        # authority. Shared-authority consumers independently fail closed if the
        # projection/current canonical session cannot later be resolved.
        return


async def google_callback(request: Request) -> Response:
    if not google_auth_ready(request):
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
        provider="google",
        provider_subject=identity["subject"],
        authenticated_at=authenticated_at,
        expires_at=expires_at,
    )

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(SESSION_COOKIE, session, **session_cookie_kwargs(settings))
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


_PASSWORD_BODY_LIMIT = 16 * 1024
_PASSWORD_FAILURE_LIMIT = 5
_PASSWORD_LOCK_MINUTES = 15


def _auth_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
    )


async def _json_body(request: Request) -> dict | None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None
    raw = await request.body()
    if not raw or len(raw) > _PASSWORD_BODY_LIMIT:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_locked_until(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _session_response(settings: Settings, profile) -> JSONResponse:
    session = create_session_token(settings, profile.id)
    response = JSONResponse({"ok": True, "user": profile.public_dict()})
    response.set_cookie(SESSION_COOKIE, session, **session_cookie_kwargs(settings))
    return response


async def password_register(request: Request) -> JSONResponse:
    if not password_auth_ready(request):
        return _unavailable()
    data = await _json_body(request)
    if data is None:
        return _auth_error(400, "invalid_request", "회원가입 정보를 확인해 주세요.")

    try:
        username = normalize_username(data.get("username"))
        email = normalize_email(data.get("email"))
        display_name = normalize_display_name(data.get("name"), fallback=username)
        password = validate_password(data.get("password"), username=username)
        encoded = hash_password(password)
    except PasswordAuthError as exc:
        return _auth_error(400, exc.code, exc.message)

    store: HistoryStore = request.app.state.history_store
    try:
        profile = await store.register_password_user(
            username,
            email,
            display_name,
            encoded,
        )
    except HistoryConflict:
        return _auth_error(
            409,
            "account_exists",
            "이미 사용 중인 아이디 또는 이메일입니다.",
        )
    except Exception:
        return _auth_error(
            503,
            "auth_storage_error",
            "회원가입 정보를 저장하지 못했습니다.",
        )

    settings: Settings = request.app.state.settings
    authenticated_epoch = int(datetime.now(timezone.utc).timestamp())
    authenticated_at = datetime.fromtimestamp(authenticated_epoch, tz=timezone.utc)
    expires_at = authenticated_at + timedelta(seconds=settings.session_max_age_seconds)
    await _write_identity_shadow_after_login(
        request,
        product_user_id=profile.id,
        provider="password",
        provider_subject=username,
        authenticated_at=authenticated_at,
        expires_at=expires_at,
        ensure_personal_tenant=True,
    )
    return _session_response(settings, profile)


async def password_login(request: Request) -> JSONResponse:
    if not password_auth_ready(request):
        return _unavailable()
    data = await _json_body(request)
    if data is None:
        return _auth_error(400, "invalid_request", "로그인 정보를 확인해 주세요.")

    identifier_raw = data.get("identifier")
    password = data.get("password")
    try:
        if not isinstance(identifier_raw, str):
            raise PasswordAuthError("invalid_credentials", "invalid")
        identifier = (
            normalize_email(identifier_raw)
            if "@" in identifier_raw
            else normalize_username(identifier_raw)
        )
    except PasswordAuthError:
        identifier = ""
    if not isinstance(password, str) or len(password) > 128:
        password = ""

    store: HistoryStore = request.app.state.history_store
    try:
        credential = await store.find_password_credential(identifier) if identifier else None
    except Exception:
        return _auth_error(503, "auth_storage_error", "로그인 정보를 확인하지 못했습니다.")

    # Always execute the verifier, including for a missing identifier.
    password_ok = verify_password(password, credential.password_hash if credential else None)
    now = datetime.now(timezone.utc)

    if credential is not None:
        locked_until = _parse_locked_until(credential.locked_until)
        if locked_until is not None and now < locked_until:
            return _auth_error(
                429,
                "auth_locked",
                "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            )

    if credential is None or not password_ok:
        if credential is not None:
            failures = min(100, credential.failed_attempts + 1)
            lock_until = None
            if failures >= _PASSWORD_FAILURE_LIMIT:
                lock_until = (now + timedelta(minutes=_PASSWORD_LOCK_MINUTES)).isoformat()
            try:
                await store.record_password_failure(
                    credential.user.id,
                    failures,
                    lock_until,
                )
            except Exception:
                pass
        return _auth_error(
            401,
            "invalid_credentials",
            "아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    try:
        await store.reset_password_failures(credential.user.id)
    except Exception:
        return _auth_error(503, "auth_storage_error", "로그인 정보를 갱신하지 못했습니다.")

    settings: Settings = request.app.state.settings
    authenticated_epoch = int(now.timestamp())
    authenticated_at = datetime.fromtimestamp(authenticated_epoch, tz=timezone.utc)
    expires_at = authenticated_at + timedelta(seconds=settings.session_max_age_seconds)
    await _write_identity_shadow_after_login(
        request,
        product_user_id=credential.user.id,
        provider="password",
        provider_subject=credential.username,
        authenticated_at=authenticated_at,
        expires_at=expires_at,
        ensure_personal_tenant=True,
    )
    return _session_response(settings, credential.user)


async def logout(request: Request) -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response
