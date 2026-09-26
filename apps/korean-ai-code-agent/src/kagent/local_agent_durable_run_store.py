"""Desktop durable Local Runner store — issue #3082, slice 2 (durable store).

This module is the **storage** half of #3082. It persists
`kagent.local_agent_durable_run.DurableRunRecord` rows in a local SQLite
database, loads them back after a Desktop/runner restart, and classifies what it
finds. It is deliberately thin: every field, bound and invariant already lives in
the slice-1 record contract, and this module neither widens them nor decides
anything the record contract has not already decided.

What this module is NOT (P0 guardrails, unchanged from slice 1):

* it is **not an identity authority** — `command_id` is the durable primary key
  and `run_id` / `tool_request_ref` / `request_id` / `revision_ref` are copied
  correlation facts, minted nowhere here;
* it is **not an admission authority** — admission stays in #3080 and
  `kagent.local_agent_command_admission`; writing a row is not admission;
* it is **not a replay engine** — see "Restart recovery" below;
* it never recomputes a request fingerprint, never mints or orders a revision,
  never scans PIDs and never reattaches a process.

Restart recovery
----------------

Recovery here is **reconciliation, not replay**. On load, every stored row is
classified into exactly one `DurableRunRecoveryClass`:

``TERMINAL``
    Locally finished and server-acknowledged. Nothing to do.
``TERMINAL_SERVER_UNACKED``
    Locally finished but the server acknowledgement never arrived (the R8 crash
    window). It stays terminal and is retained; the missing ack is *not* treated
    as retry authority and the run is never re-executed.
``EXPIRED``
    The R6 hard deadline passed while the row was still non-terminal. The
    command can no longer become executable again, and is never replayed.
``ADMITTED_NONTERMINAL``
    Admitted but not locally terminal when the runner went away. #3081's
    `KILL_ON_JOB_CLOSE` reaped the process tree, so the prior execution's
    *outcome* is genuinely unknown. This is ambiguous prior execution: the row is
    surfaced for reconciliation and is **never** automatically re-executed.
``OFFLINE_RECONCILIATION_REQUIRED``
    A locally persisted, offline-queued row that awaits an admissible session.
    Metadata only — the offline queue grants no execution authority.

`DurableRunRecoveryReport.replay_candidates` is therefore always empty and
`execution_authority_granted` is always ``False``: the store can never be the
thing that says "this may run". Producing that decision belongs to the canonical
admission path and P01.

Fail-closed
-----------

A store that cannot be trusted must not be repaired silently. Opening a store
refuses with a deterministic `DurableRunStoreError.code` for an unreadable or
corrupt database, a failed `quick_check`, an unknown schema version, or a
database that carries rows but no recognised schema version. Loading a row
refuses for an invalid enum, timestamp, reference, fingerprint, revision, exit
code, duplicate identity, a terminal state without a termination reason, or a
server acknowledgement without admission correlation. Nothing is coerced,
defaulted or skipped.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Self

from .contracts import ContractError
from .local_agent_durable_run import (
    MAX_BOUNDED_EXIT_CODE,
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_SUMMARY_CHARS,
    MIN_BOUNDED_EXIT_CODE,
    BoundedEvidenceProjection,
    DurableRunOfflineState,
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
    _digest,
    _iso,
    _ref,
)

#: Bumped only when the on-disk layout changes. An unrecognised value is never
#: migrated automatically: it fails closed so a newer/older runner cannot read a
#: store whose meaning it does not know.
DURABLE_RUN_STORE_SCHEMA_VERSION = 1

_TABLE = "claw_durable_run_records"

#: A SQLite file always begins with this 16-byte header. Checking it directly
#: keeps the "not a database" refusal deterministic instead of depending on the
#: exact wording a `sqlite3` exception happens to use.
_SQLITE_MAGIC = b"SQLite format 3\x00"

#: Deterministic fail-closed codes. These are stable strings because support and
#: the recovery report both key off them.
STORE_ERROR_CODES = (
    "durable_store_unreadable",
    "durable_store_corrupt",
    "durable_store_integrity_check_failed",
    "durable_store_unsupported_schema_version",
    "durable_store_schema_version_missing",
    "durable_store_invalid_enum",
    "durable_store_invalid_timestamp",
    "durable_store_invalid_ref",
    "durable_store_fingerprint_mismatch",
    "durable_store_revision_mismatch",
    "durable_store_invalid_exit_code",
    "durable_store_duplicate_identity",
    "durable_store_terminal_without_termination",
    "durable_store_ack_without_admission_correlation",
)

# --- explicit capability declarations ---------------------------------------
# These are declared, not inferred. They exist so the P0 guardrails from issue
# #3082 are asserted as facts rather than left to code reading, and so a future
# change that quietly introduces one of them fails a test.
#
# :data:`PID_SCANNING_SUPPORTED` and
# :data:`UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED` are ``False`` by design: #3081's
# ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` means the runner is the last owner of the
# Job handle, so a dead runner takes its process tree with it. There is no
# surviving unknown process to find, and this module never looks for one.
STORE_RECOMPUTES_FINGERPRINT = False
STORE_MINTS_FINGERPRINT = False
STORE_MINTS_REVISION = False
STORE_PARSE_REVISION = False
STORE_GRANTS_EXECUTION_AUTHORITY = False
TERMINAL_REPLAY_SUPPORTED = False
EXPIRED_COMMAND_REPLAY_SUPPORTED = False
PID_SCANNING_SUPPORTED = False
UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED = False


#: Re-used from the slice-1 record contract rather than restated, so the store
#: cannot drift into a second set of bounds.
MAX_SUMMARY_CHARS = MAX_EVIDENCE_SUMMARY_CHARS
MAX_EVIDENCE_ITEM_COUNT = MAX_EVIDENCE_ITEMS


class DurableRunStoreError(ContractError):
    """A fail-closed durable store refusal carrying a deterministic code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class DurableRunRecoveryClass(str, Enum):
    """How a previously persisted run must be treated after a restart.

    None of these values authorises execution. They are reconciliation outcomes.
    """

    #: Locally terminal *and* server-acknowledged: complete.
    TERMINAL = "terminal"
    #: Locally terminal, server acknowledgement missing (the R8 crash window).
    TERMINAL_SERVER_UNACKED = "terminal_but_server_unacked"
    #: The R6 hard deadline passed; the command is dead, never replayable.
    EXPIRED = "expired"
    #: Admitted but not locally terminal: ambiguous prior execution.
    ADMITTED_NONTERMINAL = "admitted_nonterminal"
    #: Offline-queued metadata awaiting an admissible session.
    OFFLINE_RECONCILIATION_REQUIRED = "offline_reconciliation_required"


