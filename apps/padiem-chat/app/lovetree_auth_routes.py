"""LoveTree 4.0 sign-in handoff: create, bind, and return a one-time login ticket.

LoveTree keeps its own front door and its own session, and PADIEM keeps the only login
authority. These routes are the seam between them:

* ``lovetree_handoff_start`` records one login request as a row (digest of LoveTree's own
  OAuth state, the allowlisted return origin, short expiry) and sends the browser into the
  **existing** Google sign-in with a Chat-signed state that names that row.
* ``load_lovetree_handoff_for_callback`` recognises that signed state inside the existing
  ``google_callback``; the Android and normal cookie flows are untouched.
* ``bind_lovetree_handoff`` is called only with an identity this Worker just verified — the
  Google upsert profile id plus the provider subject from the userinfo response. Nothing a
  request supplied (user id, email, subject) is ever a basis.
* ``return_to_lovetree`` sends the ticket back to the row's own recorded origin, with the
  login request the row was created for.

The store never mints a session and neither do these routes: issuance happens on the
identity authority, through the ``lovetree-auth-caller`` relay, and only after the ticket
has been claimed there with the matching login-request digest.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.auth import (
    AuthError,
    GoogleOAuthClient,
    Settings,
    create_lovetree_handoff_state,
    is_lovetree_login_request,
    verify_lovetree_handoff_state,
)
from app.lovetree_auth_store import (
    LoveTreeHandoffRecord,
    LoveTreeLoginHandoffStore,
    checked_origin,
    handoff_digest,
    is_loopback_origin,
)

LOVETREE_HANDOFF_TTL_SECONDS = 120
LOVETREE_HANDOFF_CALLBACK_PATH = "/auth/callback"
_LOVETREE_NO_STORE = "lovetree_handoff_unavailable"
_LOVETREE_RETURN_ORIGINS = frozenset({
    # Deployment-owned allowlist. The row records which of these a login started from and
    # the return leg uses only that stored value — never a host taken from the request.
    "https://lovetree-4-0.pages.dev",
    "http://127.0.0.1:8788",
    "http://localhost:8788",
})


@dataclass(frozen=True, slots=True)
class PendingLoveTreeHandoff:
    record: LoveTreeHandoffRecord
    login_request: str


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> LoveTreeLoginHandoffStore | None:
    return getattr(request.app.state, "lovetree_handoff_store", None)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _bridge_origin(request: Request) -> str | None:
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    return headers.get("x-b66-origin")


def _error(status: int, code: str, message: str = "로그인 요청을 확인할 수 없습니다. 다시 로그인해 주세요.") -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _unavailable() -> JSONResponse:
    return _error(503, _LOVETREE_NO_STORE, "로그인을 현재 사용할 수 없습니다.")


def not_ready() -> JSONResponse:
    """Terminal answer when a row never reached 'ready': LoveTree gets no ticket."""
    return _error(503, "lovetree_handoff_not_ready", "로그인 확인을 마치지 못했어요. 다시 시도해 주세요.")


def _new_ticket_id() -> str:
    return f"lovt_{secrets.token_urlsafe(18)}"


def allowed_return_origin(value: object) -> str | None:
    """The recorded return address: an explicitly reviewed origin, or a loopback test one.

    A test harness binds an ephemeral port, so loopback http is accepted by shape (same
    rule the table's CHECK and the LoveTree service use). Anywhere else has to be named
    here — a request never chooses a host.
    """
    if not isinstance(value, str):
        return None
    if is_loopback_origin(value):
        return checked_origin(value)
    if value not in _LOVETREE_RETURN_ORIGINS:
        return None
    try:
        return checked_origin(value)
    except ValueError:
        return None


async def lovetree_handoff_start(request: Request) -> Response:
    store = _store(request)
    settings: Settings = _settings(request)
    if store is None:
        return _unavailable()

    login_request = request.query_params.get("state")
    if not is_lovetree_login_request(login_request):
        return _error(400, "invalid_lovetree_login_request")
    origin = allowed_return_origin(request.query_params.get("return_origin"))
    if origin is None:
        return _error(400, "invalid_lovetree_return_origin", "되돌아갈 주소를 확인할 수 없어요.")

    ticket_id = _new_ticket_id()
    now = _now()
    try:
        record = await store.create(
            ticket_id=ticket_id,
            login_request=login_request,
            return_origin=origin,
            now_iso=_iso(now),
            expires_at_iso=_iso(now + timedelta(seconds=LOVETREE_HANDOFF_TTL_SECONDS)),
        )
        signed = create_lovetree_handoff_state(settings, ticket_id, login_request)
        identity = await _verified_session_identity(request)
        if identity is not None:
            user_id, auth_provider, provider_subject = identity
            bound = await store.bind_verified_identity(
                ticket_id,
                user_id=user_id,
                auth_provider=auth_provider,
                provider_subject=provider_subject,
                state_sha256=record.state_sha256,
                now_iso=_iso(_now()),
            )
            if not bound:
                # The row was just created as 'awaiting_login' in this request, so a
                # refusal here is a storage failure, never a user identity decision.
                # No ticket, no redirect: the browser must not be sent to LoveTree.
                return not_ready()
            fresh = await store.get(ticket_id)
            location = handoff_return_url(fresh, login_request) if fresh is not None else None
            if location is None:
                return not_ready()
        else:
            location = await _sign_in_entry(request, settings, signed)
    except AuthError as exc:
        # A refusal before any redirect is terminal: the browser is never sent to
        # LoveTree without a ready row. The specific cause stays visible.
        return _error(exc.status_code, exc.code, exc.user_message)
    except Exception:
        # A row that could not be created must not turn into a half-started login.
        return _unavailable()
    if location is None:
        return _unavailable()
    # No cookie: this browser is authenticating in order to hand a ticket to LoveTree, and
    # it never receives a PADIEM session from these routes. The browser's own
    # existing Chat session (if any) is unchanged -- the skip above only reads it.
    return RedirectResponse(location, status_code=302)


async def _sign_in_entry(request: Request, settings: Settings, signed: str) -> str | None:
    """Where an unfinished login goes: the existing Google flow, or the existing dialog.

    A Google run keeps using the canonical Chat callback (one registered
    redirect_uri, no new OAuth surface). A password-only or hybrid deployment
    lands on the page that already hosts the login dialog, which passes the
    signed value back through the form it already submits; the dialog's Google
    button returns on the same single-use handoff via
    ``lovetree_google_entry``.
    """
    if settings.auth_mode == "google":
        oauth = getattr(request.app.state, "google_oauth", None)
        if not isinstance(oauth, GoogleOAuthClient):
            return None
        return oauth.authorization_url(signed, bridge_origin=_bridge_origin(request))
    if settings.auth_mode in {"password", "hybrid"}:
        base = (settings.public_base_url or "").rstrip("/")
        if not base:
            return None
        return f"{base}/?{urlencode({'handoff': signed})}"
    return None


async def _verified_session_identity(request: Request) -> tuple[str, str, str] | None:
    """The provider-verified identity behind this browser's Chat session, or None.

    Session validity is decided by the function Chat already uses elsewhere --
    ``current_user_id`` from ``app.auth_routes`` -- which honours the canonical
    session verdict (#5225), never a new session validator here. The provider
    identity is resolved only from server-side rows that Chat itself trusts:

    * a password credential row gives ``("password", username)`` -- the same
      subject the password login leg binds -- via
      ``find_password_credential_by_user_id``;
    * otherwise the ``users`` row gives ``(auth_provider, provider_subject)``
      only when it is a real Google subject -- never a ``password:`` compatibility
      marker and never a ``shared:`` placeholder, which this finish path must not
      invent into a provider subject.

    Anything unresolved returns None and the caller falls through to the normal
    sign-in entry, where a fresh login re-verifies the identity.
    """
    from .auth_routes import current_user_id

    user_id = current_user_id(request)
    if not isinstance(user_id, str) or not user_id:
        return None
    history = getattr(request.app.state, "history_store", None)
    if history is None:
        return None
    lookup = getattr(history, "find_password_credential_by_user_id", None)
    if callable(lookup):
        try:
            credential = await lookup(user_id)
        except Exception:
            credential = None
        username = getattr(credential, "username", None) if credential is not None else None
        if isinstance(username, str) and username.strip():
            return (user_id, "password", username)
    get_user = getattr(history, "get_user", None)
    if not callable(get_user):
        return None
    try:
        profile = await get_user(user_id)
    except Exception:
        return None
    provider = getattr(profile, "auth_provider", None)
    subject = getattr(profile, "provider_subject", None)
    if (
        provider in {"google", "password"}
        and isinstance(subject, str)
        and subject.strip()
        and not subject.startswith("password:")
        and not subject.startswith("shared:")
    ):
        return (user_id, str(provider), subject)
    return None


async def load_lovetree_handoff_for_callback(
    request: Request, state: str | None
) -> tuple[PendingLoveTreeHandoff | None, Response | None]:
    """Resolve a Chat-signed LoveTree state to its live row.

    `(None, None)` means "not this flow" and the caller keeps its own rejection. A
    response in the second slot is terminal — nothing is exchanged for it.
    """
    settings: Settings = _settings(request)
    verified = verify_lovetree_handoff_state(settings, state)
    if verified is None:
        return None, None
    ticket_id, login_request = verified
    store = _store(request)
    if store is None:
        return None, _unavailable()
    record = await store.get(ticket_id)
    if record is None or record.state_sha256 != handoff_digest(login_request):
        return None, _error(400, "invalid_lovetree_handoff")
    if record.status != "awaiting_login":
        # The Google code was already exchanged on a first callback. A reload must not
        # consume it twice, and a bound row must not be re-bound.
        return None, _error(400, "lovetree_handoff_used")
    if not record.is_live(_iso(_now())):
        return None, _error(400, "lovetree_handoff_expired")
    return PendingLoveTreeHandoff(record=record, login_request=login_request), None


async def bind_lovetree_handoff(
    request: Request,
    pending: PendingLoveTreeHandoff,
    *,
    user_id: str,
    auth_provider: str,
    provider_subject: str,
) -> bool:
    """Write the identity this Worker just verified onto the row. Single transition."""
    store = _store(request)
    if store is None:
        return False
    now = _iso(_now())
    return await store.bind_verified_identity(
        pending.record.ticket_id,
        user_id=user_id,
        auth_provider=auth_provider,
        provider_subject=provider_subject,
        state_sha256=pending.record.state_sha256,
        now_iso=now,
    )


def handoff_return_url(record: LoveTreeHandoffRecord, login_request: str) -> str | None:
    """The only address a finished handoff may go to: the origin the row recorded.

    A request never supplies a host here. The stored origin is re-checked against the
    same allowlist and the same login-request digest the row was created with.
    """
    origin = allowed_return_origin(record.return_origin)
    if origin is None or record.state_sha256 != handoff_digest(login_request):
        return None
    query = urlencode({"code": record.ticket_id, "state": login_request})
    return f"{origin}{LOVETREE_HANDOFF_CALLBACK_PATH}?{query}"


async def return_to_lovetree(request: Request, pending: PendingLoveTreeHandoff) -> Response:
    """Hand the ticket back to the origin the row recorded, with that row's login request."""
    store = _store(request)
    record = await store.get(pending.record.ticket_id) if store is not None else None
    if record is None or record.status != "ready":
        return not_ready()
    location = handoff_return_url(record, pending.login_request)
    if location is None:
        return not_ready()
    response = RedirectResponse(location, status_code=302)
    response.headers["cache-control"] = "no-store"
    return response


async def bind_after_verified_login(
    request: Request,
    handoff_value: object,
    *,
    user_id: str,
    auth_provider: str,
    provider_subject: str,
) -> str | None:
    """Bind a handoff to an identity this Worker just verified, and return the hop URL.

    Used by the password leg, where the browser finishes sign-in inside the existing
    dialog and the answer comes back as JSON. Returns None whenever there is no claimable
    handoff — including a handoff that is forged, expired, already used, or bound to a
    different login request — so a failed or unrelated login never produces one.
    """
    settings: Settings = _settings(request)
    verified = verify_lovetree_handoff_state(settings, handoff_value if isinstance(handoff_value, str) else None)
    if verified is None:
        return None
    ticket_id, login_request = verified
    store = _store(request)
    if store is None:
        return None
    record = await store.get(ticket_id)
    if record is None or record.status != "awaiting_login" or not record.is_live(_iso(_now())):
        return None
    if record.state_sha256 != handoff_digest(login_request):
        return None
    bound = await store.bind_verified_identity(
        ticket_id,
        user_id=user_id,
        auth_provider=auth_provider,
        provider_subject=provider_subject,
        state_sha256=record.state_sha256,
        now_iso=_iso(_now()),
    )
    if not bound:
        return None
    fresh = await store.get(ticket_id)
    if fresh is None or fresh.status != "ready":
        return None
    return handoff_return_url(fresh, login_request)


async def lovetree_google_entry(request: Request) -> Response:
    """Continue a pending handoff on Google from the Chat login dialog.

    The dialog's Google button arrives here with ``?handoff=<signed>`` instead of
    starting a fresh Google run. The signed handoff becomes the OAuth ``state`` --
    exactly like ``_sign_in_entry``'s Google leg -- and the existing
    ``google_callback`` recognises it through ``load_lovetree_handoff_for_callback``
    and binds the Google-verified identity. No session cookie is set here; a reused,
    expired, forged, or mismatched row fails closed through the same checks the
    callback uses.
    """
    settings = _settings(request)
    signed = request.query_params.get("handoff")
    if not isinstance(signed, str) or not signed.strip():
        return _error(400, "invalid_lovetree_handoff", "로그인 요청을 확인할 수 없어요. 처음부터 다시 시도해 주세요.")
    # The dialog only offers Google on a deployment that offers Google. The
    # handoff branch in google_start runs before that readiness gate, so apply
    # the same existing gate here instead of opening a new Google surface.
    from .auth_routes import google_auth_ready

    if not google_auth_ready(request):
        return _unavailable()
    verified = verify_lovetree_handoff_state(settings, signed)
    if verified is None:
        return _error(400, "invalid_lovetree_handoff", "로그인 요청을 확인할 수 없어요. 처음부터 다시 시도해 주세요.")
    store = _store(request)
    if store is None:
        return _unavailable()
    ticket_id, login_request = verified
    record = await store.get(ticket_id)
    if record is None:
        return _error(400, "invalid_lovetree_handoff", "로그인 요청을 확인할 수 없어요. 처음부터 다시 시도해 주세요.")
    if record.state_sha256 != handoff_digest(login_request):
        return _error(400, "invalid_lovetree_handoff", "로그인 요청을 확인할 수 없어요. 처음부터 다시 시도해 주세요.")
    if record.status != "awaiting_login":
        return _error(400, "lovetree_handoff_used", "이미 사용한 로그인 요청이에요. 처음부터 다시 시도해 주세요.")
    if not record.is_live(_iso(_now())):
        return _error(400, "lovetree_handoff_expired", "로그인 시간이 만료됐어요. 처음부터 다시 시도해 주세요.")
    oauth = getattr(request.app.state, "google_oauth", None)
    if not isinstance(oauth, GoogleOAuthClient):
        return _unavailable()
    try:
        location = oauth.authorization_url(signed, bridge_origin=_bridge_origin(request))
    except AuthError as exc:
        return _error(exc.status_code, exc.code, exc.user_message)
    response = RedirectResponse(location, status_code=302)
    response.headers["cache-control"] = "no-store"
    return response


__all__ = [
    "LOVETREE_HANDOFF_CALLBACK_PATH",
    "LOVETREE_HANDOFF_TTL_SECONDS",
    "PendingLoveTreeHandoff",
    "allowed_return_origin",
    "bind_after_verified_login",
    "bind_lovetree_handoff",
    "handoff_return_url",
    "load_lovetree_handoff_for_callback",
    "lovetree_google_entry",
    "lovetree_handoff_start",
    "not_ready",
    "return_to_lovetree",
]
