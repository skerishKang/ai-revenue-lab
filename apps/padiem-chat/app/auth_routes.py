from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from padiem_control_plane.b54_identity_bridge import B54BridgedIdentitySession

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
from .b54_canonical_session import (
    B54ServerAuthenticatedOwner,
    b54_canonical_session_producer,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .config import Settings
from .control_plane_identity import TrustedProductAuthEvidence, bridge_trusted_product_auth
from .history import HistoryConflict, HistoryStore, PasswordCredential
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


def _bridge_origin(request: Request) -> str | None:
    """Read the B66 bridge origin header; tolerate headerless test doubles."""

    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    return headers.get("x-b66-origin")


async def google_start(request: Request) -> Response:
    if not google_auth_ready(request):
        return _unavailable()
    settings: Settings = request.app.state.settings
    oauth: GoogleOAuthClient = request.app.state.google_oauth
    bridge_origin = _bridge_origin(request)
    try:
        state, signed = create_oauth_state(settings)
        location = oauth.authorization_url(state, bridge_origin=bridge_origin)
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


async def establish_b54_canonical_session_after_login(
    request: Request, credential: PasswordCredential
) -> B54BridgedIdentitySession | None:
    """Establish the canonical B54 session behind a verified password login.

    This is the production callsite of the B54 canonical-session chain.  Its only
    input is the credential row the server read to authenticate the login, so no
    request content can name a user, provider subject, tenant, product, or session.

    The result is the canonical B54 authority a B54-scoped operation resolves its
    Engine session from; it is returned to server code, never projected to the
    browser.  It is attempted only when the private Control Plane identity binding
    is actually present, and a B54 failure never turns a completed B62 password
    login into an error: B54 is a separate product scope that independently fails
    closed for any consumer that requires it.
    """

    if getattr(request.app.state, "control_plane_identity_authority", None) is None:
        return None
    producer = b54_canonical_session_producer(
        app_state=request.app.state,
        session_max_age_seconds=request.app.state.settings.session_max_age_seconds,
    )
    try:
        return await producer.establish(
            B54ServerAuthenticatedOwner.from_password_credential(credential)
        )
    except Exception:
        return None


async def establish_b54_canonical_session_after_google_login(
    request: Request, profile_id: str, google_identity: Mapping[str, str]
) -> B54BridgedIdentitySession | None:
    """Establish the canonical B54 session behind a verified Google login (#3240).

    Called only after the whole server-side Google chain has already succeeded:
    OAuth state verified, code exchanged, userinfo fetched with
    ``verified_email is true``, and the server UserProfile upserted. The
    ``profile_id`` is that server row's id and ``google_identity`` is the
    already-verified userinfo result — the raw access token is not passed here and
    never reaches the B54 bridge.

    No request content names a user, provider, provider subject, tenant, product
    or session, so a forged query/body field cannot influence the canonical
    session.

    Like the password path, this is additive: it is attempted only when the
    private Control Plane identity binding is present, and a B54 failure never
    turns a completed B62 Google login into an error.
    """

    if getattr(request.app.state, "control_plane_identity_authority", None) is None:
        return None
    producer = b54_canonical_session_producer(
        app_state=request.app.state,
        session_max_age_seconds=request.app.state.settings.session_max_age_seconds,
    )
    try:
        owner = B54ServerAuthenticatedOwner.from_verified_google_identity(
            product_user_id=profile_id,
            google_identity=google_identity,
        )
    except Exception:
        return None
    try:
        return await producer.establish(owner)
    except Exception:
        return None


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
    bridge_origin = _bridge_origin(request)
    try:
        access_token = await oauth.exchange_code(code.strip(), bridge_origin=bridge_origin)
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

    # #3240: the B62 Google login above is already complete and unchanged. The
    # canonical B54 session is additive and best-effort — a B54 failure returns
    # None here and any B54-scoped operation fails closed on its own later.
    await establish_b54_canonical_session_after_google_login(
        request, profile.id, identity
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
    try:
        raw = await read_bounded_request_body(request, max_bytes=_PASSWORD_BODY_LIMIT)
    except RequestBodyTooLarge:
        return None
    if not raw:
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


def _is_locked(credential: PasswordCredential, now: datetime) -> bool:
    locked_until = _parse_locked_until(credential.locked_until)
    return locked_until is not None and now < locked_until


def _has_expired_lock(credential: PasswordCredential, now: datetime) -> bool:
    """Whether a recorded lock has already lapsed.

    A lapsed lock restarts the failure count instead of letting one new
    failure ratchet the account straight back into another lock window.
    """
    if not credential.locked_until:
        return False
    return _parse_locked_until(credential.locked_until) is not None and not _is_locked(credential, now)


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

    # #3501/#3508: lock state is server-owned and never disclosed. A
    # missing identifier, wrong password, prior failures, an active lock, and
    # an abuse-throttled attempt all reach the same public 401 projection.
    locked = credential is not None and _is_locked(credential, now)

    if credential is None or not password_ok or locked:
        # The dedicated abuse gate is NOT an authentication authority. Its only
        # power is to suppress mutation of account-level failure/lock state.
        # Missing/failed gate state therefore fails closed against remote
        # lockout amplification without blocking a later verified login.
        allow_failure_accounting = False
        gate = getattr(request.app.state, "auth_abuse_gate", None)
        if gate is not None:
            try:
                decision = await gate.authorize_failure_accounting(
                    identifier=identifier,
                    raw_ip=request.headers.get("cf-connecting-ip"),
                )
                allow_failure_accounting = bool(
                    getattr(decision, "allow_failure_accounting", False)
                )
            except Exception:
                allow_failure_accounting = False

        if credential is not None and not locked and allow_failure_accounting:
            # A lapsed lock starts a fresh failure sequence. Once the dedicated
            # identifier abuse bucket is exhausted, subsequent failed attempts
            # cannot create another lock until the bounded abuse window resets.
            if _has_expired_lock(credential, now):
                failures, lock_until = 1, None
            else:
                failures = min(100, credential.failed_attempts + 1)
                lock_until = None
                if failures >= _PASSWORD_FAILURE_LIMIT:
                    lock_until = (
                        now + timedelta(minutes=_PASSWORD_LOCK_MINUTES)
                    ).isoformat()
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
    # Establishing the session is the product outcome: it lands in the single
    # canonical Control Plane session store for the B54 product scope, where a
    # B54-scoped consumer resolves it. #2963 Step 3 is that consumer and remains a
    # separately authorized gate, so nothing here projects it to the browser.
    await establish_b54_canonical_session_after_login(request, credential)
    return _session_response(settings, credential.user)


async def logout(request: Request) -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response
