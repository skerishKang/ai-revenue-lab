from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
import secrets
from typing import Any, Callable

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.connector_connect_ticket import (
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    ConnectorConnectTicketAuthority,
)
from padiem_control_plane.contracts import ControlPlaneContractError, SubjectType


ALLOWED_PRODUCT_ID = "b62"
CONNECT_TICKET_TTL_SECONDS = 180
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_REVIEWED_CONNECTORS: dict[str, tuple[str, ...]] = {
    "gmail": (GMAIL_READONLY_SCOPE,),
    "google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),
}


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_connector_context",
            f"{field_name} must be timezone-aware",
        )
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ControlPlaneContractError(
            "connector_context_storage_error",
            f"{field_name} is invalid",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneContractError(
            "connector_context_storage_error",
            f"{field_name} is invalid",
        ) from exc
    return _utc(parsed, field_name)


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_connector_context",
            f"{field_name} must be a bounded safe reference",
        )
    return value


def decode_connect_ticket_key(secret_b64url: str) -> bytes:
    """Decode the shared issuer/verifier key without ever exposing it publicly."""

    if not isinstance(secret_b64url, str) or not _KEY_RE.fullmatch(secret_b64url):
        raise ControlPlaneContractError(
            "invalid_connect_ticket_authority",
            "Google connect ticket key must encode exactly 32 random bytes",
        )
    padding = "=" * (-len(secret_b64url) % 4)
    try:
        decoded = base64.b64decode(secret_b64url + padding, altchars=b"-_", validate=True)
    except (TypeError, ValueError) as exc:
        raise ControlPlaneContractError(
            "invalid_connect_ticket_authority",
            "Google connect ticket key is not valid base64url",
        ) from exc
    if len(decoded) != 32:
        raise ControlPlaneContractError(
            "invalid_connect_ticket_authority",
            "Google connect ticket key must decode to 256 bits",
        )
    return decoded


def _rows(cursor: Any) -> list[dict[str, Any]]:
    to_array = getattr(cursor, "toArray", None)
    if not callable(to_array):
        raise ControlPlaneContractError(
            "connector_context_storage_error",
            "connector context storage returned an invalid cursor",
        )
    raw = to_array()
    output: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            output.append(dict(item))
            continue
        to_py = getattr(item, "to_py", None)
        converted = to_py() if callable(to_py) else None
        if isinstance(converted, dict):
            output.append(dict(converted))
            continue
        try:
            output.append(dict(item))
        except (TypeError, ValueError) as exc:
            raise ControlPlaneContractError(
                "connector_context_storage_error",
                "connector context storage row is invalid",
            ) from exc
    return output


@dataclass(frozen=True, slots=True)
class CanonicalConnectorContext:
    product_id: str
    subject_id: str
    actor_ref: str
    account_ref: str
    workspace_ref: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.product_id != ALLOWED_PRODUCT_ID:
            raise ControlPlaneContractError(
                "connector_context_product_mismatch",
                "connector context belongs to another product",
            )
        if (
            not isinstance(self.subject_id, str)
            or not self.subject_id.strip()
            or len(self.subject_id) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in self.subject_id)
        ):
            raise ControlPlaneContractError(
                "invalid_connector_context",
                "subject_id must be a bounded canonical identifier",
            )
        for name in ("actor_ref", "account_ref", "workspace_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "subject_id": self.subject_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "created_at": _iso(self.created_at),
            "server_owned": True,
            "client_asserted": False,
        }


