"""#4139 reviewed SOURCE-ONLY extension of the existing canonical Identity DO.

This is NOT a second login authority, broker, device registry, or product D1
shadow. The only intended host is the existing canonical Identity Durable
Object SQLite database. No schema is installed from __init__, and no production
RPC calls this adapter until explicit host-security review.

The store persists explicit, server-verified per-device consent and a minimal
challenge->ORIGINAL canonical session pointer. It never persists browser
cookies, pairing codes, HMAC proofs, device credentials or full sessions.

The current session is re-read from the EXISTING Identity DO session authority
on every redemption, not reconstructed from old browser/client assertions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Protocol

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentConsent

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
SCHEMA_INSTALLED_BY_DEFAULT = False
PRODUCTION_CONSENT_RPC_EXPOSED = False
PRODUCT_DEVICE_REGISTRY_CREATED = False
CANONICAL_IDENTITY_DURABLE_OBJECT_REUSED = True


def _error(code: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, code)


def _ref(value: str) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise _error("connector_enrollment_invalid_reference")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("connector_enrollment_invalid_time")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime:
    if not isinstance(value, str):
        raise _error("connector_enrollment_durable_corrupt")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError) as exc:
        raise _error("connector_enrollment_durable_corrupt") from exc


def _rows(cursor: Any) -> list[dict[str, Any]]:
    reader = getattr(cursor, "toArray", None)
    if not callable(reader):
        raise _error("connector_enrollment_durable_unavailable")
    try:
        result = reader()
    except (RuntimeError, ValueError, TypeError) as exc:
        raise _error("connector_enrollment_durable_unavailable") from exc
    # Cloudflare DO / Pyodide may return JavaScript proxy rows. Use the
    # canonical Identity authority's existing to_py()/dict() conversion order,
    # while refusing malformed rows rather than silently filling fields.
    try:
        rows: list[dict[str, Any]] = []
        for item in result:
            if isinstance(item, dict):
                row = dict(item)
            else:
                to_py = getattr(item, "to_py", None)
                converted = to_py() if callable(to_py) else None
                row = dict(converted) if isinstance(converted, dict) else dict(item)
            rows.append(row)
    except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
        raise _error("connector_enrollment_durable_corrupt") from exc
    return rows


class CurrentCanonicalIdentitySessionReader(Protocol):
    """The pre-existing Identity Durable Object session authority."""

    def resolve_auth_session(self, *, session_id: str) -> AuthSessionSnapshot: ...


class IdentityDurableConnectorEnrollmentRecords:
    """Same SQLite Durable Object storage as canonical product/auth sessions.

    install_schema() is a separate explicit schema-review action, NOT called
    automatically by constructing this adapter, nor by production import.
    All DB mutations use existing ctx.storage.transactionSync.
    """

    def __init__(
        self, *, storage: Any, session_reader: CurrentCanonicalIdentitySessionReader
    ) -> None:
        if storage is None or not callable(getattr(getattr(storage, "sql", None), "exec", None)):
            raise ValueError("canonical Identity Durable Object SQLite required")
        if not callable(getattr(storage, "transactionSync", None)):
            raise ValueError("canonical DO transactional storage required")
        if not callable(getattr(session_reader, "resolve_auth_session", None)):
            raise ValueError("same canonical DO auth-session authority required")
        self._sql = storage.sql
        self._storage = storage
        self._session_reader = session_reader

    def install_schema(self) -> None:
        """Create additive tables ONLY after separately reviewed operator gate."""
        def op() -> None:
            self._sql.exec(
                "CREATE TABLE IF NOT EXISTS canonical_connector_enrollment_consent ("
                "consent_id TEXT PRIMARY KEY, owner_subject_id TEXT NOT NULL, "
                "account_ref TEXT NOT NULL, workspace_ref TEXT NOT NULL, "
                "device_id TEXT NOT NULL, granted_at TEXT NOT NULL, withdrawn_at TEXT)"
            )
            self._ensure_withdrawn_at_column()
            self._sql.exec(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_connector_consent_one_active_device "
                "ON canonical_connector_enrollment_consent(owner_subject_id,device_id) "
                "WHERE withdrawn_at IS NULL"
            )
            self._sql.exec(
                "CREATE TABLE IF NOT EXISTS canonical_connector_enrollment_session_binding ("
                "challenge_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
                "owner_subject_id TEXT NOT NULL, product_id TEXT NOT NULL, "
                "tenant_id TEXT NOT NULL, expires_at TEXT NOT NULL)"
            )
        self._storage.transactionSync(op)

    def _ensure_withdrawn_at_column(self) -> None:
        """Additive repair only: a consent table created before withdrawal
        tracking keeps every existing row; the missing nullable column is
        added and nothing else is altered, dropped, or backfilled."""
        try:
            info = self._sql.exec(
                "PRAGMA table_info(canonical_connector_enrollment_consent)"
            )
            reader = getattr(info, "toArray", None)
            if not callable(reader):
                raise _error("connector_enrollment_durable_unavailable")
        except Exception as exc:
            raise _error("connector_enrollment_durable_unavailable") from exc
        # PRAGMA metadata follows the same DO row conversion contract as
        # SELECT rows; proxy rows must not masquerade as missing columns.
        names = {row.get("name") for row in _rows(info)}
        if "consent_id" not in names:
            raise _error("connector_enrollment_durable_unavailable")
        if "withdrawn_at" not in names:
            try:
                self._sql.exec(
                    "ALTER TABLE canonical_connector_enrollment_consent "
                    "ADD COLUMN withdrawn_at TEXT"
                )
            except Exception as exc:
                raise _error("connector_enrollment_durable_unavailable") from exc

    @staticmethod
    def _consent(row: dict[str, Any]) -> ConnectorEnrollmentConsent:
        try:
            # Do not transform NULL, numbers, or missing required fields into
            # valid-looking string references (e.g. str(None) == "None").
            references = ("consent_id", "owner_subject_id", "account_ref",
                          "workspace_ref", "device_id")
            if any(type(row[key]) is not str for key in references):
                raise ValueError("invalid consent row reference type")
            return ConnectorEnrollmentConsent(
                consent_id=row["consent_id"],
                owner_subject_id=row["owner_subject_id"],
                account_ref=row["account_ref"],
                workspace_ref=row["workspace_ref"],
                device_id=row["device_id"],
                granted_at=_parse(row["granted_at"]),
                withdrawn_at=_parse(row["withdrawn_at"]) if row["withdrawn_at"] is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("connector_enrollment_durable_corrupt") from exc

    def _query(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        try:
            return _rows(self._sql.exec(sql, *args))
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            # A missing schema, transient DO storage failure or sqlite driver
            # exception must NEVER become a client-visible raw DB error.
            raise _error("connector_enrollment_durable_unavailable") from exc

    def persist_preverified_consent(
        self, *, consent: ConnectorEnrollmentConsent, now: datetime
    ) -> None:
        """Trusted, reviewed OWNER decision ONLY — no public bool/flag grants.

        The host MUST already have verified explicit current owner approval
        under canonical session/CSRF. This method is NEVER a public RPC and
        does not infer consent from a login, popup or device-supplied input.
        """
        moment = _utc(now)
        if not isinstance(consent, ConnectorEnrollmentConsent):
            raise _error("connector_enrollment_invalid_consent")
        if not consent.is_active(now=moment):
            raise _error("enrollment_consent_withdrawn")
        def op() -> None:
            existing = self.current_for_device(
                owner_subject_id=consent.owner_subject_id, device_id=consent.device_id, now=moment
            )
            if existing is not None:
                raise _error("enrollment_duplicate_device_consent_denied")
            self._sql.exec(
                "INSERT INTO canonical_connector_enrollment_consent "
                "(consent_id,owner_subject_id,account_ref,workspace_ref,device_id,granted_at,withdrawn_at) "
                "VALUES (?,?,?,?,?,?,NULL)",
                consent.consent_id, consent.owner_subject_id, consent.account_ref,
                consent.workspace_ref, consent.device_id, _iso(consent.granted_at),
            )
        try:
            self._storage.transactionSync(op)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            # Normalize unexpected SQLite / Durable Object failures.
            raise _error("connector_enrollment_durable_unavailable") from exc

    def current_for_device(
        self, *, owner_subject_id: str, device_id: str, now: datetime
    ) -> ConnectorEnrollmentConsent | None:
        _utc(now)
        rows = self._query(
            "SELECT * FROM canonical_connector_enrollment_consent "
            "WHERE owner_subject_id=? AND device_id=? AND withdrawn_at IS NULL",
            _ref(owner_subject_id), _ref(device_id),
        )
        if len(rows) > 1:
            raise _error("connector_enrollment_durable_corrupt")
        if not rows:
            return None
        consent = self._consent(rows[0])
        return consent if consent.is_active(now=now) else None

    def current_consent(
        self, *, consent_id: str, now: datetime
    ) -> ConnectorEnrollmentConsent | None:
        _utc(now)
        rows = self._query(
            "SELECT * FROM canonical_connector_enrollment_consent WHERE consent_id=?",
            _ref(consent_id),
        )
        if len(rows) > 1:
            raise _error("connector_enrollment_durable_corrupt")
        return self._consent(rows[0]) if rows else None

    def withdraw_preverified_consent(
        self, *, consent_id: str, owner_subject_id: str, now: datetime
    ) -> None:
        """Only the authenticated canonical OWNER host may invoke revocation."""
        consent_id = _ref(consent_id)
        owner = _ref(owner_subject_id)
        at = _utc(now)
        def op() -> None:
            rows = self._query(
                "SELECT * FROM canonical_connector_enrollment_consent "
                "WHERE consent_id=? AND owner_subject_id=?", consent_id, owner
            )
            if len(rows) != 1:
                raise _error("enrollment_consent_required")
            stored = self._consent(rows[0])
            if not stored.is_active(now=at):
                raise _error("enrollment_consent_withdrawn")
            stamped = _iso(at)
            self._sql.exec(
                "UPDATE canonical_connector_enrollment_consent SET withdrawn_at=? "
                "WHERE consent_id=? AND owner_subject_id=? AND withdrawn_at IS NULL",
                stamped, consent_id, owner,
            )
            # Verify through the same SELECT shape every other read uses.
            # A bare `SELECT changes()` relies on a cursor contract this
            # Durable Object SQLite path never proved in production; the
            # re-read below only depends on the proven row-projection shape.
            reread = self._query(
                "SELECT withdrawn_at FROM canonical_connector_enrollment_consent "
                "WHERE consent_id=? AND owner_subject_id=?",
                consent_id, owner,
            )
            if len(reread) != 1 or reread[0].get("withdrawn_at") != stamped:
                raise _error("connector_enrollment_durable_corrupt")
        try:
            self._storage.transactionSync(op)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _error("connector_enrollment_durable_unavailable") from exc

    def bind_challenge(
        self, *, challenge_id: str, session: AuthSessionSnapshot,
        expires_at: datetime, now: datetime
    ) -> None:
        """Bind ONLY the original canonical auth session pointer, no secrets."""
        challenge = _ref(challenge_id)
        at = _utc(now)
        expiry = _utc(expires_at)
        if not isinstance(session, AuthSessionSnapshot) or not session.tenant_id:
            raise _error("canonical_session_required")
        if not session.is_active(now=at) or expiry <= at or expiry > session.expires_at:
            raise _error("canonical_session_inactive")
        # Re-query current identity truth at the time the record is written.
        current = self._session_reader.resolve_auth_session(session_id=session.session_id)
        if not isinstance(current, AuthSessionSnapshot) or not current.is_active(now=at):
            raise _error("canonical_session_inactive")
        if (current.session_id, current.product_id, current.subject.subject_id, current.tenant_id) != (
            session.session_id, session.product_id, session.subject.subject_id, session.tenant_id
        ):
            raise _error("canonical_session_scope_mismatch")
        def op() -> None:
            self._sql.exec(
                "INSERT INTO canonical_connector_enrollment_session_binding "
                "(challenge_id,session_id,owner_subject_id,product_id,tenant_id,expires_at) "
                "VALUES (?,?,?,?,?,?)",
                challenge, session.session_id, session.subject.subject_id,
                session.product_id, session.tenant_id, _iso(expiry),
            )
        try:
            self._storage.transactionSync(op)
        except Exception as exc:
            raise _error("connector_enrollment_durable_unavailable") from exc

    def current_session(
        self, *, challenge_id: str, now: datetime
    ) -> AuthSessionSnapshot | None:
        """Read ORIGINAL session id and recheck CURRENT canonical auth authority."""
        moment = _utc(now)
        rows = self._query(
            "SELECT session_id,owner_subject_id,product_id,tenant_id,expires_at "
            "FROM canonical_connector_enrollment_session_binding WHERE challenge_id=?",
            _ref(challenge_id),
        )
        if len(rows) != 1:
            return None
        row = rows[0]
        if moment >= _parse(row["expires_at"]):
            return None
        try:
            current = self._session_reader.resolve_auth_session(session_id=str(row["session_id"]))
        except ControlPlaneContractError:
            return None
        if not isinstance(current, AuthSessionSnapshot) or not current.is_active(now=moment):
            return None
        if (current.session_id, current.product_id, current.subject.subject_id, current.tenant_id) != (
            row["session_id"], row["product_id"], row["owner_subject_id"], row["tenant_id"]
        ):
            return None
        return current