_COLUMN_ORDER = (
    "command_id",
    "run_id",
    "tool_request_ref",
    "request_id",
    "revision_ref",
    "device_id",
    "binding_ref",
    "session_id",
    "account_ref",
    "workspace_ref",
    "sequence",
    "credential_generation",
    "request_fingerprint",
    "fingerprint_source",
    "command_issued_at",
    "command_expires_at",
    "admitted_at",
    "started_at",
    "terminated_at",
    "state",
    "termination",
    "server_acknowledged_at",
    "admission_ref",
    "exit_code",
    "offline_state",
    "evidence_diff_ref",
    "evidence_test_ref",
    "evidence_artifact_ref",
    "evidence_evidence_ref",
    "evidence_item_count",
    "evidence_summary",
)

_CREATE_RUN_INDEX = f"CREATE INDEX IF NOT EXISTS {_TABLE}_run_id ON {_TABLE}(run_id)"


def _parse_ts(value: Any, field_name: str) -> datetime:
    """Parse a stored ISO-8601 UTC timestamp, refusing anything ambiguous."""

    if not isinstance(value, str) or not value:
        raise DurableRunStoreError("durable_store_invalid_timestamp", f"{field_name} is empty")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DurableRunStoreError(
            "durable_store_invalid_timestamp", f"{field_name} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DurableRunStoreError(
            "durable_store_invalid_timestamp", f"{field_name} is not timezone-aware"
        )
    return parsed.astimezone(UTC)


