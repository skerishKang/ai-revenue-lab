from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from padiem_control_plane.b54_identity_bridge import B54BridgedIdentitySession

from .android_auth_routes import (
    android_handoff_confirm_page,
    android_handoff_terminal_page,
    bind_android_handoff_user,
    load_android_handoff_for_callback,
)
from .android_auth_store import HANDOFF_STATUS_AWAITING_CONFIRMATION
from .auth import (
    AuthError,
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    GoogleOAuthClient,
    create_oauth_state,
    create_session_token,
    decode_session_claims,
    decode_session_token,
    oauth_state_cookie_kwargs,
    session_cookie_kwargs,
    verify_oauth_state,
)
from .auth_abuse import UNAVAILABLE_WINDOW, AuthAbuseWindow
from .b66_signup_notifications import deliver_after_signup
from .b54_canonical_session import (
    B54ServerAuthenticatedOwner,
    b54_canonical_session_producer,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .config import Settings
from .control_plane_identity import (
    PADIEM_CHAT_PRODUCT_ID,
    TrustedProductAuthEvidence,
    bridge_trusted_product_auth,
)
from .history import HistoryConflict, HistoryStore, PasswordCredential
from .password_auth import (
    PasswordAuthError,
    hash_password_async,
    normalize_display_name,
    normalize_email,
    normalize_login_identifier,
    normalize_username,
    verify_password_async,
    validate_password,
)
from .password_reset import (
    RESET_DELIVERY_UNAVAILABLE,
    RESET_INVALID_REQUEST,
    RESET_TOKEN_INVALID,
    RESET_UNAVAILABLE,
    PasswordResetError,
    PasswordResetService,
    PasswordResetToken,
)
from .session_revocation_guard import session_verdict


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
        and callable(getattr(store, "find_password_credential_by_user_id", None))
        and callable(getattr(store, "update_password_credential", None))
        and callable(getattr(store, "record_password_failure", None))
        and callable(getattr(store, "reset_password_failures", None))
    )


def current_user_id(request: Request) -> str | None:
    """Resolve the signed-in product user for this request.

    #5225: when the canonical session guard resolved a verdict for this
    request, that verdict is the authority. A revoked, unknown or unbound
    canonical session never yields a user id, so every protected Chat/Claw API
    refuses a stored session cookie right after the logout that revoked it.
    Without a verdict — a deployment without the canonical identity authority,
    or a directly invoked route handler — the pre-existing cookie-only
    behaviour is unchanged.
    """

    verdict = session_verdict(request)
    if verdict is not None and not verdict.authenticated:
        return None
    settings: Settings = request.app.state.settings
    return decode_session_token(settings, request.cookies.get(SESSION_COOKIE))


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "auth_unavailable", "message": "로그인을 현재 사용할 수 없습니다."}},
        status_code=503,
    )


def _password_reset_service(request: Request) -> PasswordResetService | None:
    """The configured lost-password reset service, or ``None``."""

    service = getattr(request.app.state, "password_reset_service", None)
    return service if isinstance(service, PasswordResetService) else None


def _password_reset_delivery(request: Request):
    """The configured reset-mail transport, or ``None`` when unconfigured."""

    delivery = getattr(request.app.state, "password_reset_delivery", None)
    if delivery is None or not callable(getattr(delivery, "send", None)):
        return None
    return delivery


async def _revoke_all_canonical_sessions(
    request: Request, *, user_id: str, strict: bool
) -> str | None:
    """End every canonical session of one account (#5441).

    A replaced credential has to end every session it could still
    authenticate, on every device. The canonical Control Plane session store is
    the only revocation authority, so the revocation happens there instead of
    in a second, product-local session registry.

    ``strict`` decides what an authority without the reviewed capability means:

    * ``True`` (the lost-password reset) — the revocation cannot be confirmed,
      so the credential must not move. The caller reports the failure and the
      member retries with the same link.
    * ``False`` (the #5434 signed-in change) — the capability is simply not
      deployed yet, so the already-reviewed single-session revocation stays in
      force and the route keeps working.

    Returns ``None`` when the sessions are ended (or when there was nothing to
    end), and a stable error code otherwise.
    """

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if authority is None:
        # No canonical authority bound: this deployment has no canonical
        # sessions, so there is nothing to revoke.
        return None
    revoke_all = getattr(authority, "revoke_all_auth_sessions", None)
    if not callable(revoke_all):
        return "session_revocation_unavailable" if strict else None
    try:
        await revoke_all(
            product_id=PADIEM_CHAT_PRODUCT_ID,
            product_user_id=user_id,
        )
    except Exception as exc:
        code = getattr(exc, "code", "")
        if code in {
            "canonical_product_identity_link_not_found",
            "canonical_product_identity_link_not_active",
        }:
            # The account has no canonical subject link, so it owns no
            # canonical session. There is nothing to end.
            return None
        return "session_revocation_failed"
    return None


