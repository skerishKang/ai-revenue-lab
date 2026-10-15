"""Server-owned B66 Google Drive destination account contract.

B66 login identity and the Google Drive storage destination are independent.
This module owns only the account-facing state vocabulary and an in-memory seam
for owner-scoped connection status. It never accepts browser-owned owner or
credential authority and never exposes provider credentials.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Protocol


__all__ = [
    "B66DriveConnectedAccount",
    "B66DriveConnectionRecord",
    "B66DriveConnectionStatus",
    "B66DriveConnectionStore",
    "B66DriveDestinationAuthority",
    "B66DriveFreezeDurableGrantBackend",
    "B66_DRIVE_DURABLE_CREDENTIAL_BACKEND",
    "PROPERTY_LINKED_TO_B66_IDENTITY",
]


_B66_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$")
_GOOGLE_SUB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,255}$")
_B66_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_RECONNECT_REASONS = frozenset(
    {"revoked", "expired", "scope_changed", "invalid_grant", "manual_reconnect"}
)
_SECRET_FIELD_SUBSTRINGS = ("token", "secret", "bearer", "credential", "private")

# Step 2-A deliberately provides a memory seam only. A verified persistent,
# encrypted OAuth grant backend is not present in apps/padiem-chat for B66.
B66_DRIVE_DURABLE_CREDENTIAL_BACKEND = "ABSENT_NOT_PROVEN"
PROPERTY_LINKED_TO_B66_IDENTITY = False


class B66DriveConnectionStatus(str, Enum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


@dataclass(frozen=True)
class B66DriveConnectedAccount:
    """Verified Google destination details, safe to display to that owner only."""

    google_sub: str
    email: str | None = None

    def __post_init__(self) -> None:
        if _GOOGLE_SUB_RE.fullmatch(self.google_sub) is None:
            raise ValueError("invalid_google_sub")
        if self.email is not None and (
            not isinstance(self.email, str)
            or "@" not in self.email
            or len(self.email) > 320
        ):
            raise ValueError("invalid_google_email")

    @property
    def display_value(self) -> str:
        return self.email if self.email else self.google_sub


@dataclass(frozen=True)
class B66DriveConnectionRecord:
    """Owner-scoped connection state with no bearer or refresh token."""

    owner_b66_user_id: str
    drive_account: B66DriveConnectedAccount
    google_grant_reference: str
    scope: str = _B66_DRIVE_SCOPE
    account_storage_destination: str = "server-owned-grant-vault"
    connected_at: str | None = None
    status: B66DriveConnectionStatus = B66DriveConnectionStatus.CONNECTED
    reconnect_reason: str | None = None

    def __post_init__(self) -> None:
        if _B66_USER_ID_RE.fullmatch(self.owner_b66_user_id) is None:
            raise ValueError("invalid_owner_user_id")
        if not isinstance(self.google_grant_reference, str) or not self.google_grant_reference:
            raise ValueError("missing_grant_reference")
        if self.scope != _B66_DRIVE_SCOPE:
            raise ValueError("invalid_drive_scope")
        if self.status is B66DriveConnectionStatus.CONNECTED and self.reconnect_reason is not None:
            raise ValueError("inconsistent_connection_status")
        if (
            self.status is B66DriveConnectionStatus.RECONNECT_REQUIRED
            and self.reconnect_reason not in _RECONNECT_REASONS
        ):
            raise ValueError("invalid_reconnect_reason")
        if self.reconnect_reason is not None and self.reconnect_reason not in _RECONNECT_REASONS:
            raise ValueError("invalid_reconnect_reason")

    @property
    def status_value(self) -> str:
        return self.status.value

    def public_status(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "verified_store_owner": self.owner_b66_user_id,
            "destination_account": self.drive_account.display_value,
            "destination_sub": self.drive_account.google_sub,
            "scope": self.scope,
            "reconnect_reason": self.reconnect_reason,
            "connected_at": self.connected_at,
            "durable_credential_backend": B66_DRIVE_DURABLE_CREDENTIAL_BACKEND,
        }

    def hidden_internal_fields(self) -> set[str]:
        data = asdict(self)
        return {
            key
            for key in data
            if any(substr in key.lower() for substr in _SECRET_FIELD_SUBSTRINGS)
        }

    def __repr__(self) -> str:
        return (
            "B66DriveConnectionRecord("
            f"owner={self.owner_b66_user_id!r}, "
            f"destination_sub={self.drive_account.google_sub!r}, "
            f"status={self.status.value!r}, "
            "credential_reference=<redacted>)"
        )


class B66DriveConnectionStore(Protocol):
    """Owner-scoped storage contract. Implementation remains fail-closed here."""

    def load(self, owner_b66_user_id: str) -> B66DriveConnectionRecord | None: ...

    def save(self, record: B66DriveConnectionRecord) -> B66DriveConnectionRecord: ...

    def delete(self, owner_b66_user_id: str) -> None: ...


class B66DriveInMemoryConnectionStore:
    """Non-durable convenience holder for isolated contract tests and seams.

    It deliberately does not claim to survive logouts, browsers, or process restart.
    It stores no refresh token, bearer, or provider credential.
    """

    def __init__(self) -> None:
        self._records: dict[str, B66DriveConnectionRecord] = {}

    def __repr__(self) -> str:
        return "B66DriveInMemoryConnectionStore(non-durable)"

    def load(self, owner_b66_user_id: str) -> B66DriveConnectionRecord | None:
        owner = trusted_owner(owner_b66_user_id)
        return self._records.get(owner)

    def save(self, record: B66DriveConnectionRecord) -> B66DriveConnectionRecord:
        if not isinstance(record, B66DriveConnectionRecord):
            raise ValueError("invalid_connection_record")
        owner = trusted_owner(record.owner_b66_user_id)
        self._records[owner] = record
        return record

    def delete(self, owner_b66_user_id: str) -> None:
        ownership = trusted_owner(owner_b66_user_id)
        self._records.pop(ownership, None)

    def clear(self) -> None:
        self._records.clear()


class B66DriveFreezeDurableGrantBackend:
    """Consciously fail-closed placeholder while no verified real backend exists."""

    def __repr__(self) -> str:
        return "B66DriveFreezeDurableGrantBackend(unavailable)"

    def load(self, owner_b66_user_id: object) -> B66DriveConnectionRecord | None:
        trusted_owner(owner_b66_user_id)
        return None

    def save(self, record: B66DriveConnectionRecord) -> B66DriveConnectionRecord:
        raise RuntimeError(
            "B66 durable credential backend is absent/not proven in this step"
        )

    def delete(self, owner_b66_user_id: object) -> None:
        trusted_owner(owner_b66_user_id)


class B66DriveDestinationAuthority:
    """Smallest server-side state transition seam for an independent Drive destination."""

    def __init__(self, store: B66DriveConnectionStore | None = None) -> None:
        # Default runtime is explicitly unconfigured; only tests may inject
        # a non-durable memory store. No successful default connection claim.
        self._store = store if store is not None else B66DriveFreezeDurableGrantBackend()

    @property
    def durable_backend_proven(self) -> bool:
        # Neither this step's in-memory seam nor an arbitrary injected store
        # establishes verified encrypted, renewable OAuth grant durability.
        return False

    def load_connection(self, owner_b66_user_id: str) -> B66DriveConnectionRecord | None:
        owner = trusted_owner(owner_b66_user_id)
        return self._store.load(owner)

    def connect_destination(
        self,
        *,
        owner_b66_user_id: str,
        drive_account: B66DriveConnectedAccount,
        grant_reference: str,
        connected_at: str | None = None,
    ) -> B66DriveConnectionRecord:
        owner = trusted_owner(owner_b66_user_id)
        record = B66DriveConnectionRecord(
            owner_b66_user_id=owner,
            drive_account=drive_account,
            google_grant_reference=grant_reference,
            scope=_B66_DRIVE_SCOPE,
            connected_at=connected_at,
            status=B66DriveConnectionStatus.CONNECTED,
        )
        return self._store.save(record)

    def mark_reconnect_required(
        self,
        *,
        owner_b66_user_id: str,
        drive_account: B66DriveConnectedAccount,
        grant_reference: str,
        reason: str,
        connected_at: str | None = None,
    ) -> B66DriveConnectionRecord:
        if reason not in _RECONNECT_REASONS:
            raise ValueError("invalid_reconnect_reason")
        owner = trusted_owner(owner_b66_user_id)
        record = B66DriveConnectionRecord(
            owner_b66_user_id=owner,
            drive_account=drive_account,
            google_grant_reference=grant_reference,
            scope=_B66_DRIVE_SCOPE,
            connected_at=connected_at,
            status=B66DriveConnectionStatus.RECONNECT_REQUIRED,
            reconnect_reason=reason,
        )
        return self._store.save(record)

    def disconnect_destination(self, owner_b66_user_id: str) -> None:
        self._store.delete(trusted_owner(owner_b66_user_id))

    def public_status(self, owner_b66_user_id: str) -> dict[str, Any]:
        owner = trusted_owner(owner_b66_user_id)
        record = self.load_connection(owner)
        if record is None:
            return {
                "status": B66DriveConnectionStatus.NOT_CONNECTED.value,
                "verified_store_owner": owner,
                "destination_account": None,
                "destination_sub": None,
                "scope": _B66_DRIVE_SCOPE,
                "reconnect_reason": None,
                "connected_at": None,
                "durable_credential_backend": B66_DRIVE_DURABLE_CREDENTIAL_BACKEND,
            }
        return record.public_status()

def trusted_owner(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or _B66_USER_ID_RE.fullmatch(value) is None:
        raise ValueError("untrusted_b66_owner_id")
    return value


def connection_record_from_trusted_result(result: dict[str, Any]) -> B66DriveConnectionRecord:
    """Translate a verified owner-google identity into a display-only contract.

    This is the seam that a future encrypted authorization-code flow may use
    without granting browser-supplied credentials authority.
    """
    if not isinstance(result, Mapping):
        raise ValueError("invalid_trusted_result")
    allowed_result = {"owner_b66_user_id", "drive_account", "google_grant_reference", "connected_at"}
    if set(result) - allowed_result:
        raise ValueError("spoofed_trusted_result")
    owner = trusted_owner(result.get("owner_b66_user_id"))
    destination = result.get("drive_account")
    if not isinstance(destination, Mapping):
        raise ValueError("invalid_drive_account")
    # A verified Google sub is a necessary destination identity field, NOT
    # a browser authority. Reject all unexpected/token-like nested fields.
    if set(destination) - {"google_sub", "email"}:
        raise ValueError("spoofed_trusted_result")
    account = B66DriveConnectedAccount(
        google_sub=_required_str(destination.get("google_sub")),
        email=_optional_str(destination.get("email")),
    )
    grant_reference = _required_str(result.get("google_grant_reference"))
    return B66DriveConnectionRecord(
        owner_b66_user_id=owner,
        drive_account=account,
        google_grant_reference=grant_reference,
        scope=_B66_DRIVE_SCOPE,
        connected_at=_optional_str(result.get("connected_at")),
        status=B66DriveConnectionStatus.CONNECTED,
    )


def _required_str(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("required_string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid_string")
    value = value.strip()
    return value or None
