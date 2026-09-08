from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlencode, urlsplit

from padiem_control_plane.connector_connect_ticket import (
    ConnectorConnectTicketAuthority,
    ConnectorConnectTicketClaims,
)
from padiem_control_plane.contracts import ControlPlaneContractError

from google_oauth_durable_store import (
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
    DurableGoogleOAuthAuthorizationState,
    DurableGoogleOAuthCredential,
)
from google_oauth_webcrypto_sealer import (
    GoogleOAuthSealContext,
    GoogleOAuthSealPurpose,
    GoogleOAuthWebCryptoSealer,
)


GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTHORIZATION_SESSION_TTL_SECONDS = 600
MAX_AUTHORIZATION_CODE_CHARS = 4_096
MAX_PROVIDER_ERROR_CHARS = 1_024
MAX_TOKEN_RESPONSE_BYTES = 262_144
MAX_REFRESH_TOKEN_LIFETIME_SECONDS = 366 * 24 * 60 * 60
MAX_CONNECT_TICKET_CHARS = 24_576

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~\-]{43,128}$")
_KEY_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_REVIEWED_SCOPES = {
    "gmail": (GMAIL_READONLY_SCOPE,),
    "google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),
}
_AUTH_SESSION_SENTINEL = "sealed-session-identity"


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must be a bounded safe reference",
        )
    return value


def _bounded_secret(value: Any, field_name: str, *, max_chars: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_chars
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must be non-empty bounded text",
        )
    return value.strip()


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must be timezone-aware",
        )
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must be ISO-8601 text",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must be valid ISO-8601 text",
        ) from exc
    return _utc(parsed, field_name)


def _https_uri(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ControlPlaneContractError("invalid_google_oauth_ingress", f"{field_name} must be text")
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or len(normalized) > 2_048
    ):
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must be a bounded HTTPS URI",
        )
    return normalized


def _decode_key_secret(secret_b64url: str, field_name: str) -> bytes:
    if not isinstance(secret_b64url, str) or not _KEY_SECRET_RE.fullmatch(secret_b64url):
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress_secret",
            f"{field_name} must encode exactly 32 random bytes",
        )
    padding = "=" * (-len(secret_b64url) % 4)
    try:
        decoded = base64.b64decode(secret_b64url + padding, altchars=b"-_", validate=True)
    except (TypeError, ValueError) as exc:
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress_secret",
            f"{field_name} is not valid base64url",
        ) from exc
    if len(decoded) != 32:
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress_secret",
            f"{field_name} must decode to 256 bits",
        )
    return decoded


def _pkce_challenge(verifier: str) -> str:
    if not isinstance(verifier, str) or not _PKCE_VERIFIER_RE.fullmatch(verifier):
        raise ControlPlaneContractError("invalid_google_oauth_ingress", "PKCE verifier is invalid")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _closed_dict(value: Any, required: frozenset[str], field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must contain exactly the reviewed fields",
        )
    return value