async def _account_method(store: HistoryStore | None, user_id: str) -> str:
    """The signed-in account's own authentication method.

    #5434: the account settings offer the password change only for an
    account that actually owns a password credential. The fact comes from the
    server's own credential row, never from the browser, and a failed lookup
    stays "unknown" so the UI never offers a change it cannot prove.
    """
    lookup = (
        getattr(store, "find_password_credential_by_user_id", None)
        if store is not None
        else None
    )
    if not callable(lookup):
        return "unknown"
    try:
        credential = await lookup(user_id)
    except Exception:
        return "unknown"
    if credential is None:
        return "google"
    return "password"


async def auth_status(request: Request) -> JSONResponse:
    from .member_grade_access import verified_member_grade
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
    # Owner decision 2026-10-24 (#5474): a guest may use Free on the Chat lane,
    # bounded by the usage gate; paid tiers, Claw, Custom and projects still
    # need a session. This flag is the server-authoritative condition the
    # browser may act on, and an isolated mock app (the CI browser QA target)
    # never advertises it, so no browser lane silently changes Production.
    payload["model_requires_session"] = bool(
        ready and request.app.state.settings.runtime_mode != "mock"
    )
    if authenticated:
        payload["member_grade"] = await verified_member_grade(request, uid)
        payload["account_method"] = await _account_method(store, uid)
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
) -> str | None:
    """Establish the canonical B62 session behind a verified login and shadow it.

    The canonical Control Plane identity authority is the single session
    authority for PADIEM, and this is the production callsite that binds one
    verified login to exactly one canonical session. #5225 reuses that session:
    the logout revokes it, so a stored session cookie stops authenticating.

    The only input is the server-verified identity, never request content: no
    request field can name a user, provider subject, tenant, product or
    session.

    Returns the canonical session id to bind into the signed session cookie, or
    ``None`` when this deployment established no canonical session for this
    login — a deployment without the canonical identity shadow, or a canonical
    authority that could not confirm the session. Such a session keeps the
    pre-existing cookie-only behaviour; #5225 adds a revocation path to the
    canonical session, it never removes the compatibility login.

    The D1 shadow write stays best-effort. It is a non-authoritative local
    pointer and never turns a migration telemetry write into login authority;
    a shadow failure therefore does not fail the login.
    """

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    if authority is None or shadow_store is None:
        return None
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
        return None
    return bridged.auth_session.session_id


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
    handoff_record = None
    if not verify_oauth_state(settings, query_state, cookie_state):
        # Android 1.0.0 completes Google in the device's external browser. That
        # browser has no WebView state cookie, so a handoff state is verified by
        # its own signature instead. It only identifies the pending handoff; it
        # never authenticates a user or issues a session.
        if not isinstance(query_state, str) or not query_state:
            return JSONResponse(
                {"error": {"code": "invalid_oauth_state", "message": "로그인 요청을 확인할 수 없습니다. 다시 로그인해 주세요."}},
                status_code=400,
            )
        handoff_record, handoff_response = await load_android_handoff_for_callback(
            request, query_state
        )
        if handoff_response is not None:
            return handoff_response
        if handoff_record is None:
            # Not a signed handoff state either: keep the pre-existing
            # invalid-OAuth-state rejection and never exchange the code.
            return JSONResponse(
                {"error": {"code": "invalid_oauth_state", "message": "로그인 요청을 확인할 수 없습니다. 다시 로그인해 주세요."}},
                status_code=400,
            )
        if handoff_record.status == HANDOFF_STATUS_AWAITING_CONFIRMATION:
            # The Google code was already exchanged on the first callback. A
            # reload must not consume it again; render the same code form.
            return android_handoff_confirm_page(query_state)
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
        canonical_session_id = await _write_identity_shadow_after_login(
            request,
            product_user_id=profile.id,
            provider="google",
            provider_subject=identity["subject"],
            authenticated_at=authenticated_at,
            expires_at=expires_at,
        )
        session = (
            create_session_token(
                settings,
                profile.id,
                now=authenticated_epoch,
                canonical_session_id=canonical_session_id,
            )
            if handoff_record is None
            else None
        )
    except AuthError as exc:
        return JSONResponse({"error": {"code": exc.code, "message": exc.user_message}}, status_code=exc.status_code)
    except Exception:
        return JSONResponse(
            {"error": {"code": "auth_storage_error", "message": "로그인 정보를 저장하지 못했습니다. 다시 시도해 주세요."}},
            status_code=503,
        )

    # #3240: the B62 Google login above is already complete and unchanged. The
    # canonical B54 session is additive and best-effort — a B54 failure returns
    # None here and any B54-scoped operation fails closed on its own later.
    await establish_b54_canonical_session_after_google_login(
        request, profile.id, identity
    )

    await deliver_after_signup(request, profile.id)

    if handoff_record is not None:
        # The external browser gets no session cookie. The WebView that created
        # the handoff claims the verified profile once with its one-time secret.
        bound = await bind_android_handoff_user(request, handoff_record.handoff_id, profile.id)
        if not bound:
            return android_handoff_terminal_page("failed")
        return android_handoff_confirm_page(query_state)

    if not isinstance(session, str) or not session:
        return JSONResponse(
            {"error": {"code": "auth_storage_error", "message": "로그인 정보를 저장하지 못했습니다. 다시 시도해 주세요."}},
            status_code=503,
        )
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(SESSION_COOKIE, session, **session_cookie_kwargs(settings))
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


