"""#3669 — the canonical durable store for bounded `browser.control` action leases.

CENTRAL ruling for #3669 (DECISION=B): the bounded lease admission authority
lives on the trusted local-agent side as a **separate** canonical durable
store. This module is its storage half.

    NEW_DURABLE_LEASE_STORE=1
    NEW_APPROVAL_STORE=0
    DESKTOP_DURABLE_LEASE_AUTHORITY=NO
    DURABLE_RUN_STORE_TOUCHED=NO        (schema, table, state machine: untouched)
    LEASE_ROW_GC=DEFERRED
    AUTO_RECOVERY_REAUTHORIZE=NO

One row per approved `browser.control` session request (keyed by the canonical
request fingerprint). The row shape is minimal and flat — there is **no new
lifecycle state machine**: "active" is *derived*, it is never stored.

    ACTIVE = revoked_at IS NULL
             AND now < expires_at
             AND consumed_actions < max_actions
             AND the bounded idle window is satisfied

Conventions are reused from the canonical `DurableRunStore` (issue #3082), not
invented: WAL journaling, explicit `BEGIN IMMEDIATE` single-writer
transactions, a `PRAGMA user_version` schema gate, `quick_check` on open, and
deterministic fail-closed refusal codes. The store is a single SQLite file of
its own, in the same durable path family as the run store.

What this module is NOT:

* it is **not an approval authority** — a row only ever exists because the
  `BrowserControlLeaseAuthority` validated canonical P01 evidence and a
  recomputed local policy before calling `issue_from_p01`;
* it never mints a lease — `lease_id` is a *deterministic derivation* of the
  request fingerprint, so a same-fingerprint re-issuance lands on the same row
  (idempotency), and a fingerprint/correlation mismatch fails closed;
* it is not a renewal engine — after issuance the only writer states are the
  monotonic durable consume, a revoke and the explicit primitive; no path
  extends `expires_at`, `consumed_actions` or `max_actions`;
* it is not a replay engine — a restart reopens the same rows. A lease with
  K consumed slots sees its next success at K+1, and expired, revoked or
  exhausted rows are non-executable forever.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Self

from .browser_control_actions import (
    LEASE_ELIGIBLE_ACTIONS,
    LEASE_IDLE_SECONDS,
    LEASE_MAX_ACTIONS_HARD_CAP,
    MAX_ORIGIN_CHARS,
    ORIGIN_RE,
    SAFE_REF_RE,
)
from .contracts import ContractError

BROWSER_CONTROL_LEASE_STORE_SCHEMA_VERSION = 1

_TABLE = "claw_browser_control_leases"

#: A SQLite file always begins with this 16-byte header; checking it directly
#: keeps the "not a database" refusal deterministic.
_SQLITE_MAGIC = b"SQLite format 3\x00"

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

#: The closed vocabulary of durable revoke reasons. A second, open-ended
#: vocabulary would let a caller launder a revoke into a story, so the column
#: is checked against exactly this set on the way in *and* on the way out.
REVOKE_REASONS = ("cross_origin", "idle_expired", "explicit")

#: Deterministic fail-closed storage codes (stable strings; support and the
#: recovery projections both key off them).
STORE_ERROR_CODES = (
    "lease_store_unreadable",
    "lease_store_corrupt",
    "lease_store_integrity_check_failed",
    "lease_store_unsupported_schema_version",
    "lease_store_schema_version_missing",
    "lease_store_invalid_ref",
    "lease_store_invalid_timestamp",
    "lease_store_invalid_enum",
    "lease_store_invalid_row",
)

#: The closed set of *action-level* lease refusals the store raises against a
#: specific request. Every one of them means "no slot was consumed".
LEASE_REFUSAL_CODES = (
    "lease_unknown",
    "lease_revoked",
    "lease_expired",
    "lease_idle_exceeded",
    "lease_correlation_mismatch",
    "action_not_allowed",
    "action_budget_exhausted",
    "origin_scope_exceeded",
    "lease_busy",
)

# --- explicit capability declarations --------------------------------------
# Declared, not inferred: a future change that quietly introduces one of
# these facts fails a test instead of shipping.
STORE_MINTS_LEASE_ID = False           # lease_id is a deterministic derivation
STORE_MINTS_FINGERPRINT = False
STORE_RENEWS_LEASE = False             # no path extends expiry, count or budget
STORE_GRANTS_EXECUTION_AUTHORITY = False
LEASE_ROW_GC_SUPPORTED = False         # LEASE_ROW_GC=DEFERRED: rows are retained
AUTO_RECOVERY_REAUTHORIZE = False      # restart never re-authorizes anything
REVOKE_REASON_VOCABULARY_IS_OPEN = False

_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    lease_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL UNIQUE,
    browser_session_ref TEXT NOT NULL,
    run_ref TEXT NOT NULL,
    workspace_ref TEXT NOT NULL,
    owner_ref TEXT NOT NULL,
    allowed_action_classes TEXT NOT NULL,
    origin_scope TEXT NOT NULL,
    max_actions INTEGER NOT NULL,
    consumed_actions INTEGER NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_consumed_at TEXT,
    revoked_at TEXT,
    revoke_reason TEXT,
    approval_ref TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    command_id TEXT,
    admission_ref TEXT,
    revision_ref TEXT
)
"""