@dataclass(frozen=True, slots=True)
class GoogleOAuthIngressConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_id", _bounded_secret(self.client_id, "client_id", max_chars=4_096))
        object.__setattr__(
            self,
            "client_secret",
            _bounded_secret(self.client_secret, "client_secret", max_chars=16_384),
        )
        object.__setattr__(self, "redirect_uri", _https_uri(self.redirect_uri, "redirect_uri"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "client_secret_present": True,
            "raw_client_secret": False,
        }


@dataclass(frozen=True, slots=True)
class GoogleOAuthSessionPayload:
    state_ref: str
    connector_id: str
    actor_ref: str
    account_ref: str
    workspace_ref: str
    scopes: tuple[str, ...]
    code_verifier: str = field(repr=False)
    redirect_uri: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "state_ref",
            "connector_id",
            "actor_ref",
            "account_ref",
            "workspace_ref",
        ):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        expected = _REVIEWED_SCOPES.get(self.connector_id)
        if expected is None or not isinstance(self.scopes, tuple) or set(self.scopes) != set(expected):
            raise ControlPlaneContractError(
                "unreviewed_google_oauth_scope",
                "OAuth session scopes must exactly match the reviewed readonly set",
            )
        object.__setattr__(self, "scopes", expected)
        verifier = _bounded_secret(self.code_verifier, "code_verifier", max_chars=128)
        if not _PKCE_VERIFIER_RE.fullmatch(verifier):
            raise ControlPlaneContractError("invalid_google_oauth_ingress", "code_verifier is invalid")
        object.__setattr__(self, "code_verifier", verifier)
        object.__setattr__(self, "redirect_uri", _https_uri(self.redirect_uri, "redirect_uri"))
        created = _utc(self.created_at, "created_at")
        expires = _utc(self.expires_at, "expires_at")
        if not created < expires <= created + timedelta(seconds=AUTHORIZATION_SESSION_TTL_SECONDS):
            raise ControlPlaneContractError(
                "invalid_google_oauth_ingress",
                "authorization session expiry exceeds the trusted bound",
            )
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)

    def to_plaintext(self) -> str:
        return json.dumps(
            {
                "state_ref": self.state_ref,
                "connector_id": self.connector_id,
                "actor_ref": self.actor_ref,
                "account_ref": self.account_ref,
                "workspace_ref": self.workspace_ref,
                "scopes": list(self.scopes),
                "code_verifier": self.code_verifier,
                "redirect_uri": self.redirect_uri,
                "created_at": _iso(self.created_at),
                "expires_at": _iso(self.expires_at),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    @classmethod
    def from_plaintext(cls, plaintext: str) -> "GoogleOAuthSessionPayload":
        try:
            wire = json.loads(plaintext)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ControlPlaneContractError(
                "invalid_google_oauth_ingress",
                "sealed OAuth session payload is invalid",
            ) from exc
        wire = _closed_dict(
            wire,
            frozenset(
                {
                    "state_ref",
                    "connector_id",
                    "actor_ref",
                    "account_ref",
                    "workspace_ref",
                    "scopes",
                    "code_verifier",
                    "redirect_uri",
                    "created_at",
                    "expires_at",
                }
            ),
            "sealed OAuth session payload",
        )
        try:
            scopes = tuple(wire["scopes"])
        except TypeError as exc:
            raise ControlPlaneContractError(
                "invalid_google_oauth_ingress",
                "sealed OAuth session scopes are invalid",
            ) from exc
        return cls(
            state_ref=wire["state_ref"],
            connector_id=wire["connector_id"],
            actor_ref=wire["actor_ref"],
            account_ref=wire["account_ref"],
            workspace_ref=wire["workspace_ref"],
            scopes=scopes,
            code_verifier=wire["code_verifier"],
            redirect_uri=wire["redirect_uri"],
            created_at=_parse_iso(wire["created_at"], "created_at"),
            expires_at=_parse_iso(wire["expires_at"], "expires_at"),
        )


@dataclass(frozen=True, slots=True)
class GoogleOAuthAuthorizationStartReceipt:
    authorization_url: str
    connector_id: str
    expires_at: datetime

    def safe_dict(self) -> dict[str, Any]:
        return {
            "authorization_url": self.authorization_url,
            "connector_id": self.connector_id,
            "expires_at": _iso(self.expires_at),
            "raw_connect_ticket": False,
            "raw_pkce_verifier": False,
            "raw_client_secret": False,
        }


@dataclass(frozen=True, slots=True)
class GoogleOAuthConnectedReceipt:
    binding_ref: str
    connector_id: str
    actor_ref: str
    account_ref: str
    workspace_ref: str
    scopes: tuple[str, ...]
    connected_at: datetime
    expires_at: datetime | None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "scopes": list(self.scopes),
            "connected_at": _iso(self.connected_at),
            "expires_at": _iso(self.expires_at) if self.expires_at is not None else None,
            "refresh_token_persisted_sealed": True,
            "access_token_discarded": True,
            "raw_authorization_code": False,
            "raw_access_token": False,
            "raw_refresh_token": False,
            "raw_client_secret": False,
        }


class GoogleOAuthTokenExchangePort(Protocol):
    async def exchange_authorization_code(
        self,
        *,
        config: GoogleOAuthIngressConfig,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        ...


class CloudflareGoogleOAuthTokenExchangePort:
    """Worker-native outbound token exchange using the supported async Fetch API."""

    async def exchange_authorization_code(
        self,
        *,
        config: GoogleOAuthIngressConfig,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        from workers import fetch  # type: ignore[import-not-found]

        form = urlencode(
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )
        response = await fetch(
            GOOGLE_TOKEN_URL,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-store",
            },
            body=form,
        )
        status = getattr(response, "status", None)
        if type(status) is not int or status != 200:
            raise ControlPlaneContractError(
                "google_oauth_token_exchange_failed",
                "Google OAuth authorization-code exchange failed",
            )
        text = await response.text()
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TOKEN_RESPONSE_BYTES:
            raise ControlPlaneContractError(
                "google_oauth_token_exchange_failed",
                "Google OAuth token response exceeds the trusted bound",
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ControlPlaneContractError(
                "google_oauth_token_exchange_failed",
                "Google OAuth token response is invalid",
            ) from exc
        if not isinstance(payload, dict):
            raise ControlPlaneContractError(
                "google_oauth_token_exchange_failed",
                "Google OAuth token response must be an object",
            )
        return payload

    def safe_dict(self) -> dict[str, Any]:
        return {
            "cloudflare_worker_fetch": True,
            "token_endpoint": GOOGLE_TOKEN_URL,
            "post_only": True,
            "no_store": True,
            "response_bytes_bounded": True,
            "raw_client_secret_public": False,
            "raw_authorization_code_public": False,
        }


class GoogleOAuthIngressRuntime:
    """Private durable runtime behind the dedicated public OAuth edge."""

    def __init__(
        self,
        *,
        store: CloudflareDurableGoogleOAuthStore,
        sealer: GoogleOAuthWebCryptoSealer,
        ticket_authority: ConnectorConnectTicketAuthority,
        config: GoogleOAuthIngressConfig,
        token_exchange: GoogleOAuthTokenExchangePort,
        clock: Callable[[], datetime] | None = None,
        random_token: Callable[[int], str] | None = None,
    ) -> None:
        self._store = store
        self._sealer = sealer
        self._ticket_authority = ticket_authority
        self._config = config
        self._token_exchange = token_exchange
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._random_token = random_token or secrets.token_urlsafe

    def _now(self) -> datetime:
        return _utc(self._clock(), "clock")

    def _token(self, size: int, field_name: str) -> str:
        value = self._random_token(size)
        return _safe_ref(value, field_name)

    @staticmethod
    def _authorization_context(*, state_ref: str, connector_id: str) -> GoogleOAuthSealContext:
        # state_ref is unique and is the row/callback binding. Identity remains
        # authenticated inside the sealed session; it is not duplicated in the
        # durable state row merely to reconstruct AAD.
        return GoogleOAuthSealContext(
            purpose=GoogleOAuthSealPurpose.AUTHORIZATION_SESSION,
            connector_id=connector_id,
            record_ref=state_ref,
            actor_ref=_AUTH_SESSION_SENTINEL,
            account_ref=_AUTH_SESSION_SENTINEL,
            workspace_ref=_AUTH_SESSION_SENTINEL,
        )

    @staticmethod
    def _credential_context(
        *,
        binding_ref: str,
        connector_id: str,
        actor_ref: str,
        account_ref: str,
        workspace_ref: str,
    ) -> GoogleOAuthSealContext:
        return GoogleOAuthSealContext(
            purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
            connector_id=connector_id,
            record_ref=binding_ref,
            actor_ref=actor_ref,
            account_ref=account_ref,
            workspace_ref=workspace_ref,
        )

    async def begin(self, *, connect_ticket: str) -> GoogleOAuthAuthorizationStartReceipt:
        ticket = _bounded_secret(
            connect_ticket,
            "connect_ticket",
            max_chars=MAX_CONNECT_TICKET_CHARS,
        )
        now = self._now()
        claims = self._ticket_authority.verify(token=ticket, now=now)
        expected_scopes = _REVIEWED_SCOPES.get(claims.connector_id)
        if expected_scopes is None or set(claims.scopes) != set(expected_scopes):
            raise ControlPlaneContractError(
                "unreviewed_google_oauth_scope",
                "connector ticket does not authorize a reviewed Google readonly connector",
            )

        state_ref = self._token(32, "state_ref")
        verifier = self._random_token(64)
        if not isinstance(verifier, str) or not _PKCE_VERIFIER_RE.fullmatch(verifier):
            raise ControlPlaneContractError(
                "invalid_google_oauth_ingress",
                "random source returned an invalid PKCE verifier",
            )
        expires_at = now + timedelta(seconds=AUTHORIZATION_SESSION_TTL_SECONDS)
        session = GoogleOAuthSessionPayload(
            state_ref=state_ref,
            connector_id=claims.connector_id,
            actor_ref=claims.actor_ref,
            account_ref=claims.account_ref,
            workspace_ref=claims.workspace_ref,
            scopes=expected_scopes,
            code_verifier=verifier,
            redirect_uri=self._config.redirect_uri,
            created_at=now,
            expires_at=expires_at,
        )
        sealed_session = await self._sealer.seal_text(
            plaintext=session.to_plaintext(),
            context=self._authorization_context(
                state_ref=state_ref,
                connector_id=claims.connector_id,
            ),
        )
        durable_state = DurableGoogleOAuthAuthorizationState(
            state_ref=state_ref,
            ticket_id=claims.ticket_id,
            connector_id=claims.connector_id,
            sealed_session=sealed_session,
            created_at=now,
            expires_at=expires_at,
        )
        self._store.begin_authorization(
            ticket_id=claims.ticket_id,
            connector_id=claims.connector_id,
            ticket_expires_at=claims.expires_at,
            state=durable_state,
            now=now,
        )
        authorization_url = GOOGLE_AUTHORIZATION_URL + "?" + urlencode(
            {
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "response_type": "code",
                "scope": " ".join(expected_scopes),
                "access_type": "offline",
                "prompt": "consent",
                "state": state_ref,
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        return GoogleOAuthAuthorizationStartReceipt(
            authorization_url=authorization_url,
            connector_id=claims.connector_id,
            expires_at=expires_at,
        )

    async def complete_callback(
        self,
        *,
        state_ref: str,
        authorization_code: str | None,
        provider_error: str | None,
    ) -> GoogleOAuthConnectedReceipt:
        state_ref = _safe_ref(state_ref, "state_ref")
        now = self._now()
        # Consume first. Denials, malformed codes, expired states and token
        # exchange failures never make this callback state replayable.
        durable_state = self._store.consume_authorization_state(state_ref=state_ref, now=now)
        plaintext = await self._sealer.unseal_text(
            envelope=durable_state.sealed_session,
            context=self._authorization_context(
                state_ref=durable_state.state_ref,
                connector_id=durable_state.connector_id,
            ),
        )
        session = GoogleOAuthSessionPayload.from_plaintext(plaintext)
        if session.state_ref != durable_state.state_ref or session.connector_id != durable_state.connector_id:
            raise ControlPlaneContractError(
                "google_oauth_state_mismatch",
                "sealed OAuth session does not match the consumed durable state",
            )
        if now >= session.expires_at:
            raise ControlPlaneContractError(
                "expired_google_oauth_state",
                "Google OAuth authorization state has expired",
            )
        if provider_error is not None:
            _bounded_secret(provider_error, "provider_error", max_chars=MAX_PROVIDER_ERROR_CHARS)
            raise ControlPlaneContractError(
                "google_oauth_authorization_denied",
                "Google OAuth authorization was not granted",
            )
        code = _bounded_secret(
            authorization_code if authorization_code is not None else "",
            "authorization_code",
            max_chars=MAX_AUTHORIZATION_CODE_CHARS,
        )
        payload = await self._token_exchange.exchange_authorization_code(
            config=self._config,
            code=code,
            code_verifier=session.code_verifier,
            redirect_uri=session.redirect_uri,
        )
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        token_type = payload.get("token_type")
        scopes_raw = payload.get("scope")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ControlPlaneContractError(
                "google_oauth_token_exchange_failed",
                "Google OAuth token response lacks access token proof",
            )
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise ControlPlaneContractError(
                "google_oauth_token_exchange_failed",
                "Google OAuth token response lacks refresh token",
            )
        if not isinstance(token_type, str) or token_type.casefold() != "bearer":
            raise ControlPlaneContractError(
                "google_oauth_token_exchange_failed",
                "Google OAuth token response has unsupported token type",
            )
        if not isinstance(scopes_raw, str) or set(scopes_raw.split()) != set(session.scopes):
            raise ControlPlaneContractError(
                "google_oauth_scope_mismatch",
                "Google OAuth granted scopes differ from the reviewed request",
            )
        refresh_expires_in = payload.get("refresh_token_expires_in")
        expires_at = None
        if refresh_expires_in is not None:
            if (
                isinstance(refresh_expires_in, bool)
                or not isinstance(refresh_expires_in, int)
                or not 1 <= refresh_expires_in <= MAX_REFRESH_TOKEN_LIFETIME_SECONDS
            ):
                raise ControlPlaneContractError(
                    "google_oauth_token_exchange_failed",
                    "Google OAuth refresh token expiry is invalid",
                )
            expires_at = now + timedelta(seconds=refresh_expires_in)

        binding_ref = _safe_ref(
            f"google-{session.connector_id}-{self._token(24, 'binding_token')}",
            "binding_ref",
        )
        sealed_refresh = await self._sealer.seal_text(
            plaintext=refresh_token.strip(),
            context=self._credential_context(
                binding_ref=binding_ref,
                connector_id=session.connector_id,
                actor_ref=session.actor_ref,
                account_ref=session.account_ref,
                workspace_ref=session.workspace_ref,
            ),
        )
        record = DurableGoogleOAuthCredential(
            binding_ref=binding_ref,
            connector_id=session.connector_id,
            actor_ref=session.actor_ref,
            account_ref=session.account_ref,
            workspace_ref=session.workspace_ref,
            scopes=session.scopes,
            sealed_refresh_token=sealed_refresh,
            issued_at=now,
            expires_at=expires_at,
        )
        self._store.save_credential(record)
        # access_token intentionally falls out of scope without persistence.
        return GoogleOAuthConnectedReceipt(
            binding_ref=binding_ref,
            connector_id=session.connector_id,
            actor_ref=session.actor_ref,
            account_ref=session.account_ref,
            workspace_ref=session.workspace_ref,
            scopes=session.scopes,
            connected_at=now,
            expires_at=expires_at,
        )

    def safe_dict(self) -> dict[str, Any]:
        token_safe = getattr(self._token_exchange, "safe_dict", None)
        return {
            "trusted_connect_ticket_required": True,
            "connect_ticket_body_only": True,
            "state_pkce_server_generated": True,
            "authorization_session_sealed": True,
            "callback_state_single_use": True,
            "provider_denial_consumes_state": True,
            "token_exchange_failure_consumes_state": True,
            "refresh_token_persisted_sealed": True,
            "access_token_persisted": False,
            "google_write_scope": False,
            "raw_connect_ticket_persisted": False,
            "raw_authorization_code_persisted": False,
            "raw_refresh_token_public": False,
            "raw_client_secret_public": False,
            "token_exchange": token_safe() if callable(token_safe) else {"test_port": True},
            "production_deployment": False,
            "production_ready": False,
        }


GOOGLE_OAUTH_INGRESS_RUNTIME_SOURCE_READY = True
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
CONNECT_TICKET_QUERY_PARAMETER = False
AUTHORIZATION_CODE_PERSISTED = False
ACCESS_TOKEN_PERSISTED = False
GOOGLE_WRITE_SCOPE = False
PUBLIC_HOSTNAME_CONFIGURED = False
PRODUCTION_MUTATION = False