_PASSWORD_BODY_LIMIT = 16 * 1024
_PASSWORD_FAILURE_LIMIT = 5
_PASSWORD_LOCK_MINUTES = 15
_PASSWORD_LOCK_MINUTES_ESCALATED = 30
_PASSWORD_LOCK_MINUTES_MAX = 60


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


def _password_lock_minutes(window_failures: int) -> int:
    """Lock duration for a recorded failure, from the identifier's own window.

    Monotone in the attacker's own spend and hard-capped. Spending the whole
    dedicated identifier abuse budget therefore *raises* the throttle instead
    of removing it, and the cap keeps a correct password recoverable on
    schedule rather than turning exhaustion into a permanent denial.
    """
    if window_failures <= _PASSWORD_FAILURE_LIMIT:
        return _PASSWORD_LOCK_MINUTES
    if window_failures <= _PASSWORD_FAILURE_LIMIT * 2:
        return _PASSWORD_LOCK_MINUTES_ESCALATED
    return _PASSWORD_LOCK_MINUTES_MAX


_LOGIN_DECOY_IDENTIFIER = "\x00padiem-login-decoy"
# The decoy preimage can never equal a normalized identifier: NUL is rejected
# by both the username grammar and the email grammar, so the decoy HMAC key
# is provably disjoint from every real identifier bucket. Exactly one decoy
# bucket exists per day, no matter how many distinct missing identifiers an
# attacker invents — the missing-identifier durable keyspace stays bounded.


async def _decoy_failure_window(request: Request) -> None:
    """Bounded timing decoy for failure classes without real accounting.

    Missing identifiers and locked accounts have no real counter to advance:
    a real take would either mint durable rows for arbitrary attacker-chosen
    strings or mutate a locked account's escalation state (a new remote lock
    amplification). The fixed-bucket decoy performs the same durable gate
    shape instead. Its result is always discarded: it is never a lock input,
    never an authentication input, and never an existence signal.
    """
    gate = getattr(request.app.state, "auth_abuse_gate", None)
    if gate is None:
        return
    try:
        await gate.record_failure_window(
            identifier=_LOGIN_DECOY_IDENTIFIER,
            raw_ip=request.headers.get("cf-connecting-ip"),
        )
    except Exception:
        pass