_CREATE_FINGERPRINT_INDEX = (
    f"CREATE INDEX IF NOT EXISTS {_TABLE}_fingerprint ON {_TABLE}(request_fingerprint)"
)


class BrowserControlLeaseStoreError(ContractError):
    """A fail-closed durable store refusal carrying a deterministic code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class BrowserControlLeaseRefusal(BrowserControlLeaseStoreError):
    """An action-level lease refusal (one of `LEASE_REFUSAL_CODES`)."""


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not SAFE_REF_RE.fullmatch(value.strip()):
        raise BrowserControlLeaseStoreError(
            "lease_store_invalid_ref", f"{field_name} must be a bounded safe reference"
        )
    return value.strip()


def _digest(value: Any, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(normalized):
        raise BrowserControlLeaseStoreError(
            "lease_store_invalid_ref", f"{field_name} must be a lowercase SHA-256 digest"
        )
    return normalized


def _origin(value: Any, field_name: str) -> str:
    origin = value.strip().lower() if isinstance(value, str) else ""
    if not origin or len(origin) > MAX_ORIGIN_CHARS or not ORIGIN_RE.fullmatch(origin):
        raise BrowserControlLeaseStoreError(
            "lease_store_invalid_ref", f"{field_name} must be a bounded bare http(s) origin"
        )
    return origin


def _aware_now(value: Any, field_name: str = "now") -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BrowserControlLeaseStoreError(
            "lease_store_invalid_timestamp", f"{field_name} must be a timezone-aware datetime"
        )
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware_now(value, "timestamp").isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise BrowserControlLeaseStoreError(
            "lease_store_invalid_timestamp", f"{field_name} is empty"
        )
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BrowserControlLeaseStoreError(
            "lease_store_invalid_timestamp", f"{field_name} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BrowserControlLeaseStoreError(
            "lease_store_invalid_timestamp", f"{field_name} is not timezone-aware"
        )
    return parsed.astimezone(UTC)


def _lease_id_from_fingerprint(request_fingerprint: str) -> str:
    """The deterministic lease identity: a derivation, never a second mint.

    The same request fingerprint always yields the same `lease_id`, which is
    what makes re-issuance idempotent across restarts instead of a second row.
    """

    return "lease_" + hashlib.sha256(
        f"browser-control-lease.v1:{request_fingerprint}".encode("utf-8")
    ).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class BrowserControlLeaseProjection:
    """One durable lease row, loaded whole. `active` is derived, never stored."""

    lease_id: str
    request_fingerprint: str
    browser_session_ref: str
    run_ref: str
    workspace_ref: str
    owner_ref: str
    allowed_action_classes: tuple[str, ...]
    origin_scope: str
    max_actions: int
    consumed_actions: int
    issued_at: datetime
    expires_at: datetime
    last_consumed_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: str | None
    approval_ref: str
    evidence_ref: str
    #: Optional internal correlation copies from the canonical evidence.
    command_id: str | None = None
    admission_ref: str | None = None
    revision_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lease_id", _ref(self.lease_id, "lease_id"))
        object.__setattr__(self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint"))
        for field_name in ("browser_session_ref", "run_ref", "workspace_ref", "owner_ref", "approval_ref", "evidence_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        for optional in ("command_id", "admission_ref", "revision_ref"):
            value = getattr(self, optional)
            if value is not None:
                object.__setattr__(self, optional, _ref(value, optional))
        classes = self.allowed_action_classes
        if (
            not isinstance(classes, tuple)
            or not classes
            or len(set(classes)) > len(LEASE_ELIGIBLE_ACTIONS)
            or any(cls not in LEASE_ELIGIBLE_ACTIONS for cls in classes)
        ):
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum",
                "allowed_action_classes must be a bounded subset of the lease-eligible classes",
            )
        object.__setattr__(self, "allowed_action_classes", tuple(sorted(classes)))
        object.__setattr__(self, "origin_scope", _origin(self.origin_scope, "origin_scope"))
        if isinstance(self.max_actions, bool) or not isinstance(self.max_actions, int):
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum", "max_actions must be an integer"
            )
        if not 1 <= self.max_actions <= LEASE_MAX_ACTIONS_HARD_CAP:
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum",
                f"max_actions must be 1..{LEASE_MAX_ACTIONS_HARD_CAP}",
            )
        if isinstance(self.consumed_actions, bool) or not isinstance(self.consumed_actions, int):
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum", "consumed_actions must be an integer"
            )
        if not 0 <= self.consumed_actions <= self.max_actions:
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_row",
                "consumed_actions may never exceed max_actions",
            )
        object.__setattr__(self, "issued_at", _aware_now(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _aware_now(self.expires_at, "expires_at"))
        if self.issued_at >= self.expires_at:
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_timestamp", "a lease must be born before it expires"
            )
        if self.last_consumed_at is not None:
            object.__setattr__(
                self, "last_consumed_at", _aware_now(self.last_consumed_at, "last_consumed_at")
            )
        if self.revoked_at is not None:
            object.__setattr__(
                self, "revoked_at", _aware_now(self.revoked_at, "revoked_at")
            )
        if self.revoked_at is not None and self.last_consumed_at is not None:
            if self.revoked_at < self.last_consumed_at:
                raise BrowserControlLeaseStoreError(
                    "lease_store_invalid_timestamp", "a revoke cannot predate the last consumption"
                )
        if self.revoke_reason is not None:
            if self.revoke_reason not in REVOKE_REASONS:
                raise BrowserControlLeaseStoreError(
                    "lease_store_invalid_enum",
                    f"revoke_reason {self.revoke_reason!r} is outside the closed vocabulary",
                )
            if self.revoked_at is None:
                raise BrowserControlLeaseStoreError(
                    "lease_store_invalid_row", "a revoke reason requires a revoked_at stamp"
                )
        elif self.revoked_at is not None:
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_row", "a revoked lease must carry a closed-vocabulary reason"
            )

    @property
    def idle_reference(self) -> datetime:
        """The last activity the bounded idle window is measured from.

        Before the first consumption the window starts at issuance — but the
        idle *refusal* only ever applies once a slot has been consumed
        (inactivity before the first action is just waiting; the TTL still
        bounds it). See `BrowserControlLeaseStore.consume_action`.
        """

        if self.consumed_actions > 0:
            assert self.last_consumed_at is not None
            return self.last_consumed_at
        return self.issued_at

    def active(self, *, now: datetime) -> bool:
        """DERIVED activeness (CENTRAL ruling §2): never a stored state."""

        moment = _aware_now(now)
        if self.revoked_at is not None:
            return False
        if moment >= self.expires_at:
            return False
        if self.consumed_actions >= self.max_actions:
            return False
        if self.consumed_actions > 0:
            if (moment - self.last_consumed_at).total_seconds() > LEASE_IDLE_SECONDS:
                return False
        return True

    def safe_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "request_fingerprint": self.request_fingerprint,
            "browser_session_ref": self.browser_session_ref,
            "run_ref": self.run_ref,
            "workspace_ref": self.workspace_ref,
            "owner_ref": self.owner_ref,
            "allowed_action_classes": list(self.allowed_action_classes),
            "origin_scope": self.origin_scope,
            "max_actions": self.max_actions,
            "consumed_actions": self.consumed_actions,
            "issued_at": _iso(self.issued_at),
            "expires_at": _iso(self.expires_at),
            "last_consumed_at": _iso(self.last_consumed_at) if self.last_consumed_at else None,
            "revoked_at": _iso(self.revoked_at) if self.revoked_at else None,
            "revoke_reason": self.revoke_reason,
            "approval_ref": self.approval_ref,
            "evidence_ref": self.evidence_ref,
            "command_id": self.command_id,
            "admission_ref": self.admission_ref,
            "revision_ref": self.revision_ref,
            "raw_page_content": False,
            "raw_credential": False,
            "p01_approval_payload": False,
        }

    def wire_lease_dict(self) -> dict[str, str | int | list[str]]:
        """The #3647 desktop `BoundedActionLease` shape, key-for-key.

        The Desktop-side `assertBoundedActionLease` validator is the schema
        authority for these 14 camelCase keys; this projection exists so the
        agent's own output stays assertable by that exact validator.
        """

        return {
            "leaseId": self.lease_id,
            "requestFingerprint": self.request_fingerprint,
            "browserSessionRef": self.browser_session_ref,
            "runRef": self.run_ref,
            "workspaceRef": self.workspace_ref,
            "ownerRef": self.owner_ref,
            "allowedActionClasses": list(self.allowed_action_classes),
            "originScope": self.origin_scope,
            "maxActions": self.max_actions,
            "issuedAtIso": _iso(self.issued_at),
            "expiresAtIso": _iso(self.expires_at),
            "approvalRef": self.approval_ref,
            "evidenceRef": self.evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class BrowserControlLeaseIssuance:
    """The bounded facts the authority hands to `issue_from_p01`.

    Every value is either copied from validated canonical P01 evidence and
    the trusted session context, or a policy default — nothing here is minted
    by the caller, and the store re-validates every bound on the way in.
    """

    request_fingerprint: str
    browser_session_ref: str
    run_ref: str
    workspace_ref: str
    owner_ref: str
    allowed_action_classes: tuple[str, ...]
    origin_scope: str
    max_actions: int
    issued_at: datetime
    expires_at: datetime
    approval_ref: str
    evidence_ref: str
    command_id: str | None = None
    admission_ref: str | None = None
    revision_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint"))
        for field_name in (
            "browser_session_ref",
            "run_ref",
            "workspace_ref",
            "owner_ref",
            "approval_ref",
            "evidence_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        for optional in ("command_id", "admission_ref", "revision_ref"):
            value = getattr(self, optional)
            if value is not None:
                object.__setattr__(self, optional, _ref(value, optional))
        classes = self.allowed_action_classes
        if (
            not isinstance(classes, tuple)
            or not classes
            or len(set(classes)) > len(LEASE_ELIGIBLE_ACTIONS)
            or any(cls not in LEASE_ELIGIBLE_ACTIONS for cls in classes)
        ):
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum",
                "allowed_action_classes must be a bounded subset of the lease-eligible classes",
            )
        object.__setattr__(self, "allowed_action_classes", tuple(sorted(classes)))
        object.__setattr__(self, "origin_scope", _origin(self.origin_scope, "origin_scope"))
        if isinstance(self.max_actions, bool) or not isinstance(self.max_actions, int):
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum", "max_actions must be an integer"
            )
        if not 1 <= self.max_actions <= LEASE_MAX_ACTIONS_HARD_CAP:
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum",
                f"max_actions must be 1..{LEASE_MAX_ACTIONS_HARD_CAP}",
            )
        object.__setattr__(self, "issued_at", _aware_now(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _aware_now(self.expires_at, "expires_at"))
        if not self.issued_at < self.expires_at:
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_timestamp", "a lease must be issued before it expires"
            )

    @property
    def lease_id(self) -> str:
        return _lease_id_from_fingerprint(self.request_fingerprint)


class BrowserControlLeaseStore:
    """Single-writer SQLite store for durable bounded browser-control leases.

    Reuses the `DurableRunStore` conventions (WAL, `BEGIN IMMEDIATE`, a
    `user_version` schema gate, `quick_check`, deterministic refusal codes) on
    its own SQLite file. See the module docstring for what this store does
    not do.
    """

    def __init__(
        self,
        database_path: str | Path,
        observer: Callable[[str], None] | None = None,
    ) -> None:
        self._observer = observer
        if isinstance(database_path, Path):
            database_path = str(database_path)
        if not isinstance(database_path, str) or not database_path.strip():
            raise ContractError("database_path must be non-empty")
        self._database_path = database_path.strip()
        self._observe("lease_store_path_resolved")
        if self._database_path != ":memory:":
            self._observe("lease_store_directory_prepare_start")
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
            self._observe("lease_store_directory_prepare_done")
        self._observe("lease_store_connect_start")
        self._db = self._connect()
        self._observe("lease_store_connect_done")
        try:
            self._verify_or_create_schema()
        except Exception:
            # Do not leak the handle on a refused open: on Windows an open
            # connection would keep the file locked and the caller could not
            # even inspect the very file it was told is corrupt.
            self._db.close()
            raise
        self._observe("lease_store_ready")

    def _observe(self, event: str) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event)
        except Exception:  # pragma: no cover - observation never breaks the store
            pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    @property
    def database_path(self) -> str:
        return self._database_path

    @property
    def schema_version(self) -> int:
        return int(self._db.execute("PRAGMA user_version").fetchone()[0])

    # --- lifecycle -----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._assert_sqlite_header()
        try:
            db = sqlite3.connect(
                self._database_path,
                isolation_level=None,
                check_same_thread=False,
            )
        except sqlite3.DatabaseError as exc:
            raise BrowserControlLeaseStoreError(
                "lease_store_unreadable", "database could not be opened"
            ) from exc
        try:
            db.row_factory = sqlite3.Row
            # WAL: the trusted main and the runner read and write while a lease
            # is live, and a crash mid-write must not corrupt the log.
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = FULL")
            db.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.DatabaseError as exc:
            db.close()
            raise BrowserControlLeaseStoreError(
                "lease_store_corrupt", "database could not be prepared for use"
            ) from exc
        return db

    def _assert_sqlite_header(self) -> None:
        if self._database_path == ":memory:":
            return
        path = Path(self._database_path)
        if not path.exists() or path.stat().st_size == 0:
            return
        try:
            with path.open("rb") as handle:
                header = handle.read(len(_SQLITE_MAGIC))
        except OSError as exc:
            raise BrowserControlLeaseStoreError(
                "lease_store_unreadable", "database file could not be read"
            ) from exc
        if header != _SQLITE_MAGIC:
            raise BrowserControlLeaseStoreError(
                "lease_store_corrupt", "database file is not a SQLite database"
            )

    def _verify_or_create_schema(self) -> None:
        try:
            result = self._db.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise BrowserControlLeaseStoreError(
                "lease_store_corrupt", "quick_check could not run"
            ) from exc
        if result is None or result[0] != "ok":
            raise BrowserControlLeaseStoreError(
                "lease_store_integrity_check_failed",
                f"quick_check reported {result!r}",
            )
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version == BROWSER_CONTROL_LEASE_STORE_SCHEMA_VERSION:
            return
        if version != 0:
            raise BrowserControlLeaseStoreError(
                "lease_store_unsupported_schema_version",
                f"schema version {version} is not supported",
            )
        existing = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
        ).fetchone()
        if existing is not None:
            raise BrowserControlLeaseStoreError(
                "lease_store_schema_version_missing",
                "lease rows exist but the schema version is unrecognised",
            )
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(_CREATE_TABLE)
            self._db.execute(_CREATE_FINGERPRINT_INDEX)
            self._db.execute(
                f"PRAGMA user_version = {BROWSER_CONTROL_LEASE_STORE_SCHEMA_VERSION}"
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    # --- row mapping ---------------------------------------------------------

    @staticmethod
    def _to_row(issuance: BrowserControlLeaseIssuance) -> dict[str, Any]:
        return {
            "lease_id": issuance.lease_id,
            "request_fingerprint": issuance.request_fingerprint,
            "browser_session_ref": issuance.browser_session_ref,
            "run_ref": issuance.run_ref,
            "workspace_ref": issuance.workspace_ref,
            "owner_ref": issuance.owner_ref,
            "allowed_action_classes": json.dumps(
                list(issuance.allowed_action_classes),
                sort_keys=True,
                separators=(",", ":"),
            ),
            "origin_scope": issuance.origin_scope,
            "max_actions": issuance.max_actions,
            "consumed_actions": 0,
            "issued_at": _iso(issuance.issued_at),
            "expires_at": _iso(issuance.expires_at),
            "last_consumed_at": None,
            "revoked_at": None,
            "revoke_reason": None,
            "approval_ref": issuance.approval_ref,
            "evidence_ref": issuance.evidence_ref,
            "command_id": issuance.command_id,
            "admission_ref": issuance.admission_ref,
            "revision_ref": issuance.revision_ref,
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> BrowserControlLeaseProjection:
        def optional_ref(field_name: str) -> str | None:
            value = row[field_name]
            return None if value is None else _ref(value, field_name)

        def optional_ts(field_name: str) -> datetime | None:
            value = row[field_name]
            return None if value is None else _parse_ts(value, field_name)

        raw_classes = row["allowed_action_classes"]
        try:
            classes = json.loads(raw_classes) if isinstance(raw_classes, str) else None
        except (json.JSONDecodeError, TypeError):
            classes = None
        try:
            return BrowserControlLeaseProjection(
                lease_id=row["lease_id"],
                request_fingerprint=row["request_fingerprint"],
                browser_session_ref=row["browser_session_ref"],
                run_ref=row["run_ref"],
                workspace_ref=row["workspace_ref"],
                owner_ref=row["owner_ref"],
                allowed_action_classes=(
                    tuple(classes) if isinstance(classes, list) and classes else ()
                ),
                origin_scope=row["origin_scope"],
                max_actions=row["max_actions"],
                consumed_actions=row["consumed_actions"],
                issued_at=_parse_ts(row["issued_at"], "issued_at"),
                expires_at=_parse_ts(row["expires_at"], "expires_at"),
                last_consumed_at=optional_ts("last_consumed_at"),
                revoked_at=optional_ts("revoked_at"),
                revoke_reason=row["revoke_reason"],
                approval_ref=row["approval_ref"],
                evidence_ref=row["evidence_ref"],
                command_id=optional_ref("command_id"),
                admission_ref=optional_ref("admission_ref"),
                revision_ref=optional_ref("revision_ref"),
            )
        except BrowserControlLeaseStoreError:
            raise
        except ContractError as exc:
            # A row that cannot satisfy the minimal lease shape is corrupt, not
            # a lease we are free to reinterpret.
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_row", f"stored row violates the lease contract: {exc}"
            ) from exc

    def _select(self, request_fingerprint: str) -> BrowserControlLeaseProjection | None:
        row = self._db.execute(
            f"SELECT * FROM {_TABLE} WHERE request_fingerprint = ?", (request_fingerprint,)
        ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    # --- issuance ------------------------------------------------------------

    def issue_from_p01(
        self, issuance: BrowserControlLeaseIssuance
    ) -> tuple[BrowserControlLeaseProjection, bool]:
        """Idempotently land one validated issuance under the UNIQUE fingerprint.

        Same fingerprint + same correlations returns the existing row (the
        `issued` flag is False, the row keeps its original issued/expires
        stamps — no renewal). A fingerprint that is already bound to *different*
        correlations fails closed: two distinct sessions cannot share a row.
        """

        if not isinstance(issuance, BrowserControlLeaseIssuance):
            raise ContractError("issuance must be a BrowserControlLeaseIssuance")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._select(issuance.request_fingerprint)
            if existing is not None:
                mismatched = [
                    name
                    for name in (
                        "browser_session_ref",
                        "run_ref",
                        "workspace_ref",
                        "owner_ref",
                        "allowed_action_classes",
                        "origin_scope",
                        "max_actions",
                        "approval_ref",
                        "evidence_ref",
                    )
                    if getattr(existing, name) != getattr(issuance, name)
                ]
                if mismatched:
                    self._db.execute("ROLLBACK")
                    raise BrowserControlLeaseRefusal(
                        "lease_correlation_mismatch",
                        "this request fingerprint is already bound to different "
                        "correlations: " + ", ".join(mismatched),
                    )
                self._db.execute("ROLLBACK")
                return existing, False
            row = self._to_row(issuance)
            columns = ", ".join(row)
            placeholders = ", ".join(f":{name}" for name in row)
            self._db.execute(
                f"INSERT INTO {_TABLE} ({columns}) VALUES ({placeholders})", row
            )
            self._db.execute("COMMIT")
        except BrowserControlLeaseRefusal:
            raise
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        created = self._select(issuance.request_fingerprint)
        assert created is not None
        return created, True

    # --- PHASE A: read-only resolve ------------------------------------------

    def resolve_lease(
        self,
        request_fingerprint: str,
        *,
        browser_session_ref: str,
        now: datetime,
    ) -> BrowserControlLeaseProjection:
        """PHASE A of the two-phase provider: confirm, never mutate.

        The projection is returned only when the lease is derivable-active at
        `now` (not revoked, not expired, budget remaining, idle window
        satisfied, session bound). No slot is consumed and no row is written.
        An idle observation *refuses* here — the durable revoke for idle
        belongs to `consume_action`, the single owner of the revoke write.
        """

        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        session_ref = _ref(browser_session_ref, "browser_session_ref")
        moment = _aware_now(now)
        projection = self._select(fingerprint)
        if projection is None:
            raise BrowserControlLeaseRefusal("lease_unknown", "no durable lease for this request")
        if projection.browser_session_ref != session_ref:
            raise BrowserControlLeaseRefusal(
                "lease_correlation_mismatch",
                "the lease is not bound to this browser session",
            )
        if projection.revoked_at is not None:
            raise BrowserControlLeaseRefusal(
                "lease_revoked", f"the lease is durably revoked ({projection.revoke_reason})"
            )
        if moment >= projection.expires_at:
            raise BrowserControlLeaseRefusal("lease_expired", "the lease TTL has passed")
        if projection.consumed_actions >= projection.max_actions:
            raise BrowserControlLeaseRefusal(
                "action_budget_exhausted", "the lease budget is exhausted"
            )
        if projection.consumed_actions > 0 and (
            moment - projection.last_consumed_at
        ).total_seconds() > LEASE_IDLE_SECONDS:
            # Read-only here: surface the idle fact, let consume own the revoke.
            raise BrowserControlLeaseRefusal(
                "lease_idle_exceeded", "the lease went idle beyond the bounded idle window"
            )
        return projection

    # --- PHASE B: the atomic durable consume ---------------------------------

    def consume_action(
        self,
        request_fingerprint: str,
        *,
        browser_session_ref: str,
        run_ref: str,
        workspace_ref: str,
        owner_ref: str,
        action: str,
        observed_origin: str,
        now: datetime,
    ) -> BrowserControlLeaseProjection:
        """One `BEGIN IMMEDIATE`: verify every §6 fact, then consume exactly one slot.

        The verification order is the contract (all of it, before any write):

        1. the lease exists; 2. it has not been revoked; 3. now < expires_at;
        4. session/run/workspace/owner correlations match; 5. the action is in
           the allowed classes; 6. the observed origin is the exact origin
           scope; 7. a consumed lease is inside the bounded idle window;
        8. a slot remains.

        On an idle breach or a cross-origin observation the row is durably
        revoked in the *same* transaction (reasons `idle_expired` /
        `cross_origin` — the closed vocabulary, nothing open-ended) and the
        refusal is raised with **no** slot consumed. On success the
        `consumed_actions + 1` and `last_consumed_at` write is a CAS guarded
        by the expected pre-count: two real processes racing the last slot
        therefore produce exactly one success and exactly one refusal.
        """

        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        session_ref = _ref(browser_session_ref, "browser_session_ref")
        run = _ref(run_ref, "run_ref")
        workspace = _ref(workspace_ref, "workspace_ref")
        owner = _ref(owner_ref, "owner_ref")
        if action not in LEASE_ELIGIBLE_ACTIONS:
            raise BrowserControlLeaseRefusal(
                "action_not_allowed", f"action {action!r} is not lease-eligible"
            )
        origin = _origin(observed_origin, "observed_origin")
        moment = _aware_now(now)

        self._db.execute("BEGIN IMMEDIATE")
        try:
            projection = self._select(fingerprint)
            if projection is None:
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal("lease_unknown", "no durable lease for this request")
            if projection.revoked_at is not None:
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal(
                    "lease_revoked", f"the lease is durably revoked ({projection.revoke_reason})"
                )
            if moment >= projection.expires_at:
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal("lease_expired", "the lease TTL has passed")
            mismatched = [
                name
                for name, supplied in (
                    ("browser_session_ref", session_ref),
                    ("run_ref", run),
                    ("workspace_ref", workspace),
                    ("owner_ref", owner),
                )
                if getattr(projection, name) != supplied
            ]
            if mismatched:
                # A run transfer attempt is refused, not revoked: the row stays
                # as it is and the canonical authority decides what happens.
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal(
                    "lease_correlation_mismatch",
                    "consume correlations do not match the lease: " + ", ".join(mismatched),
                )
            if action not in projection.allowed_action_classes:
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal(
                    "action_not_allowed", f"action {action!r} is not in this lease's allowed classes"
                )
            if origin != projection.origin_scope:
                self._revoke_in_transaction(projection, reason="cross_origin", now=moment)
                self._db.execute("COMMIT")
                raise BrowserControlLeaseRefusal(
                    "origin_scope_exceeded",
                    "the observed origin left the lease's exact origin scope; the lease is revoked",
                )
            if projection.consumed_actions > 0 and (
                moment - projection.last_consumed_at
            ).total_seconds() > LEASE_IDLE_SECONDS:
                self._revoke_in_transaction(projection, reason="idle_expired", now=moment)
                self._db.execute("COMMIT")
                raise BrowserControlLeaseRefusal(
                    "lease_idle_exceeded",
                    "the lease went idle beyond the bounded window; the lease is revoked",
                )
            if projection.consumed_actions >= projection.max_actions:
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal(
                    "action_budget_exhausted", "the lease budget is exhausted"
                )
            # The CAS: only the process that still sees the expected count
            # writes the increment.
            cursor = self._db.execute(
                f"UPDATE {_TABLE} SET consumed_actions = ?, last_consumed_at = ? "
                f"WHERE request_fingerprint = ? AND consumed_actions = ? AND revoked_at IS NULL",
                (
                    projection.consumed_actions + 1,
                    _iso(moment),
                    fingerprint,
                    projection.consumed_actions,
                ),
            )
            if cursor.rowcount != 1:
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal(
                    "lease_busy", "the lease slot write lost its CAS guard"
                )
            self._db.execute("COMMIT")
        except BrowserControlLeaseRefusal:
            raise
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        updated = self._select(fingerprint)
        assert updated is not None and updated.consumed_actions == projection.consumed_actions + 1
        return updated

    def _revoke_in_transaction(self, projection: BrowserControlLeaseProjection, *, reason: str, now: datetime) -> None:
        if reason not in REVOKE_REASONS:  # pragma: no cover - vocabulary is closed
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum", f"revoke reason {reason!r} is outside the vocabulary"
            )
        self._db.execute(
            f"UPDATE {_TABLE} SET revoked_at = ?, revoke_reason = ? "
            f"WHERE lease_id = ? AND revoked_at IS NULL",
            (_iso(now), reason, projection.lease_id),
        )

    # --- the explicit revoke primitive ---------------------------------------

    def revoke_lease(
        self, lease_id: str, *, reason: str, now: datetime
    ) -> BrowserControlLeaseProjection:
        """The one explicit revoke primitive (CENTRAL ruling §7).

        No renderer or public UI path calls this in this child — the primitive
        exists so a trusted caller can durably kill a lease. Revocation is
        monotone: a revoked lease is non-executable forever, including across
        restarts, and an already-revoked lease is never re-revoked with a
        different reason.
        """

        key = _ref(lease_id, "lease_id")
        if reason not in REVOKE_REASONS:
            raise BrowserControlLeaseStoreError(
                "lease_store_invalid_enum",
                f"revoke reason {reason!r} is outside the closed vocabulary {sorted(REVOKE_REASONS)}",
            )
        moment = _aware_now(now)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(f"SELECT * FROM {_TABLE} WHERE lease_id = ?", (key,)).fetchone()
            if row is None:
                self._db.execute("ROLLBACK")
                raise BrowserControlLeaseRefusal("lease_unknown", "no durable lease with this id")
            projection = self._from_row(row)
            if projection.revoked_at is not None:
                # Monotone: already dead, nothing to write.
                self._db.execute("ROLLBACK")
                return projection
            self._revoke_in_transaction(projection, reason=reason, now=moment)
            self._db.execute("COMMIT")
        except BrowserControlLeaseRefusal:
            raise
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        updated = self._db.execute(
            f"SELECT * FROM {_TABLE} WHERE lease_id = ?", (key,)
        ).fetchone()
        assert updated is not None
        result = self._from_row(updated)
        assert result.revoked_at is not None and result.revoke_reason == reason
        return result

    # --- reads ----------------------------------------------------------------

    def get(self, request_fingerprint: str) -> BrowserControlLeaseProjection | None:
        """Load one lease by its canonical fingerprint. Read-only."""

        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        return self._select(fingerprint)

    def list_projections(self) -> tuple[BrowserControlLeaseProjection, ...]:
        """Every stored lease, in stable order. Read-only, no classification verdict."""

        rows = self._db.execute(f"SELECT * FROM {_TABLE} ORDER BY lease_id").fetchall()
        return tuple(self._from_row(row) for row in rows)
