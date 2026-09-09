from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable

from padiem_ai_core.drive_capability import DRIVE_READONLY_SCOPE

from app.service import ServiceContractError


MAX_ACCESS_TOKEN_CHARS = 131_072
MAX_ACCESS_LEASE_SECONDS = 7_200
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_LEASE_KEYS = frozenset(
    {
        "access_token",
        "binding_ref",
        "connector_id",
        "actor_ref",
        "account_ref",
        "workspace_ref",
        "scopes",
        "expires_at",
    }
)


def _unavailable(message: str) -> ServiceContractError:
    return ServiceContractError(
        "google_oauth_access_lease_unavailable",
        message,
        status_code=503,
    )


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_REF_RE.fullmatch(value) is None:
        raise _unavailable(f"Control Plane access lease {field_name} is invalid.")
    return value


def _expires_at(value: Any, *, now: datetime) -> datetime:
    if not isinstance(value, str) or not value:
        raise _unavailable("Control Plane access lease expiry is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _unavailable("Control Plane access lease expiry is invalid.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _unavailable("Control Plane access lease expiry is invalid.")
    parsed = parsed.astimezone(timezone.utc)
    if not now < parsed <= now + timedelta(seconds=MAX_ACCESS_LEASE_SECONDS):
        raise _unavailable("Control Plane access lease is expired or exceeds the trusted lifetime.")
    return parsed


@dataclass(frozen=True, slots=True)
class EngineGoogleOAuthAccessLease:
    access_token: str = field(repr=False)
    binding_ref: str = ""
    connector_id: str = ""
    actor_ref: str = ""
    account_ref: str = ""
    workspace_ref: str = ""
    scopes: tuple[str, ...] = ()
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "access_token_present": True,
            "raw_access_token": False,
            "raw_refresh_token": False,
        }


class CloudflareControlPlaneGoogleOAuthAccessLeaseClient:
    """Engine adapter over the private padiem-google-oauth-state Service Binding."""

    def __init__(
        self,
        binding: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if binding is None:
            raise ValueError("Control Plane Google OAuth Service Binding is required")
        self._binding = binding
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def issue_access_lease(
        self,
        *,
        binding_ref: str,
        connector_id: str,
    ) -> EngineGoogleOAuthAccessLease:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        connector_id = _safe_ref(connector_id, "connector_id")
        if connector_id != "google-drive":
            raise _unavailable("Only the reviewed Google Drive connector is accepted by this client.")

        method = getattr(self._binding, "issue_access_lease", None)
        if not callable(method):
            raise _unavailable("Control Plane Google OAuth access-lease RPC is unavailable.")
        try:
            result = await method(
                {"binding_ref": binding_ref, "connector_id": connector_id}
            )
        except ServiceContractError:
            raise
        except Exception:
            raise _unavailable("Control Plane Google OAuth access-lease RPC failed.") from None

        if not isinstance(result, Mapping):
            raise _unavailable("Control Plane Google OAuth access-lease RPC returned invalid data.")
        if result.get("ok") is not True:
            raise _unavailable("Control Plane Google OAuth access lease was rejected.")
        lease = result.get("lease")
        if not isinstance(lease, Mapping) or frozenset(lease.keys()) != _LEASE_KEYS:
            raise _unavailable("Control Plane Google OAuth access lease schema is invalid.")

        access_token = lease.get("access_token")
        if (
            not isinstance(access_token, str)
            or not access_token.strip()
            or len(access_token) > MAX_ACCESS_TOKEN_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in access_token)
        ):
            raise _unavailable("Control Plane Google OAuth access token is invalid.")

        lease_binding_ref = _safe_ref(lease.get("binding_ref"), "binding_ref")
        lease_connector_id = _safe_ref(lease.get("connector_id"), "connector_id")
        if lease_binding_ref != binding_ref or lease_connector_id != connector_id:
            raise _unavailable("Control Plane Google OAuth access lease does not match the requested binding.")

        scopes = lease.get("scopes")
        if not isinstance(scopes, list) or scopes != [DRIVE_READONLY_SCOPE]:
            raise _unavailable("Control Plane Google OAuth access lease scope is invalid.")

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("access lease client clock must be timezone-aware")
        now = now.astimezone(timezone.utc)

        return EngineGoogleOAuthAccessLease(
            access_token=access_token.strip(),
            binding_ref=lease_binding_ref,
            connector_id=lease_connector_id,
            actor_ref=_safe_ref(lease.get("actor_ref"), "actor_ref"),
            account_ref=_safe_ref(lease.get("account_ref"), "account_ref"),
            workspace_ref=_safe_ref(lease.get("workspace_ref"), "workspace_ref"),
            scopes=(DRIVE_READONLY_SCOPE,),
            expires_at=_expires_at(lease.get("expires_at"), now=now),
        )


RAW_REFRESH_TOKEN_ACCEPTED = False
ACCESS_TOKEN_PERSISTED = False
PUBLIC_TOKEN_PROJECTION = False
