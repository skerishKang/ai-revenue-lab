from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Callable, TypeVar

from padiem_control_plane.contracts import ControlPlaneContractError

_T = TypeVar("_T")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_SEALED_ENVELOPE_RE = re.compile(r"^sealed:v1:[A-Za-z0-9_-]{16,262120}$")
MAX_SEALED_BLOB_CHARS = 262_144
MAX_AUTHORIZATION_STATE_TTL_SECONDS = 600
MAX_CONNECT_TICKET_RESIDUAL_LIFETIME_SECONDS = 330

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
# #2010: the Control Plane owns the long-lived Google refresh credential and
# issues short-lived read leases. Calendar joins the same reviewed OAuth
# authority with exactly one readonly scope.
GOOGLE_CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
# Internal OAuth-reviewed authority set. It is deliberately WIDER than the
# public/default workspace-status projection: a connector may be a reviewed
# OAuth authority without being part of the authorized #2830 B-0 surface.
_OAUTH_REVIEWED_SCOPES: dict[str, tuple[str, ...]] = {
    "gmail": (GMAIL_READONLY_SCOPE,),
    "google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),
    "google-calendar": (GOOGLE_CALENDAR_READONLY_SCOPE,),
}
# Backwards-compatible module-level map used by the Control Plane modules.
_REVIEWED_SCOPES = _OAUTH_REVIEWED_SCOPES
OAUTH_REVIEWED_CONNECTORS = tuple(sorted(_REVIEWED_SCOPES))

_TICKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS google_oauth_connect_ticket_use (
    ticket_id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    ticket_expires_at TEXT NOT NULL
)
"""

_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS google_oauth_authorization_state (
    state_ref TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL UNIQUE,
    connector_id TEXT NOT NULL,
    sealed_session TEXT NOT NULL CHECK (length(sealed_session) > 0),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
"""

_CREDENTIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS google_oauth_refresh_credential (
    binding_ref TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    actor_ref TEXT NOT NULL,
    account_ref TEXT NOT NULL,
    workspace_ref TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    sealed_refresh_token TEXT NOT NULL CHECK (length(sealed_refresh_token) > 0),
    issued_at TEXT NOT NULL,
    expires_at TEXT NULL,
    revoked_at TEXT NULL
)
"""


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_google_oauth_durable_record",
            f"{field_name} must be a bounded safe reference",
        )
    return value


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_google_oauth_durable_record",
            f"{field_name} must be timezone-aware",
        )
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ControlPlaneContractError(
            "invalid_google_oauth_durable_record",
            f"{field_name} must be ISO-8601 text",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneContractError(
            "invalid_google_oauth_durable_record",
            f"{field_name} must be valid ISO-8601 text",
        ) from exc
    return _utc(parsed, field_name)


def _sealed(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_SEALED_BLOB_CHARS
        or _SEALED_ENVELOPE_RE.fullmatch(value) is None
    ):
        raise ControlPlaneContractError(
            "invalid_google_oauth_durable_record",
            f"{field_name} must use the bounded sealed:v1 envelope",
        )
    return value


def _reviewed_scopes(connector_id: str, value: Any) -> tuple[str, ...]:
    connector_id = _safe_ref(connector_id, "connector_id")
    if not isinstance(value, tuple) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ControlPlaneContractError(
            "invalid_google_oauth_durable_record",
            "scopes must be a non-empty tuple",
        )
    if len(set(value)) != len(value):
        raise ControlPlaneContractError(
            "invalid_google_oauth_durable_record",
            "scopes must be unique",
        )
    expected = _REVIEWED_SCOPES.get(connector_id)
    if expected is None or set(value) != set(expected):
        raise ControlPlaneContractError(
            "unreviewed_google_oauth_scope",
            "durable Google OAuth scopes must exactly match the reviewed readonly set",
        )
    return expected


def _row_value(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row[name]
    return getattr(row, name)


def _rows(cursor: Any) -> list[Any]:
    to_array = getattr(cursor, "toArray", None)
    if not callable(to_array):
        raise RuntimeError("Durable Object SQL cursor must expose toArray")
    return list(to_array())


def _rows_written(cursor: Any) -> int:
    _rows(cursor)
    value = getattr(cursor, "rowsWritten", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or value < 0:
        raise RuntimeError("Durable Object SQL returned invalid rowsWritten")
    return int(value)


@dataclass(frozen=True, slots=True)
class DurableGoogleOAuthAuthorizationState:
    state_ref: str
    ticket_id: str
    connector_id: str
    sealed_session: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in ("state_ref", "ticket_id", "connector_id"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        if self.connector_id not in _REVIEWED_SCOPES:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "connector_id is not a reviewed Google readonly connector",
            )
        object.__setattr__(self, "sealed_session", _sealed(self.sealed_session, "sealed_session"))
        created_at = _utc(self.created_at, "created_at")
        expires_at = _utc(self.expires_at, "expires_at")
        if not created_at < expires_at <= created_at + timedelta(seconds=MAX_AUTHORIZATION_STATE_TTL_SECONDS):
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "authorization state expiry exceeds the trusted bound",
            )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "expires_at", expires_at)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "state_ref": self.state_ref,
            "ticket_id": self.ticket_id,
            "connector_id": self.connector_id,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "sealed_session_present": True,
            "raw_session": False,
            "raw_pkce_verifier": False,
            "raw_connect_ticket": False,
        }


@dataclass(frozen=True, slots=True)
class DurableGoogleOAuthCredential:
    binding_ref: str
    connector_id: str
    actor_ref: str
    account_ref: str
    workspace_ref: str
    scopes: tuple[str, ...]
    sealed_refresh_token: str
    issued_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("binding_ref", "connector_id", "actor_ref", "account_ref", "workspace_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        object.__setattr__(self, "scopes", _reviewed_scopes(self.connector_id, self.scopes))
        object.__setattr__(
            self,
            "sealed_refresh_token",
            _sealed(self.sealed_refresh_token, "sealed_refresh_token"),
        )
        issued_at = _utc(self.issued_at, "issued_at")
        expires_at = _utc(self.expires_at, "expires_at") if self.expires_at is not None else None
        revoked_at = _utc(self.revoked_at, "revoked_at") if self.revoked_at is not None else None
        if expires_at is not None and expires_at <= issued_at:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "credential expiry must be after issue time",
            )
        if revoked_at is not None and revoked_at < issued_at:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "credential revocation cannot predate issue time",
            )
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "revoked_at", revoked_at)

    def usable_at(self, now: datetime) -> bool:
        now = _utc(now, "now")
        return self.revoked_at is None and (self.expires_at is None or now < self.expires_at)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "scopes": list(self.scopes),
            "issued_at": _iso(self.issued_at),
            "expires_at": _iso(self.expires_at) if self.expires_at is not None else None,
            "revoked_at": _iso(self.revoked_at) if self.revoked_at is not None else None,
            "sealed_refresh_token_present": True,
            "raw_refresh_token": False,
            "raw_access_token": False,
            "raw_client_secret": False,
        }


@dataclass(frozen=True, slots=True)
class GoogleOAuthWorkspaceConnectorState:
    """Bounded, identity-free connector truth for one workspace + connector.

    This projection is the *only* shape the workspace-status read path may
    return. It is deliberately narrower than ``DurableGoogleOAuthCredential``:
    the durable credential carries ``binding_ref`` / ``actor_ref`` /
    ``account_ref`` / ``workspace_ref`` / ``scopes`` / ``sealed_refresh_token``,
    none of which may cross the workspace-status boundary. Only the connector
    id, a tri-state usability verdict, whether an expiry is present, and the
    duplicate-binding ambiguity flag are exposed.

    ``state`` is tri-state on purpose:

    * ``"connected"`` — exactly one usable row (not revoked, not expired)
    * ``"not_connected"`` — zero usable rows
    * ``"ambiguous"`` — more than one usable row for the same workspace and
      connector (see ``AMBIGUOUS`` handling below)

    The schema has no ``UNIQUE(workspace_ref, connector_id)`` constraint, so
    "multiple usable rows" is a reachable state. Picking a winner would be
    latest-wins/first-row-wins identity fabrication, so the read fails closed
    into ``ambiguous`` and the caller must treat the connector as unusable.
    """

    connector_id: str
    state: str
    expires_present: bool
    ambiguous: bool = False

    _STATES = ("connected", "not_connected", "ambiguous")

    def __post_init__(self) -> None:
        object.__setattr__(self, "connector_id", _safe_ref(self.connector_id, "connector_id"))
        if self.connector_id not in _REVIEWED_SCOPES:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "connector_id is not a reviewed Google readonly connector",
            )
        if self.state not in self._STATES:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "workspace connector state must be connected, not_connected or ambiguous",
            )
        if not isinstance(self.expires_present, bool) or not isinstance(self.ambiguous, bool):
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "workspace connector state flags must be strict booleans",
            )
        if self.state == "ambiguous" and not self.ambiguous:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "ambiguous workspace connector state must set the ambiguity flag",
            )
        if self.state != "ambiguous" and self.ambiguous:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "only ambiguous workspace connector state may set the ambiguity flag",
            )

    @property
    def usable(self) -> bool:
        return self.state == "connected"

    def to_bounded_dict(self) -> dict[str, Any]:
        """Return the reviewed public projection; never widens to raw identity."""
        return {
            "connector_id": self.connector_id,
            "state": self.state,
            "usable": self.usable,
            "expires_present": self.expires_present,
            "ambiguous": self.ambiguous,
        }


def workspace_connector_state(
    *,
    connector_id: str,
    usable_rows: int,
    expires_present: bool,
) -> GoogleOAuthWorkspaceConnectorState:
    """Map a usable-row count to the tri-state workspace connector verdict.

    Single source of truth for the duplicate-active-binding rule, so the
    store, the private RPC and the tests cannot drift apart.
    """
    if usable_rows < 0:
        raise RuntimeError("usable_rows cannot be negative")
    if usable_rows == 0:
        return GoogleOAuthWorkspaceConnectorState(
            connector_id=connector_id,
            state="not_connected",
            expires_present=False,
        )
    if usable_rows == 1:
        return GoogleOAuthWorkspaceConnectorState(
            connector_id=connector_id,
            state="connected",
            expires_present=bool(expires_present),
        )
    return GoogleOAuthWorkspaceConnectorState(
        connector_id=connector_id,
        state="ambiguous",
        expires_present=bool(expires_present),
        ambiguous=True,
    )


class CloudflareDurableGoogleOAuthStore:
    """SQLite-backed Durable Object state for the future Google OAuth ingress.

    The adapter accepts only the canonical ``sealed:v1:<base64url>`` envelope.
    Cryptography is intentionally outside this module; the future Worker-native
    WebCrypto sealer must produce that envelope before persistence.
    """

    durable = True

    def __init__(self, storage: Any) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise ValueError("SQLite-backed Durable Object storage is required")
        transaction_sync = getattr(storage, "transactionSync", None)
        if not callable(transaction_sync):
            raise ValueError("SQLite-backed Durable Object transactionSync is required")
        self._storage = storage
        self._sql = sql
        self._transaction_sync = transaction_sync
        self._sql.exec(_TICKET_SCHEMA)
        self._sql.exec(_STATE_SCHEMA)
        self._sql.exec(_CREDENTIAL_SCHEMA)

    def transaction(self, operation: Callable[[], _T]) -> _T:
        return self._transaction_sync(operation)

    def begin_authorization(
        self,
        *,
        ticket_id: str,
        connector_id: str,
        ticket_expires_at: datetime,
        state: DurableGoogleOAuthAuthorizationState,
        now: datetime,
    ) -> DurableGoogleOAuthAuthorizationState:
        ticket_id = _safe_ref(ticket_id, "ticket_id")
        connector_id = _safe_ref(connector_id, "connector_id")
        if connector_id not in _REVIEWED_SCOPES:
            raise ControlPlaneContractError(
                "invalid_google_oauth_durable_record",
                "connector_id is not a reviewed Google readonly connector",
            )
        now = _utc(now, "now")
        ticket_expires_at = _utc(ticket_expires_at, "ticket_expires_at")
        if now >= ticket_expires_at:
            raise ControlPlaneContractError("expired_connect_ticket", "connector ticket has expired")
        if ticket_expires_at > now + timedelta(seconds=MAX_CONNECT_TICKET_RESIDUAL_LIFETIME_SECONDS):
            raise ControlPlaneContractError(
                "invalid_connect_ticket",
                "connector ticket residual lifetime exceeds the trusted bound",
            )
        if not isinstance(state, DurableGoogleOAuthAuthorizationState):
            raise ValueError("state must be DurableGoogleOAuthAuthorizationState")
        if state.ticket_id != ticket_id or state.connector_id != connector_id:
            raise ControlPlaneContractError(
                "google_oauth_state_mismatch",
                "authorization state does not match the consumed connector ticket",
            )
        if now < state.created_at - timedelta(seconds=30) or now >= state.expires_at:
            raise ControlPlaneContractError(
                "invalid_google_oauth_authorization_state",
                "authorization state is not currently usable",
            )

        def operation() -> DurableGoogleOAuthAuthorizationState:
            ticket_cursor = self._sql.exec(
                "INSERT OR IGNORE INTO google_oauth_connect_ticket_use "
                "(ticket_id, connector_id, consumed_at, ticket_expires_at) VALUES (?, ?, ?, ?)",
                ticket_id,
                connector_id,
                _iso(now),
                _iso(ticket_expires_at),
            )
            if _rows_written(ticket_cursor) != 1:
                raise ControlPlaneContractError(
                    "replayed_connect_ticket",
                    "connector connect ticket was already consumed",
                )
            state_cursor = self._sql.exec(
                "INSERT OR IGNORE INTO google_oauth_authorization_state "
                "(state_ref, ticket_id, connector_id, sealed_session, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                state.state_ref,
                state.ticket_id,
                state.connector_id,
                state.sealed_session,
                _iso(state.created_at),
                _iso(state.expires_at),
            )
            if _rows_written(state_cursor) != 1:
                raise ControlPlaneContractError(
                    "duplicate_google_oauth_state",
                    "authorization state reference already exists",
                )
            return state

        return self.transaction(operation)

    def consume_authorization_state(
        self,
        *,
        state_ref: str,
        now: datetime,
    ) -> DurableGoogleOAuthAuthorizationState:
        state_ref = _safe_ref(state_ref, "state_ref")
        now = _utc(now, "now")

        def operation() -> DurableGoogleOAuthAuthorizationState:
            found = _rows(
                self._sql.exec(
                    "SELECT state_ref, ticket_id, connector_id, sealed_session, created_at, expires_at "
                    "FROM google_oauth_authorization_state WHERE state_ref = ?",
                    state_ref,
                )
            )
            if len(found) != 1:
                raise ControlPlaneContractError(
                    "missing_google_oauth_state",
                    "authorization state is missing or already consumed",
                )
            row = found[0]
            state = DurableGoogleOAuthAuthorizationState(
                state_ref=_row_value(row, "state_ref"),
                ticket_id=_row_value(row, "ticket_id"),
                connector_id=_row_value(row, "connector_id"),
                sealed_session=_row_value(row, "sealed_session"),
                created_at=_parse_iso(_row_value(row, "created_at"), "created_at"),
                expires_at=_parse_iso(_row_value(row, "expires_at"), "expires_at"),
            )
            deleted = self._sql.exec(
                "DELETE FROM google_oauth_authorization_state WHERE state_ref = ?",
                state_ref,
            )
            if _rows_written(deleted) != 1:
                raise RuntimeError("authorization state disappeared during atomic consume")
            return state

        # The delete must commit even when the state is expired. Raising inside
        # transactionSync would roll the delete back and make an expired state
        # replayable. Expiry is therefore checked only after successful commit.
        state = self.transaction(operation)
        if now >= state.expires_at:
            raise ControlPlaneContractError(
                "expired_google_oauth_state",
                "authorization state has expired and was permanently consumed",
            )
        return state

    def save_credential(self, record: DurableGoogleOAuthCredential) -> None:
        if not isinstance(record, DurableGoogleOAuthCredential):
            raise ValueError("record must be DurableGoogleOAuthCredential")
        cursor = self._sql.exec(
            "INSERT OR IGNORE INTO google_oauth_refresh_credential "
            "(binding_ref, connector_id, actor_ref, account_ref, workspace_ref, scopes_json, "
            "sealed_refresh_token, issued_at, expires_at, revoked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            record.binding_ref,
            record.connector_id,
            record.actor_ref,
            record.account_ref,
            record.workspace_ref,
            json.dumps(list(record.scopes), separators=(",", ":"), ensure_ascii=True),
            record.sealed_refresh_token,
            _iso(record.issued_at),
            _iso(record.expires_at) if record.expires_at is not None else None,
            _iso(record.revoked_at) if record.revoked_at is not None else None,
        )
        if _rows_written(cursor) != 1:
            raise ControlPlaneContractError(
                "duplicate_google_oauth_binding",
                "Google OAuth credential binding already exists",
            )

    def load_active_credential(
        self,
        *,
        binding_ref: str,
        now: datetime,
    ) -> DurableGoogleOAuthCredential:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        now = _utc(now, "now")
        found = _rows(
            self._sql.exec(
                "SELECT binding_ref, connector_id, actor_ref, account_ref, workspace_ref, scopes_json, "
                "sealed_refresh_token, issued_at, expires_at, revoked_at "
                "FROM google_oauth_refresh_credential WHERE binding_ref = ?",
                binding_ref,
            )
        )
        if len(found) != 1:
            raise ControlPlaneContractError(
                "missing_google_oauth_binding",
                "Google OAuth credential binding was not found",
            )
        row = found[0]
        try:
            parsed_scopes = json.loads(_row_value(row, "scopes_json"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("durable Google OAuth scopes row is invalid JSON") from exc
        if not isinstance(parsed_scopes, list):
            raise RuntimeError("durable Google OAuth scopes row must be a list")
        expires_text = _row_value(row, "expires_at")
        revoked_text = _row_value(row, "revoked_at")
        record = DurableGoogleOAuthCredential(
            binding_ref=_row_value(row, "binding_ref"),
            connector_id=_row_value(row, "connector_id"),
            actor_ref=_row_value(row, "actor_ref"),
            account_ref=_row_value(row, "account_ref"),
            workspace_ref=_row_value(row, "workspace_ref"),
            scopes=tuple(parsed_scopes),
            sealed_refresh_token=_row_value(row, "sealed_refresh_token"),
            issued_at=_parse_iso(_row_value(row, "issued_at"), "issued_at"),
            expires_at=_parse_iso(expires_text, "expires_at") if expires_text is not None else None,
            revoked_at=_parse_iso(revoked_text, "revoked_at") if revoked_text is not None else None,
        )
        if not record.usable_at(now):
            raise ControlPlaneContractError(
                "inactive_google_oauth_binding",
                "Google OAuth credential is expired or revoked",
            )
        return record

    def revoke_credential(self, *, binding_ref: str, revoked_at: datetime) -> None:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        revoked_at = _utc(revoked_at, "revoked_at")

        def operation() -> None:
            found = _rows(
                self._sql.exec(
                    "SELECT issued_at, revoked_at FROM google_oauth_refresh_credential WHERE binding_ref = ?",
                    binding_ref,
                )
            )
            if len(found) != 1 or _row_value(found[0], "revoked_at") is not None:
                raise ControlPlaneContractError(
                    "inactive_google_oauth_binding",
                    "Google OAuth credential is missing or already revoked",
                )
            issued_at = _parse_iso(_row_value(found[0], "issued_at"), "issued_at")
            if revoked_at < issued_at:
                raise ControlPlaneContractError(
                    "invalid_google_oauth_durable_record",
                    "credential revocation cannot predate issue time",
                )
            cursor = self._sql.exec(
                "UPDATE google_oauth_refresh_credential SET revoked_at = ? "
                "WHERE binding_ref = ? AND revoked_at IS NULL",
                _iso(revoked_at),
                binding_ref,
            )
            if _rows_written(cursor) != 1:
                raise RuntimeError("Google OAuth credential disappeared during revocation")

        self.transaction(operation)

    def list_workspace_connector_state(
        self,
        *,
        workspace_ref: str,
        now: datetime,
        connector_ids: tuple[str, ...] | None = None,
    ) -> tuple[GoogleOAuthWorkspaceConnectorState, ...]:
        """Bounded workspace-scoped Google connector truth; identity-free.

        This is the read primitive behind the future connector-status surface.
        It deliberately returns *only* :class:`GoogleOAuthWorkspaceConnectorState`
        values. The query selects nothing but ``connector_id``, ``expires_at``
        and ``revoked_at``; that is the minimum needed to evaluate usability and
        expiry presence. Raw identity (``binding_ref``, ``actor_ref``,
        ``account_ref``, ``workspace_ref``), ``scopes`` and
        ``sealed_refresh_token`` are neither selected nor projected back to the
        caller.

        ``expires_present`` is derived from the **usable row set only**. An
        expired or revoked row is not active truth, so it must not influence the
        flag: otherwise a workspace whose single usable binding has no expiry
        would report ``expires_present=True`` merely because some inactive row
        carried one.

        ``workspace_ref`` is the durable row's own canonical workspace key; the
        query is always anchored to ``WHERE workspace_ref = ?`` so a caller can
        never observe another workspace's bindings.

        ``connector_ids`` is an internal bounded narrowing filter, not a public
        API surface. It must be a duplicate-free tuple drawn from the reviewed
        Google readonly connector set, so one request can never emit the same
        connector twice.

        No token is unsealed, no access lease is issued, and nothing is written.
        """
        workspace_ref = _safe_ref(workspace_ref, "workspace_ref")
        now = _utc(now, "now")
        if connector_ids is None:
            # #2830 non-widening rule: the default surface stays exactly the
            # authorized B-0 set (gmail + google-drive). Adding google-calendar
            # as a reviewed OAuth authority above must never widen this
            # public/default projection.
            reviewed = tuple(WORKSPACE_READ_CONNECTOR_SCOPE)
        else:
            if not isinstance(connector_ids, tuple):
                raise ControlPlaneContractError(
                    "invalid_google_oauth_durable_record",
                    "connector_ids filter must be a tuple of reviewed connector ids",
                )
            if len(set(connector_ids)) != len(connector_ids):
                raise ControlPlaneContractError(
                    "invalid_google_oauth_durable_record",
                    "connector_ids filter must not repeat a connector id",
                )
            reviewed = tuple(connector_ids)
        if not reviewed:
            return ()
        for connector_id in reviewed:
            if connector_id not in _REVIEWED_SCOPES:
                raise ControlPlaneContractError(
                    "invalid_google_oauth_durable_record",
                    "connector_id is not a reviewed Google readonly connector",
                )
        placeholders = ", ".join("?" for _ in reviewed)
        rows = _rows(
            self._sql.exec(
                "SELECT connector_id, expires_at, revoked_at "
                "FROM google_oauth_refresh_credential "
                f"WHERE workspace_ref = ? AND connector_id IN ({placeholders})",
                workspace_ref,
                *reviewed,
            )
        )
        # Per connector, track the expiry presence of *usable* rows only.
        usable_expiry: dict[str, list[bool]] = {connector_id: [] for connector_id in reviewed}
        for row in rows:
            connector_id = _row_value(row, "connector_id")
            if connector_id not in usable_expiry:
                continue
            expires_text = _row_value(row, "expires_at")
            revoked_text = _row_value(row, "revoked_at")
            expires_at = _parse_iso(expires_text, "expires_at") if expires_text is not None else None
            revoked_at = _parse_iso(revoked_text, "revoked_at") if revoked_text is not None else None
            if revoked_at is not None or (expires_at is not None and now >= expires_at):
                # Inactive truth: never contributes to state or expires_present.
                continue
            usable_expiry[connector_id].append(expires_at is not None)

        states: list[GoogleOAuthWorkspaceConnectorState] = []
        for connector_id in reviewed:
            verdicts = usable_expiry[connector_id]
            states.append(
                workspace_connector_state(
                    connector_id=connector_id,
                    usable_rows=len(verdicts),
                    expires_present=any(verdicts),
                )
            )
        return tuple(states)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "cloudflare_durable_object": True,
            "sqlite_storage": True,
            "connect_ticket_replay_durable": True,
            "oauth_state_single_use": True,
            "expired_oauth_state_single_use": True,
            "sealed_envelope_required": True,
            "sealed_session_only": True,
            "sealed_refresh_token_only": True,
            "reviewed_readonly_scopes_only": True,
            "raw_refresh_token_persisted": False,
            "raw_pkce_verifier_persisted": False,
            "raw_connect_ticket_persisted": False,
            "cryptography_implemented_here": False,
            "webcrypto_sealer_required": True,
            "production_deployment": False,
            "production_ready": False,
        }


WORKER_NATIVE_DURABLE_STORE_SOURCE_READY = True
WEBCRYPTO_SEALER_REQUIRED = True
SEALED_ENVELOPE_VERSION = "v1"
PUBLIC_OAUTH_ROUTE_ADDED = False
PRODUCTION_MUTATION = False
# Phase B-0 (#2830): workspace-scoped Google connector truth read primitive.
# Bounded projection only; raw identity and sealed material never leave the row.
WORKSPACE_KEYED_CONNECTOR_READ = True
WORKSPACE_READ_REQUIRES_EXACT_WORKSPACE_REF = True
# Authorized #2830 Phase B-0 surface (Gmail + Drive only). #2010 Calendar is a
# reviewed OAuth authority in OAUTH_REVIEWED_CONNECTORS, but it is NOT part of
# this default workspace-status projection.
WORKSPACE_READ_CONNECTOR_SCOPE = ("gmail", "google-drive")
# #2830_WORKSPACE_STATUS_SURFACE_WIDENED=NO
CALENDAR_OAUTH_REVIEWED_CONNECTOR = "google-calendar"
OAUTH_REVIEWED_CONNECTORS_INCLUDE_CALENDAR = "google-calendar" in OAUTH_REVIEWED_CONNECTORS
WORKSPACE_READ_TOKEN_UNSEAL = False
WORKSPACE_READ_ACCESS_LEASE_ISSUE = False
WORKSPACE_READ_PUBLIC_ROUTE = False
WORKSPACE_READ_WRITE_SCOPE = False
WORKSPACE_READ_DUPLICATE_ACTIVE_POLICY = "ambiguous_fail_closed"
WORKSPACE_READ_EXPIRES_PRESENT_SCOPE = "usable_rows_only"
WORKSPACE_READ_DUPLICATE_CONNECTOR_FILTER = "rejected"
WORKSPACE_READ_BINDING_REF_OUTPUT = False
WORKSPACE_READ_ACTOR_ACCOUNT_REF_OUTPUT = False
WORKSPACE_READ_WORKSPACE_REF_ECHO = False
WORKSPACE_READ_SCOPES_OUTPUT = False
WORKSPACE_READ_SEALED_CREDENTIAL_OUTPUT = False
WORKSPACE_READ_SCHEMA_UNIQUE_INDEX_ADDED = False
