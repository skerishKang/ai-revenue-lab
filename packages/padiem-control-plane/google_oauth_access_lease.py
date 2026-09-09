from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Callable, Protocol
from urllib.parse import urlencode

from padiem_control_plane.contracts import ControlPlaneContractError

from google_oauth_durable_store import (
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
)
from google_oauth_ingress_runtime import (
    GOOGLE_TOKEN_URL,
    MAX_TOKEN_RESPONSE_BYTES,
    GoogleOAuthIngressConfig,
)
from google_oauth_webcrypto_sealer import (
    GoogleOAuthSealContext,
    GoogleOAuthSealPurpose,
    GoogleOAuthWebCryptoSealer,
)


MAX_ACCESS_TOKEN_LIFETIME_SECONDS = 7_200
MAX_ACCESS_TOKEN_CHARS = 131_072
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_REVIEWED_SCOPES: dict[str, tuple[str, ...]] = {
    "gmail": (GMAIL_READONLY_SCOPE,),
    "google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),
}


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_REF_RE.fullmatch(value) is None:
        raise ControlPlaneContractError(
            "invalid_google_oauth_access_lease",
            f"{field_name} must be a bounded safe reference",
        )
    return value


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_google_oauth_access_lease",
            f"{field_name} must be timezone-aware",
        )
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class GoogleOAuthAccessLease:
    access_token: str = field(repr=False)
    binding_ref: str = ""
    connector_id: str = ""
    actor_ref: str = ""
    account_ref: str = ""
    workspace_ref: str = ""
    scopes: tuple[str, ...] = ()
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if (
            not isinstance(self.access_token, str)
            or not self.access_token.strip()
            or len(self.access_token) > MAX_ACCESS_TOKEN_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in self.access_token)
        ):
            raise ControlPlaneContractError(
                "invalid_google_oauth_access_lease",
                "access token is invalid",
            )
        object.__setattr__(self, "access_token", self.access_token.strip())
        for name in ("binding_ref", "connector_id", "actor_ref", "account_ref", "workspace_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        expected = _REVIEWED_SCOPES.get(self.connector_id)
        if expected is None or tuple(self.scopes) != expected:
            raise ControlPlaneContractError(
                "google_oauth_scope_mismatch",
                "access lease scopes do not match the reviewed connector",
            )
        object.__setattr__(self, "scopes", expected)
        object.__setattr__(self, "expires_at", _utc(self.expires_at, "expires_at"))

    def to_private_rpc_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "binding_ref": self.binding_ref,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "scopes": list(self.scopes),
            "expires_at": _iso(self.expires_at),
        }

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "scopes": list(self.scopes),
            "expires_at": _iso(self.expires_at),
            "access_token_present": True,
            "raw_access_token": False,
            "raw_refresh_token": False,
            "raw_client_secret": False,
        }


class GoogleOAuthRefreshPort(Protocol):
    async def refresh_access_token(
        self,
        *,
        config: GoogleOAuthIngressConfig,
        refresh_token: str,
    ) -> dict[str, Any]: ...