async def _identifier_failure_window(
    request: Request, identifier: str
) -> AuthAbuseWindow:
    """Read the identifier's own durable failure window.

    Never raises and never touches the public login projection. An absent,
    exhausted, or failing dedicated store all return the base window, so a
    dedicated-store outage degrades the throttle to its base strength instead
    of switching brute-force protection off.
    """
    gate = getattr(request.app.state, "auth_abuse_gate", None)
    if gate is None:
        return UNAVAILABLE_WINDOW
    try:
        window = await gate.record_failure_window(
            identifier=identifier,
            raw_ip=request.headers.get("cf-connecting-ip"),
        )
    except Exception:
        return UNAVAILABLE_WINDOW
    return window if isinstance(window, AuthAbuseWindow) else UNAVAILABLE_WINDOW


def _display_name_fallback(login_identifier: str) -> str:
    """The display name used when a registration supplies no name.

    The login identifier is the email address, so its readable part is the
    local part. This is a presentation default only; it never becomes an
    account authority.
    """
    return login_identifier.partition("@")[0] or login_identifier


def _session_response(settings: Settings, profile, *, canonical_session_id: str | None = None) -> JSONResponse:
    session = create_session_token(
        settings, profile.id, canonical_session_id=canonical_session_id
    )
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
        # #5424: the email address is the single login identifier. The
        # credential keeps storing that identifier in its own subject column,
        # so the canonical id derivation and the "password:" compatibility
        # subject are unchanged. A client-supplied "username" is no longer
        # part of the signup contract and is ignored on purpose.
        login_identifier = normalize_login_identifier(data.get("email"))
        display_name = normalize_display_name(
            data.get("name"), fallback=_display_name_fallback(login_identifier)
        )
        password = validate_password(
            data.get("password"), identifier=login_identifier
        )
        encoded = await hash_password_async(password)
    except PasswordAuthError as exc:
        return _auth_error(400, exc.code, exc.message)

    store: HistoryStore = request.app.state.history_store
    try:
        # The credential subject and the account email are the one identifier
        # now, so the stored username column holds the normalized email.
        profile = await store.register_password_user(
            login_identifier,
            login_identifier,
            display_name,
            encoded,
        )
    except HistoryConflict:
        return _auth_error(
            409,
            "account_exists",
            "이미 사용 중인 이메일입니다.",
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
    try:
        canonical_session_id = await _write_identity_shadow_after_login(
            request,
            product_user_id=profile.id,
            provider="password",
            provider_subject=login_identifier,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            ensure_personal_tenant=True,
        )
    except Exception:
        canonical_session_id = None
    # Preserve B62's recently merged canonical-session registration fix.
    try:
        registered_credential = await store.find_password_credential(login_identifier)
        if (isinstance(registered_credential, PasswordCredential)
                and registered_credential.user.id == profile.id
                and registered_credential.username == login_identifier):
            await establish_b54_canonical_session_after_login(
                request, registered_credential,
            )
    except Exception:
        # B54 fails closed independently; do not roll back B62 signup.
        pass
    await deliver_after_signup(request, profile.id)
    return _session_response(
        settings, profile, canonical_session_id=canonical_session_id
    )


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
        # The email address is the login identifier (#5424). An account that
        # was registered before the unification keeps signing in with the ID
        # it was created with, so the legacy grammar is still accepted here.
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
    password_ok = await verify_password_async(password, credential.password_hash if credential else None)
    now = datetime.now(timezone.utc)

    # #3501/#3508: lock state is server-owned and never disclosed. A
    # missing identifier, a wrong password, prior failures, an active lock, and
    # an abuse-throttled attempt all reach the same public 401 projection.
    locked = credential is not None and _is_locked(credential, now)

    if credential is None or not password_ok or locked:
        # #3508: failure accounting is NEVER suppressed. Exhausting the
        # dedicated per-identifier abuse budget must strengthen the throttle,
        # not remove it, and a missing or failing dedicated store must leave the
        # base lock policy in force. The gate is only consulted when a real
        # failure is about to be recorded against a real credential, so an
        # unauthenticated caller cannot inflate another subject's window and
        # cannot create abuse rows for identifiers that do not exist.
        #
        # Every other failure class (missing identifier, active lock) runs the
        # fixed-bucket timing decoy instead, so all public failures share one
        # durable gate shape. The decoy never feeds a lock decision.
        if credential is not None and not locked:
            window = await _identifier_failure_window(request, identifier)
            # A lapsed lock starts a fresh failure sequence so one stray
            # failure after expiry does not re-lock the account by itself.
            if _has_expired_lock(credential, now):
                failures, lock_until = 1, None
            else:
                failures = min(100, credential.failed_attempts + 1)
                lock_until = None
                if failures >= _PASSWORD_FAILURE_LIMIT:
                    lock_minutes = _password_lock_minutes(window.identifier_failures)
                    lock_until = (now + timedelta(minutes=lock_minutes)).isoformat()
            try:
                await store.record_password_failure(
                    credential.user.id,
                    failures,
                    lock_until,
                )
            except Exception:
                pass
        else:
            await _decoy_failure_window(request)
        return _auth_error(
            401,
            "invalid_credentials",
            "이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    try:
        await store.reset_password_failures(credential.user.id)
    except Exception:
        return _auth_error(503, "auth_storage_error", "로그인 정보를 갱신하지 못했습니다.")

    settings: Settings = request.app.state.settings
    authenticated_epoch = int(now.timestamp())
    authenticated_at = datetime.fromtimestamp(authenticated_epoch, tz=timezone.utc)
    expires_at = authenticated_at + timedelta(seconds=settings.session_max_age_seconds)
    try:
        canonical_session_id = await _write_identity_shadow_after_login(
            request,
            product_user_id=credential.user.id,
            provider="password",
            provider_subject=credential.username,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            ensure_personal_tenant=True,
        )
    except Exception:
        canonical_session_id = None
    # Establishing the session is the product outcome: it lands in the single
    # canonical Control Plane session store for the B54 product scope, where a
    # B54-scoped consumer resolves it. #2963 Step 3 is that consumer and remains a
    # separately authorized gate, so nothing here projects it to the browser.
    await establish_b54_canonical_session_after_login(request, credential)
    return _session_response(
        settings, credential.user, canonical_session_id=canonical_session_id
    )


async def _revoke_canonical_session(request: Request) -> str | None:
    """Revoke the canonical session behind this cookie.

    Returns ``None`` when the session is ended (or was already gone), or a
    stable error code when the revocation could not be confirmed. #5225: the
    signed cookie is a stateless bearer value, so the canonical session has to
    be revoked server-side before a stored copy of the cookie stops working.

    Shared by the logout and by the #5434 self-service password change, which
    ends the session it changed the credential for.
    """
    settings: Settings = request.app.state.settings
    claims = decode_session_claims(settings, request.cookies.get(SESSION_COOKIE))
    canonical_session_id = claims.canonical_session_id if claims is not None else None
    if not canonical_session_id:
        return None
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    revoke = getattr(authority, "revoke_auth_session", None) if authority is not None else None
    if not callable(revoke):
        return "session_revocation_unavailable"
    try:
        await revoke(
            product_id=PADIEM_CHAT_PRODUCT_ID,
            session_id=canonical_session_id,
        )
    except Exception as exc:
        if getattr(exc, "code", "") != "canonical_auth_session_not_found":
            # The canonical session is still active, so the stored cookie
            # would keep working.
            return "session_revocation_failed"
        # The canonical session is already gone, so the stored cookie can no
        # longer authenticate anything. The outcome is already true.
    return None


async def password_change(request: Request) -> JSONResponse:
    """Change the signed-in account's own password (#5434).

    The account is resolved from the signed session only. A request body can
    never name the account to change, so one signed-in account can never
    change another account's password. The current password is verified
    against the stored hash first, the new password is validated by the same
    server policy the signup uses, and only the hash, the failure counter and
    the lock of that one credential row move.

    The session that changed the credential is ended afterwards, so the browser
    proves the new password by signing in again and a stored copy of the old
    session stops working.
    """
    if not password_auth_ready(request) or not auth_ready(request):
        return _unavailable()
    user_id = current_user_id(request)
    if not user_id:
        return _auth_error(401, "authentication_required", "로그인이 필요합니다.")
    data = await _json_body(request)
    if data is None or set(data) != {"current_password", "new_password"}:
        return _auth_error(400, "invalid_request", "비밀번호 변경 정보를 확인해 주세요.")
    current_password = data.get("current_password")
    new_password = data.get("new_password")
    if not isinstance(current_password, str) or not isinstance(new_password, str):
        return _auth_error(400, "invalid_request", "비밀번호 변경 정보를 확인해 주세요.")

    store: HistoryStore = request.app.state.history_store
    try:
        credential = await store.find_password_credential_by_user_id(user_id)
    except Exception:
        return _auth_error(503, "auth_storage_error", "계정 정보를 확인하지 못했습니다.")
    if credential is None:
        # A Google-only account has no password credential to change, and the
        # existing Google login rule stays exactly as it was.
        return _auth_error(
            400,
            "password_change_unavailable",
            "이 계정은 Google 로그인 계정이라 비밀번호를 변경할 수 없습니다.",
        )

    if not await verify_password_async(current_password, credential.password_hash):
        # The current password is the proof of ownership. A wrong one never
        # reaches the hash and never changes any stored value.
        return _auth_error(401, "invalid_credentials", "현재 비밀번호가 올바르지 않습니다.")

    try:
        validated = validate_password(new_password, identifier=credential.user.email)
    except PasswordAuthError as exc:
        return _auth_error(400, exc.code, exc.message)
    # The new password is hashed once and stored once. The route deliberately
    # runs no further key derivation: the Worker's CPU budget for one request
    # fits the same two derivations the login path already runs, and a third
    # one is what made this route exceed the limit in Production.
    encoded = await hash_password_async(validated)

    # End the session first: a session that cannot be ended leaves the
    # credential untouched, so the user can simply try again.
    failure = await _revoke_canonical_session(request)
    if failure is not None:
        return _auth_error(
            503,
            failure,
            "세션을 종료하지 못했습니다. 다시 시도해 주세요.",
        )
    # #5441: end the sessions of this account on the other devices too. The
    # reviewed single-session revocation above stays in force; this is the
    # additional account-wide revocation, and it is best effort here so an
    # identity authority that predates the capability keeps the route working.
    await _revoke_all_canonical_sessions(request, user_id=user_id, strict=False)
    try:
        await store.update_password_credential(user_id, encoded)
    except Exception:
        return _auth_error(503, "auth_storage_error", "비밀번호를 저장하지 못했습니다.")

    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


async def password_reset_request(request: Request) -> JSONResponse:
    """Issue one lost-password reset link (#5441).

    The member proves ownership of the account's email address with a
    one-time link and then chooses the new password themselves. An email
    address alone never changes a password: the stored hash moves only after
    that link is redeemed.

    The public answer never says whether the address belongs to an account, so
    this unauthenticated route cannot be used to enumerate members. When the
    deployment has no mail transport at all the request is refused honestly
    with a retryable error instead of a fake "we sent it" answer.
    """

    if not password_auth_ready(request) or not auth_ready(request):
        return _unavailable()
    service = _password_reset_service(request)
    if service is None or not service.ready:
        return _auth_error(
            503, RESET_UNAVAILABLE, "비밀번호 찾기를 현재 사용할 수 없습니다."
        )
    delivery = _password_reset_delivery(request)
    if delivery is None:
        return _auth_error(
            503,
            RESET_DELIVERY_UNAVAILABLE,
            "비밀번호 찾기 메일을 현재 보낼 수 없습니다. 잠시 후 다시 시도해 주세요.",
        )
    data = await _json_body(request)
    if data is None or set(data) != {"email"}:
        return _auth_error(400, RESET_INVALID_REQUEST, "이메일 정보를 확인해 주세요.")
    raw_email = data.get("email")
    try:
        identifier = normalize_email(raw_email)
    except PasswordAuthError as exc:
        return _auth_error(400, exc.code, exc.message)

    try:
        await service.check_request_allowed(identifier=identifier)
    except PasswordResetError as exc:
        # A throttled request is audited as rejected, so it never consumes the
        # daily budget it was refused by.
        await service.record_request(
            identifier=identifier, user_id=None, reason_code=exc.code
        )
        return _auth_error(429, exc.code, exc.message)

    store: HistoryStore = request.app.state.history_store
    try:
        credential = await store.find_password_credential(identifier)
    except Exception:
        return _auth_error(503, "auth_storage_error", "계정 정보를 확인하지 못했습니다.")

    # Always run the verifier, including for an unknown identifier, so the
    # answer time does not reveal whether the address owns an account.
    await verify_password_async("", credential.password_hash if credential else None)

    await service.record_request(
        identifier=identifier,
        user_id=credential.user.id if credential is not None else None,
    )
    if credential is None:
        # No password credential owns this identifier: there is no password to
        # reset and no mail is sent. The public answer stays the same one.
        return JSONResponse({"ok": True}, status_code=202)

    raw_token, _token = await service.issue(
        identifier=identifier, user_id=credential.user.id
    )
    link = service.link_for(raw_token)
    delivered = False
    try:
        from .password_reset_delivery import (
            RESET_MAIL_SUBJECT,
            build_reset_mail_text,
        )

        delivered = bool(
            await delivery.send(
                to=identifier,
                subject=RESET_MAIL_SUBJECT,
                text=build_reset_mail_text(link),
            )
        )
    except Exception:
        delivered = False
    await service.record_delivery(
        identifier=identifier, user_id=credential.user.id, delivered=delivered
    )
    # The answer is the same for a delivered and for a refused mail, so the
    # route never reveals whether the address owns an account. The delivery
    # outcome itself is recorded in the audit ledger.
    return JSONResponse({"ok": True}, status_code=202)


async def password_reset_confirm(request: Request) -> JSONResponse:
    """Redeem one reset link and set the new password (#5441).

    The token is single use and short lived. A second redemption of the same
    token is refused, the outstanding tokens of that account die with the
    successful redemption, and every canonical session of that account is
    ended before the stored hash moves, so the old password and every old
    session stop working together.
    """

    if not password_auth_ready(request) or not auth_ready(request):
        return _unavailable()
    service = _password_reset_service(request)
    if service is None or not service.ready:
        return _auth_error(
            503, RESET_UNAVAILABLE, "비밀번호 찾기를 현재 사용할 수 없습니다."
        )
    data = await _json_body(request)
    if data is None or set(data) != {"token", "new_password"}:
        return _auth_error(400, RESET_INVALID_REQUEST, "비밀번호 정보를 확인해 주세요.")
    raw_token = data.get("token")
    new_password = data.get("new_password")
    if not isinstance(raw_token, str) or not isinstance(new_password, str):
        return _auth_error(400, RESET_INVALID_REQUEST, "비밀번호 정보를 확인해 주세요.")

    peeked = await service.peek(raw_token)
    if peeked is None:
        return _auth_error(
            400, RESET_TOKEN_INVALID, "재설정 링크가 올바르지 않습니다."
        )

    store: HistoryStore = request.app.state.history_store
    try:
        credential = await store.find_password_credential_by_user_id(peeked.user_id)
    except Exception:
        return _auth_error(503, "auth_storage_error", "계정 정보를 확인하지 못했습니다.")
    if credential is None:
        return _auth_error(
            400, RESET_TOKEN_INVALID, "재설정 링크가 올바르지 않습니다."
        )
    try:
        validated = validate_password(new_password, identifier=credential.user.email)
    except PasswordAuthError as exc:
        return _auth_error(400, exc.code, exc.message)
    encoded = await hash_password_async(validated)

    # End every session of this account first. A session that cannot be ended
    # leaves the credential untouched, so the member can retry with the same
    # link.
    failure = await _revoke_all_canonical_sessions(
        request, user_id=peeked.user_id, strict=True
    )
    if failure is not None:
        return _auth_error(
            503,
            failure,
            "세션을 종료하지 못했습니다. 다시 시도해 주세요.",
        )

    try:
        user_id = await service.redeem(raw_token=raw_token)
    except PasswordResetError as exc:
        return _auth_error(400, exc.code, exc.message)
    if user_id != peeked.user_id:
        return _auth_error(
            400, RESET_TOKEN_INVALID, "재설정 링크가 올바르지 않습니다."
        )

    try:
        await store.update_password_credential(user_id, encoded)
    except Exception:
        return _auth_error(503, "auth_storage_error", "비밀번호를 저장하지 못했습니다.")

    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


async def logout(request: Request) -> JSONResponse:
    """Revoke the canonical session behind this cookie, then clear the cookie.

    #5225: deleting the browser cookie alone left the signed session token
    usable on every protected Chat/Claw API until it expired. The canonical
    Control Plane session is therefore revoked server-side first, so a stored
    copy of the cookie is refused by the protected APIs immediately after a
    successful logout.

    Exactly one canonical session is revoked. A second device that signed in
    normally owns a different canonical session and keeps it.

    A revocation the canonical authority could not confirm is reported as a
    failure and the cookie is kept: the session was not ended, so the logout
    must not be reported as successful.
    """

    failure = await _revoke_canonical_session(request)
    if failure is not None:
        return _auth_error(
            503,
            failure,
            "로그아웃을 완료하지 못했습니다. 다시 시도해 주세요.",
        )
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response