class CanonicalConnectorContextStore:
    """Control Plane-owned personal connector context for one canonical B62 user.

    The caller never supplies actor/account/workspace references. They are minted
    once by this authority and then reused for the canonical subject. This keeps
    connector binding identity out of browser and product-local authority.
    """

    def __init__(
        self,
        storage: Any,
        *,
        random_hex: Callable[[int], str] | None = None,
    ) -> None:
        sql = getattr(storage, "sql", None)
        transaction = getattr(storage, "transactionSync", None)
        if sql is None or not callable(getattr(sql, "exec", None)) or not callable(transaction):
            raise ValueError("SQLite Durable Object storage is required")
        self._storage = storage
        self._sql = sql
        self._random_hex = random_hex or secrets.token_hex
        self._initialize()

    def _initialize(self) -> None:
        self._sql.exec(
            "CREATE TABLE IF NOT EXISTS canonical_connector_context ("
            "product_id TEXT NOT NULL, subject_id TEXT NOT NULL, "
            "actor_ref TEXT NOT NULL UNIQUE, account_ref TEXT NOT NULL UNIQUE, "
            "workspace_ref TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, "
            "PRIMARY KEY(product_id, subject_id))"
        )

    def _new_ref(self, prefix: str, bytes_count: int = 16) -> str:
        token = self._random_hex(bytes_count)
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]+", token) or len(token) != bytes_count * 2:
            raise ControlPlaneContractError(
                "connector_context_random_source_invalid",
                "connector context random source returned invalid material",
            )
        return prefix + token

    @staticmethod
    def _validate_session(session: AuthSessionSnapshot, *, now: datetime) -> None:
        if not isinstance(session, AuthSessionSnapshot):
            raise ControlPlaneContractError(
                "invalid_connector_context",
                "canonical auth session is required",
            )
        if session.product_id != ALLOWED_PRODUCT_ID or session.subject.subject_type is not SubjectType.USER:
            raise ControlPlaneContractError(
                "connector_context_session_mismatch",
                "canonical auth session is outside the reviewed product boundary",
            )
        if session.effective_state(now=now) is not AuthSessionState.ACTIVE:
            raise ControlPlaneContractError(
                "inactive_auth_session",
                "connector context requires an active canonical auth session",
            )

    def resolve_or_create(
        self,
        *,
        auth_session: AuthSessionSnapshot,
        now: datetime,
    ) -> CanonicalConnectorContext:
        observed_at = _utc(now, "now")
        self._validate_session(auth_session, now=observed_at)
        subject_id = auth_session.subject.subject_id

        def operation() -> tuple[str, str, str, str]:
            rows = _rows(
                self._sql.exec(
                    "SELECT actor_ref, account_ref, workspace_ref, created_at "
                    "FROM canonical_connector_context WHERE product_id=? AND subject_id=?",
                    ALLOWED_PRODUCT_ID,
                    subject_id,
                )
            )
            if len(rows) > 1:
                raise ControlPlaneContractError(
                    "connector_context_storage_error",
                    "canonical connector context is ambiguous",
                )
            if rows:
                row = rows[0]
                return (
                    str(row["actor_ref"]),
                    str(row["account_ref"]),
                    str(row["workspace_ref"]),
                    str(row["created_at"]),
                )

            actor_ref = self._new_ref("actor_")
            account_ref = self._new_ref("account_")
            workspace_ref = self._new_ref("workspace_")
            created_at = _iso(observed_at)
            self._sql.exec(
                "INSERT INTO canonical_connector_context "
                "(product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ALLOWED_PRODUCT_ID,
                subject_id,
                actor_ref,
                account_ref,
                workspace_ref,
                created_at,
            )
            return actor_ref, account_ref, workspace_ref, created_at

        actor_ref, account_ref, workspace_ref, created_at = self._storage.transactionSync(operation)
        return CanonicalConnectorContext(
            product_id=ALLOWED_PRODUCT_ID,
            subject_id=subject_id,
            actor_ref=actor_ref,
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            created_at=_parse_iso(created_at, "created_at"),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "canonical_connector_context": True,
            "sqlite_durable_object": True,
            "server_owned_actor_account_workspace": True,
            "client_supplied_actor_account_workspace": False,
        }


@dataclass(frozen=True, slots=True)
class PrivateGoogleConnectTicketReceipt:
    connect_ticket: str = field(repr=False)
    connector_id: str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.connect_ticket, str) or not self.connect_ticket or len(self.connect_ticket) > 24_576:
            raise ControlPlaneContractError("invalid_connect_ticket", "issued connector ticket is invalid")
        if self.connector_id not in _REVIEWED_CONNECTORS:
            raise ControlPlaneContractError("unreviewed_connect_scope", "connector is not reviewed")
        object.__setattr__(self, "expires_at", _utc(self.expires_at, "expires_at"))

    def to_private_rpc_dict(self) -> dict[str, Any]:
        return {
            "connect_ticket": self.connect_ticket,
            "connector_id": self.connector_id,
            "expires_at": _iso(self.expires_at),
        }

    def safe_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "expires_at": _iso(self.expires_at),
            "raw_connect_ticket": False,
            "raw_signing_key": False,
        }


class GoogleConnectTicketIssuer:
    """Private Control Plane issuer bound to current canonical auth-session truth."""

    def __init__(
        self,
        *,
        context_store: CanonicalConnectorContextStore,
        signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        random_hex: Callable[[int], str] | None = None,
    ) -> None:
        if not isinstance(context_store, CanonicalConnectorContextStore):
            raise ValueError("context_store is required")
        self._context_store = context_store
        self._authority = ConnectorConnectTicketAuthority(signing_key=signing_key)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._random_hex = random_hex or secrets.token_hex

    def _ticket_id(self) -> str:
        value = self._random_hex(16)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ControlPlaneContractError(
                "invalid_connect_ticket",
                "ticket random source returned invalid material",
            )
        return "ct_" + value

    def issue(
        self,
        *,
        auth_session: AuthSessionSnapshot,
        connector_id: str,
    ) -> PrivateGoogleConnectTicketReceipt:
        now = _utc(self._clock(), "clock")
        scopes = _REVIEWED_CONNECTORS.get(connector_id)
        if scopes is None:
            raise ControlPlaneContractError(
                "unreviewed_connect_scope",
                "connector is not a reviewed Google readonly connector",
            )
        context = self._context_store.resolve_or_create(auth_session=auth_session, now=now)
        ticket = self._authority.issue(
            auth_session=auth_session,
            ticket_id=self._ticket_id(),
            connector_id=connector_id,
            actor_ref=context.actor_ref,
            account_ref=context.account_ref,
            workspace_ref=context.workspace_ref,
            scopes=scopes,
            now=now,
            ttl_seconds=CONNECT_TICKET_TTL_SECONDS,
        )
        return PrivateGoogleConnectTicketReceipt(
            connect_ticket=ticket,
            connector_id=connector_id,
            expires_at=now + timedelta(seconds=CONNECT_TICKET_TTL_SECONDS),
        )


CONTROL_PLANE_CONNECTOR_CONTEXT_AUTHORITY = True
CLIENT_ASSERTED_ACTOR_ACCOUNT_WORKSPACE = False
CONNECT_TICKET_ISSUER_PRIVATE = True
RAW_CONNECT_TICKET_PUBLIC = False
GOOGLE_WRITE_SCOPE = False