class CloudflareGoogleOAuthRefreshPort:
    """Worker-native refresh-token grant. Raw refresh material stays in CP."""

    async def refresh_access_token(
        self,
        *,
        config: GoogleOAuthIngressConfig,
        refresh_token: str,
    ) -> dict[str, Any]:
        from workers import fetch  # type: ignore[import-not-found]

        form = urlencode(
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
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
                "google_oauth_refresh_failed",
                "Google OAuth access-token refresh failed",
            )
        text = await response.text()
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TOKEN_RESPONSE_BYTES:
            raise ControlPlaneContractError(
                "google_oauth_refresh_failed",
                "Google OAuth refresh response exceeds the trusted bound",
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ControlPlaneContractError(
                "google_oauth_refresh_failed",
                "Google OAuth refresh response is invalid",
            ) from exc
        if not isinstance(payload, dict):
            raise ControlPlaneContractError(
                "google_oauth_refresh_failed",
                "Google OAuth refresh response must be an object",
            )
        return payload

    def safe_dict(self) -> dict[str, Any]:
        return {
            "cloudflare_worker_fetch": True,
            "token_endpoint": GOOGLE_TOKEN_URL,
            "grant_type": "refresh_token",
            "form_urlencoded": True,
            "raw_refresh_token_public": False,
            "raw_client_secret_public": False,
            "raw_access_token_public": False,
        }


class GoogleOAuthAccessLeaseRuntime:
    """CP-owned exchange from sealed refresh credential to short-lived lease."""

    def __init__(
        self,
        *,
        store: CloudflareDurableGoogleOAuthStore,
        sealer: GoogleOAuthWebCryptoSealer,
        config: GoogleOAuthIngressConfig,
        refresh_port: GoogleOAuthRefreshPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._sealer = sealer
        self._config = config
        self._refresh_port = refresh_port
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return _utc(self._clock(), "clock")

    async def issue(self, *, binding_ref: str, connector_id: str) -> GoogleOAuthAccessLease:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        connector_id = _safe_ref(connector_id, "connector_id")
        expected = _REVIEWED_SCOPES.get(connector_id)
        if expected is None:
            raise ControlPlaneContractError(
                "unreviewed_google_oauth_scope",
                "connector is not a reviewed Google readonly connector",
            )
        now = self._now()
        record = self._store.load_active_credential(binding_ref=binding_ref, now=now)
        if record.connector_id != connector_id or tuple(record.scopes) != expected:
            raise ControlPlaneContractError(
                "google_oauth_scope_mismatch",
                "canonical Google credential does not match the requested connector",
            )
        context = GoogleOAuthSealContext(
            purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
            connector_id=record.connector_id,
            record_ref=record.binding_ref,
            actor_ref=record.actor_ref,
            account_ref=record.account_ref,
            workspace_ref=record.workspace_ref,
        )
        refresh_token = await self._sealer.unseal_text(
            envelope=record.sealed_refresh_token,
            context=context,
        )
        try:
            payload = await self._refresh_port.refresh_access_token(
                config=self._config,
                refresh_token=refresh_token,
            )
        finally:
            # Python cannot guarantee string zeroization, but the plaintext is
            # kept in this local frame only and is never persisted or returned.
            refresh_token = ""

        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ControlPlaneContractError(
                "google_oauth_refresh_failed",
                "Google OAuth refresh response lacks an access token",
            )
        if not isinstance(token_type, str) or token_type.casefold() != "bearer":
            raise ControlPlaneContractError(
                "google_oauth_refresh_failed",
                "Google OAuth refresh response has unsupported token type",
            )
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or not 1 <= expires_in <= MAX_ACCESS_TOKEN_LIFETIME_SECONDS
        ):
            raise ControlPlaneContractError(
                "google_oauth_refresh_failed",
                "Google OAuth access-token expiry is invalid",
            )
        scopes_raw = payload.get("scope")
        if scopes_raw is not None and (
            not isinstance(scopes_raw, str) or set(scopes_raw.split()) != set(expected)
        ):
            raise ControlPlaneContractError(
                "google_oauth_scope_mismatch",
                "Google OAuth refreshed scopes differ from the canonical binding",
            )
        return GoogleOAuthAccessLease(
            access_token=access_token,
            binding_ref=record.binding_ref,
            connector_id=record.connector_id,
            actor_ref=record.actor_ref,
            account_ref=record.account_ref,
            workspace_ref=record.workspace_ref,
            scopes=expected,
            expires_at=now + timedelta(seconds=expires_in),
        )

    def safe_dict(self) -> dict[str, Any]:
        refresh_safe = getattr(self._refresh_port, "safe_dict", None)
        return {
            "canonical_binding_required": True,
            "refresh_token_unsealed_inside_control_plane": True,
            "refresh_token_returned": False,
            "access_token_persisted": False,
            "private_rpc_only": True,
            "google_write_scope": False,
            "refresh_port": refresh_safe() if callable(refresh_safe) else {"test_port": True},
        }


RAW_REFRESH_TOKEN_TO_ENGINE = False
ACCESS_TOKEN_PERSISTED = False
GOOGLE_WRITE_SCOPE = False
PRIVATE_ACCESS_LEASE_SOURCE_READY = True