def _enum_value(enum_cls: type[Enum], value: Any, code: str, field_name: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise DurableRunStoreError(code, f"{field_name} is not a known value") from exc


def _aware_now(value: Any, field_name: str) -> datetime:
    if isinstance(value, str) or not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DurableRunRecoveryReport:
    """Bounded, secret-free result of classifying the store after a restart."""

    #: Class counts, keyed by `DurableRunRecoveryClass` value.
    classifications: dict[str, int] = field(default_factory=dict)
    #: Exact correlation refs needing human/server reconciliation, stable order.
    reconciliation_command_ids: tuple[str, ...] = ()
    #: Always empty. The store is not a replay engine (issue #3082, restart rules).
    replay_candidates: tuple[str, ...] = ()
    #: Always ``False``. Writing or loading a row never grants execution.
    execution_authority_granted: bool = False

    def safe_dict(self) -> dict[str, Any]:
        return {
            "classifications": dict(sorted(self.classifications.items())),
            "reconciliation_command_ids": list(self.reconciliation_command_ids),
            "replay_candidates": list(self.replay_candidates),
            "execution_authority_granted": self.execution_authority_granted,
            "raw_stdout": False,
            "raw_stderr": False,
            "raw_argv": False,
            "raw_device_credential": False,
            "p01_approval_payload": False,
        }


_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    command_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool_request_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    revision_ref TEXT NOT NULL,
    device_id TEXT NOT NULL,
    binding_ref TEXT NOT NULL,
    session_id TEXT NOT NULL,
    account_ref TEXT NOT NULL,
    workspace_ref TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    credential_generation INTEGER NOT NULL,
    request_fingerprint TEXT NOT NULL,
    fingerprint_source TEXT NOT NULL,
    command_issued_at TEXT NOT NULL,
    command_expires_at TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    started_at TEXT,
    terminated_at TEXT,
    state TEXT NOT NULL,
    termination TEXT,
    server_acknowledged_at TEXT,
    admission_ref TEXT,
    exit_code INTEGER,
    offline_state TEXT NOT NULL,
    evidence_diff_ref TEXT,
    evidence_test_ref TEXT,
    evidence_artifact_ref TEXT,
    evidence_evidence_ref TEXT,
    evidence_item_count INTEGER NOT NULL,
    evidence_summary TEXT NOT NULL
)
"""



class DurableRunStore:
    """Single-writer SQLite store for durable Desktop run records (#3082).

    This follows the existing internal SQLite pattern in this package
    (`SqliteSealedGoogleOAuthStore` and the `claw_automation` store): a plain
    `sqlite3` connection in autocommit mode with explicit `BEGIN IMMEDIATE`
    transactions. It adds no generic database framework.

    Durability choices, and why:

    * **WAL** — the Desktop reads while the runner writes, and a crash between
      the two must not corrupt the log. `journal_mode=WAL` is set once at open.
    * **single writer** — `BEGIN IMMEDIATE` takes the write lock up front so two
      Desktop/runner processes cannot interleave a terminal write. `busy_timeout`
      makes a contending writer wait rather than fail halfway.
    * **schema version** — `PRAGMA user_version` is the single source of truth
      and is checked *before* any table is created or read.
    * **quick_check** — run at open so a corrupt file fails closed instead of
      being silently repaired by a partial write.
    * **atomic terminal persistence** — `record_terminal` writes state,
      termination, timestamp, exit code and evidence in one transaction, so a
      crash can never leave a half-terminal row that recovery would misread.
    """

    def __init__(self, database_path: str | Path) -> None:
        if isinstance(database_path, Path):
            database_path = str(database_path)
        if not isinstance(database_path, str) or not database_path.strip():
            raise ContractError("database_path must be non-empty")
        self._database_path = database_path.strip()
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = self._connect()
        try:
            self._verify_or_create_schema()
        except Exception:
            # Do not leak the handle on a refused open: on Windows an open
            # connection would keep the file locked and the caller could not
            # even inspect or move the very file it was told is corrupt.
            self._db.close()
            raise

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
            raise DurableRunStoreError(
                "durable_store_unreadable", "database could not be opened"
            ) from exc
        try:
            db.row_factory = sqlite3.Row
            # A first-run store must be able to create its file, so the database
            # is created and then verified rather than opened `mode=rw`.
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = FULL")
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.DatabaseError as exc:
            # Close before refusing, so a refused corrupt file is not left locked
            # by a half-open handle on Windows.
            db.close()
            raise DurableRunStoreError(
                "durable_store_corrupt", "database could not be prepared for use"
            ) from exc
        return db

    def _assert_sqlite_header(self) -> None:
        """Distinguish "not a database" from "cannot open" deterministically.

        Relying on the exact wording of a `sqlite3` exception is not a
        deterministic error code, so a file that exists and is non-empty but does
        not carry the SQLite magic header is refused as corrupt up front. A
        zero-length file is a legitimate first run and is left to be created.
        """

        if self._database_path == ":memory:":
            return
        path = Path(self._database_path)
        if not path.exists() or path.stat().st_size == 0:
            return
        try:
            with path.open("rb") as handle:
                header = handle.read(len(_SQLITE_MAGIC))
        except OSError as exc:
            raise DurableRunStoreError(
                "durable_store_unreadable", "database file could not be read"
            ) from exc
        if header != _SQLITE_MAGIC:
            raise DurableRunStoreError(
                "durable_store_corrupt", "database file is not a SQLite database"
            )

    def _verify_or_create_schema(self) -> None:
        self._assert_integrity()
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version == DURABLE_RUN_STORE_SCHEMA_VERSION:
            return
        if version != 0:
            # No silent migration: a runner that does not know this layout must
            # not write into it.
            raise DurableRunStoreError(
                "durable_store_unsupported_schema_version",
                f"schema version {version} is not supported",
            )
        existing = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
        ).fetchone()
        if existing is not None:
            # Rows with no recognised version: someone else's file, or a store
            # written by a build that never stamped a version. Either way its
            # meaning is unknown, so refuse rather than assume.
            raise DurableRunStoreError(
                "durable_store_schema_version_missing",
                "records exist but the schema version is unrecognised",
            )
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(_CREATE_TABLE)
            self._db.execute(_CREATE_RUN_INDEX)
            self._db.execute(f"PRAGMA user_version = {DURABLE_RUN_STORE_SCHEMA_VERSION}")
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def _assert_integrity(self) -> None:
        try:
            result = self._db.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise DurableRunStoreError(
                "durable_store_corrupt", "quick_check could not run"
            ) from exc
        if result is None or result[0] != "ok":
            raise DurableRunStoreError(
                "durable_store_integrity_check_failed",
                f"quick_check reported {result!r}",
            )


    # --- row mapping ---------------------------------------------------------

    @staticmethod
    def _to_row(record: DurableRunRecord) -> dict[str, Any]:
        evidence = record.evidence
        return {
            "command_id": record.command_id,
            "run_id": record.run_id,
            "tool_request_ref": record.tool_request_ref,
            "request_id": record.request_id,
            "revision_ref": record.revision_ref,
            "device_id": record.device_id,
            "binding_ref": record.binding_ref,
            "session_id": record.session_id,
            "account_ref": record.account_ref,
            "workspace_ref": record.workspace_ref,
            "sequence": record.sequence,
            "credential_generation": record.credential_generation,
            "request_fingerprint": record.request_fingerprint,
            "fingerprint_source": record.fingerprint_source,
            "command_issued_at": _iso(record.command_issued_at),
            "command_expires_at": _iso(record.command_expires_at),
            "admitted_at": _iso(record.admitted_at),
            "started_at": _iso(record.started_at) if record.started_at else None,
            "terminated_at": _iso(record.terminated_at) if record.terminated_at else None,
            "state": record.state.value,
            "termination": record.termination.value if record.termination else None,
            "server_acknowledged_at": (
                _iso(record.server_acknowledged_at) if record.server_acknowledged_at else None
            ),
            "admission_ref": record.admission_ref,
            "exit_code": record.exit_code,
            "offline_state": record.offline_state.value,
            "evidence_diff_ref": evidence.diff_ref,
            "evidence_test_ref": evidence.test_ref,
            "evidence_artifact_ref": evidence.artifact_ref,
            "evidence_evidence_ref": evidence.evidence_ref,
            "evidence_item_count": evidence.item_count,
            "evidence_summary": evidence.summary,
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DurableRunRecord:
        def ref(field_name: str) -> str:
            try:
                return _ref(row[field_name], field_name)
            except ContractError as exc:
                raise DurableRunStoreError(
                    "durable_store_invalid_ref", f"{field_name} is not a safe reference"
                ) from exc

        def optional_ref(field_name: str) -> str | None:
            value = row[field_name]
            return None if value is None else ref(field_name)

        try:
            fingerprint = _digest(row["request_fingerprint"], "request_fingerprint")
        except ContractError as exc:
            raise DurableRunStoreError(
                "durable_store_fingerprint_mismatch",
                "stored request_fingerprint is not a canonical digest",
            ) from exc
        try:
            revision_ref = _ref(row["revision_ref"], "revision_ref")
        except ContractError as exc:
            raise DurableRunStoreError(
                "durable_store_revision_mismatch",
                "stored revision_ref is not a safe opaque reference",
            ) from exc

        exit_code = row["exit_code"]
        if exit_code is not None:
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                raise DurableRunStoreError(
                    "durable_store_invalid_exit_code", "exit_code is not an integer"
                )
            if not MIN_BOUNDED_EXIT_CODE <= exit_code <= MAX_BOUNDED_EXIT_CODE:
                raise DurableRunStoreError(
                    "durable_store_invalid_exit_code", "exit_code is out of bounds"
                )

        summary = row["evidence_summary"]
        if not isinstance(summary, str) or len(summary) > MAX_SUMMARY_CHARS:
            raise DurableRunStoreError(
                "durable_store_invalid_ref", "evidence summary is not bounded"
            )
        item_count = row["evidence_item_count"]
        if isinstance(item_count, bool) or not isinstance(item_count, int):
            raise DurableRunStoreError(
                "durable_store_invalid_enum", "evidence item_count is not an integer"
            )
        if not 0 <= item_count <= MAX_EVIDENCE_ITEM_COUNT:
            raise DurableRunStoreError(
                "durable_store_invalid_enum", "evidence item_count is out of bounds"
            )

        state = _enum_value(
            DurableRunState, row["state"], "durable_store_invalid_enum", "state"
        )
        offline_state = _enum_value(
            DurableRunOfflineState,
            row["offline_state"],
            "durable_store_invalid_enum",
            "offline_state",
        )
        termination = (
            _enum_value(
                DurableRunTermination,
                row["termination"],
                "durable_store_invalid_enum",
                "termination",
            )
            if row["termination"] is not None
            else None
        )
        if state is DurableRunState.TERMINAL and termination is None:
            raise DurableRunStoreError(
                "durable_store_terminal_without_termination",
                "a stored terminal row has no termination reason",
            )


        try:
            return DurableRunRecord(
                command_id=ref("command_id"),
                run_id=ref("run_id"),
                tool_request_ref=ref("tool_request_ref"),
                request_id=ref("request_id"),
                revision_ref=revision_ref,
                device_id=ref("device_id"),
                binding_ref=ref("binding_ref"),
                session_id=ref("session_id"),
                account_ref=ref("account_ref"),
                workspace_ref=ref("workspace_ref"),
                sequence=row["sequence"],
                credential_generation=row["credential_generation"],
                request_fingerprint=fingerprint,
                fingerprint_source=ref("fingerprint_source"),
                command_issued_at=_parse_ts(row["command_issued_at"], "command_issued_at"),
                command_expires_at=_parse_ts(row["command_expires_at"], "command_expires_at"),
                admitted_at=_parse_ts(row["admitted_at"], "admitted_at"),
                started_at=(
                    _parse_ts(row["started_at"], "started_at")
                    if row["started_at"] is not None
                    else None
                ),
                terminated_at=(
                    _parse_ts(row["terminated_at"], "terminated_at")
                    if row["terminated_at"] is not None
                    else None
                ),
                state=state,
                termination=termination,
                server_acknowledged_at=(
                    _parse_ts(row["server_acknowledged_at"], "server_acknowledged_at")
                    if row["server_acknowledged_at"] is not None
                    else None
                ),
                admission_ref=optional_ref("admission_ref"),
                exit_code=exit_code,
                offline_state=offline_state,
                evidence=BoundedEvidenceProjection(
                    diff_ref=optional_ref("evidence_diff_ref"),
                    test_ref=optional_ref("evidence_test_ref"),
                    artifact_ref=optional_ref("evidence_artifact_ref"),
                    evidence_ref=optional_ref("evidence_evidence_ref"),
                    item_count=item_count,
                    summary=summary,
                ),
            )
        except DurableRunStoreError:
            raise
        except ContractError as exc:
            # A row that cannot satisfy the slice-1 contract is corrupt, not a
            # record we are free to reinterpret.
            raise DurableRunStoreError(
                "durable_store_invalid_ref", f"stored row violates the record contract: {exc}"
            ) from exc


    # --- writes --------------------------------------------------------------

    def put(self, record: DurableRunRecord) -> None:
        """Insert one admitted run record.

        This records an already-decided admission. It is not an admission
        decision: a `DurableRunRecord` can only be built from correlation the
        canonical path already issued.
        """

        if not isinstance(record, DurableRunRecord):
            raise ContractError("record must be DurableRunRecord")
        row = self._to_row(record)
        columns = ", ".join(_COLUMN_ORDER)
        placeholders = ", ".join(f":{name}" for name in _COLUMN_ORDER)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                f"INSERT INTO {_TABLE}({columns}) VALUES({placeholders})", row
            )
            self._db.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            self._db.execute("ROLLBACK")
            raise DurableRunStoreError(
                "durable_store_duplicate_identity",
                "a record with this command_id already exists",
            ) from exc
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def record_terminal(self, record: DurableRunRecord) -> None:
        """Atomically persist a locally terminal outcome for an existing row.

        State, termination reason, timestamp, bounded exit code and bounded
        evidence all land in a single transaction, so a crash leaves the row
        either fully non-terminal or fully terminal — never a half-written state
        that recovery would have to guess about.
        """

        if not isinstance(record, DurableRunRecord):
            raise ContractError("record must be DurableRunRecord")
        if not record.terminal:
            raise ContractError("record_terminal requires a locally terminal record")
        row = self._to_row(record)
        assignments = ", ".join(
            f"{name}=:{name}" for name in _COLUMN_ORDER if name != "command_id"
        )
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._db.execute(
                f"SELECT state FROM {_TABLE} WHERE command_id = ?", (record.command_id,)
            ).fetchone()
            if existing is None:
                raise DurableRunStoreError(
                    "durable_store_duplicate_identity",
                    "no admitted record exists for this command_id",
                )
            if existing[0] == DurableRunState.TERMINAL.value:
                # A recorded local outcome is never overwritten: that would let
                # a later writer erase the R8 terminal fact.
                raise ContractError(
                    "a terminal run outcome is already durable and is never overwritten"
                )
            self._db.execute(
                f"UPDATE {_TABLE} SET {assignments} WHERE command_id = :command_id", row
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise


    def acknowledge(self, *, command_id: str, acknowledged_at: datetime) -> None:
        """Record the orthogonal server acknowledgement for a terminal run.

        This is the only method that writes `server_acknowledged_at`, and it
        refuses to write it for a non-terminal run. A missing acknowledgement is
        never treated as retry authority: this method only ever *adds* the server
        fact, it never removes the local one.
        """

        try:
            key = _ref(command_id, "command_id")
            stamp = _iso(acknowledged_at)
        except ContractError as exc:
            raise DurableRunStoreError(
                "durable_store_invalid_ref",
                "command acknowledgement is not a safe reference",
            ) from exc
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._db.execute(
                f"SELECT state, admission_ref, terminated_at, admitted_at, command_expires_at "
                f"FROM {_TABLE} WHERE command_id = ?",
                (key,),
            ).fetchone()
            if existing is None:
                raise DurableRunStoreError(
                    "durable_store_duplicate_identity", "no record exists for this command_id"
                )
            if existing[0] != DurableRunState.TERMINAL.value:
                raise DurableRunStoreError(
                    "durable_store_ack_without_admission_correlation",
                    "a server acknowledgement cannot precede a local terminal outcome",
                )
            if existing[1] is None or existing[2] is None:
                raise DurableRunStoreError(
                    "durable_store_ack_without_admission_correlation",
                    "a server acknowledgement requires admission and termination correlation",
                )
            acknowledged = _parse_ts(stamp, "server_acknowledged_at")
            if acknowledged < _parse_ts(existing[3], "admitted_at"):
                raise DurableRunStoreError(
                    "durable_store_invalid_timestamp",
                    "server acknowledgement cannot predate admitted_at",
                )
            if acknowledged >= _parse_ts(existing[4], "command_expires_at"):
                raise DurableRunStoreError(
                    "durable_store_invalid_timestamp",
                    "server acknowledgement cannot be at or after the command hard deadline",
                )
            self._db.execute(
                f"UPDATE {_TABLE} SET server_acknowledged_at = ? WHERE command_id = ?",
                (stamp, key),
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise


    # --- reads and restart recovery -----------------------------------------

    def get(self, *, command_id: str) -> DurableRunRecord | None:
        """Load one record by its durable primary key (`command_id`)."""

        try:
            key = _ref(command_id, "command_id")
        except ContractError as exc:
            raise DurableRunStoreError(
                "durable_store_invalid_ref", "command_id is not a safe reference"
            ) from exc
        row = self._db.execute(
            f"SELECT * FROM {_TABLE} WHERE command_id = ?", (key,)
        ).fetchone()
        return None if row is None else self._from_row(row)

    def list_records(self, *, run_id: str | None = None) -> tuple[DurableRunRecord, ...]:
        """Load every stored record, optionally narrowed to one `run_id`."""

        if run_id is None:
            rows = self._db.execute(f"SELECT * FROM {_TABLE} ORDER BY command_id").fetchall()
        else:
            try:
                key = _ref(run_id, "run_id")
            except ContractError as exc:
                raise DurableRunStoreError(
                    "durable_store_invalid_ref", "run_id is not a safe reference"
                ) from exc
            rows = self._db.execute(
                f"SELECT * FROM {_TABLE} WHERE run_id = ? ORDER BY command_id", (key,)
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def classify(record: DurableRunRecord, *, now: datetime) -> DurableRunRecoveryClass:
        """Classify one loaded record for reconciliation after a restart.

        Deliberately free of any execution verdict. Ordering of the checks is the
        contract: a locally terminal fact outranks a passed deadline, and a
        passed deadline outranks an unfinished row.
        """

        if not isinstance(record, DurableRunRecord):
            raise ContractError("record must be DurableRunRecord")
        moment = _aware_now(now, "now")
        if record.state is DurableRunState.TERMINAL:
            # R8: local terminality is durable. Whether the server acknowledged
            # it is an orthogonal fact and never changes the terminal class.
            if record.acknowledged:
                return DurableRunRecoveryClass.TERMINAL
            return DurableRunRecoveryClass.TERMINAL_SERVER_UNACKED
        if record.hard_deadline_passed(now=moment):
            # R6: the hard deadline is not renewable and never re-armable.
            return DurableRunRecoveryClass.EXPIRED
        if record.offline_state is not DurableRunOfflineState.IDLE:
            return DurableRunRecoveryClass.OFFLINE_RECONCILIATION_REQUIRED
        return DurableRunRecoveryClass.ADMITTED_NONTERMINAL

    def recover(self, *, now: datetime) -> DurableRunRecoveryReport:
        """Classify the whole store after a restart.

        This is *not* a replay engine. `replay_candidates` is always empty and
        `execution_authority_granted` is always `False`: ambiguous prior
        execution is reported for reconciliation and is never re-executed here.
        """

        moment = _aware_now(now, "now")
        counts: dict[str, int] = {}
        reconciliation: list[str] = []
        for record in self.list_records():
            classification = self.classify(record, now=moment)
            key = classification.value
            counts[key] = counts.get(key, 0) + 1
            if classification is not DurableRunRecoveryClass.TERMINAL:
                reconciliation.append(record.command_id)
        return DurableRunRecoveryReport(
            classifications=counts,
            reconciliation_command_ids=tuple(sorted(reconciliation)),
            replay_candidates=(),
            execution_authority_granted=False,
        )


    # --- retention -----------------------------------------------------------

    def collect_garbage(self, *, now: datetime, max_age: timedelta) -> tuple[str, ...]:
        """Delete only provably finished, acknowledged, old records.

        Retention follows the R8 retention hold: a terminal record whose server
        acknowledgement is still missing is *never* collected, because that
        missing ack is precisely the state a human may need to look at. Records
        that are non-terminal, or terminal-without-ack, or recently terminated
        are all kept. GC therefore cannot destroy uncertainty evidence.
        """

        moment = _aware_now(now, "now")
        if isinstance(max_age, str) or not isinstance(max_age, timedelta) or max_age <= timedelta(0):
            raise ContractError("max_age must be a positive timedelta")
        collected: list[str] = []
        self._db.execute("BEGIN IMMEDIATE")
        try:
            rows = self._db.execute(
                f"SELECT command_id, state, server_acknowledged_at, terminated_at FROM {_TABLE}"
            ).fetchall()
            for row in rows:
                if row["state"] != DurableRunState.TERMINAL.value:
                    continue
                if row["server_acknowledged_at"] is None:
                    continue
                if row["terminated_at"] is None:
                    continue
                try:
                    terminated_at = _parse_ts(row["terminated_at"], "terminated_at")
                except DurableRunStoreError:
                    # Unparseable retention metadata is a corruption signal, not
                    # a licence to delete.
                    continue
                if (moment - terminated_at) < max_age:
                    continue
                self._db.execute(
                    f"DELETE FROM {_TABLE} WHERE command_id = ?", (row["command_id"],)
                )
                collected.append(row["command_id"])
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return tuple(sorted(collected))
