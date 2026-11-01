"""#5881 follow-on — the schema of the 컴2 PC queue database.

Only the migrations that own the tables the queue is responsible for are applied here:
`oracle_mesh_dispatch` (047·048·049·063·074), `mesh_device_presence` (067·070) and the
pairing directory `pc_pairing_codes` + `pc_device_links` (072·073), and the latest
drive inventory `mesh_device_drives` (086). Conversation rows —
runs, messages, tool calls, the preferred-PC selection — stay in Cloudflare D1, which is
the split the design was approved on.

The files are applied in name order, exactly as the D1 migration ledger applies them, so a
column that a guard depends on cannot be missing on one side only. They are also applied at
most ONCE per database, for the same reason D1 has a ledger: these files are not
idempotent. 048 ends with `ALTER TABLE ... ADD COLUMN kind`, which fails on a table that
already has `kind`, and 063·070 rebuild their table by `DROP` + `RENAME`. Before this file
kept a ledger, the queue re-ran all nine files at every open, which meant the service could
only ever start on a database it had just created itself — the first restart of the 컴2
queue after its state copy, on 2026-10-30, crash-looped on `duplicate column name: kind`
and served nobody until the database was rebuilt.

`queue_schema_applied` is that ledger. Three cases matter:

- a database created by this code: each file runs once and is recorded;
- a database built before the ledger existed (its tables are there, the ledger is empty):
  the files have already run, so the ledger is backfilled and nothing is replayed;
- a file that is not in the ledger yet: it runs, and a statement whose effect the database
  already reports (`duplicate column name`, `already exists`) is tolerated so a run
  interrupted halfway can never wedge startup — the shape check at the end is what proves
  the database is really complete, so tolerance cannot hide a missing column.

A recorded file whose text later changed is skipped, not replayed — that is what D1 does
with an applied migration — and the file is named on stderr, because silently disagreeing
with D1 about a schema is the failure this whole file exists to prevent.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import pathlib
import sqlite3
import sys
from typing import Any

from app.d1_sqlite import SqliteD1, connect


def migration_dir(base: pathlib.Path | None = None) -> pathlib.Path:
    """Where the Chat migrations are, in whichever layout this file is running.

    The repository layout puts this file at apps/padiem-mesh-queue/schema.py, one level
    below the Chat app. On 컴2 the same file is installed at $ROOT/schema.py, where that
    relative path would be /opt/padiem/padiem-chat — so the installed `app` link is
    used instead: $ROOT/app resolves to <chat>/app, and its parent holds migrations.
    An explicit MESH_QUEUE_MIGRATIONS_DIR wins over both.
    """

    override = os.environ.get("MESH_QUEUE_MIGRATIONS_DIR", "").strip()
    if override:
        return pathlib.Path(override)
    here = pathlib.Path(base) if base is not None else pathlib.Path(__file__).resolve().parent
    # Resolve the app link and take its parent: "../" after a symlink is lexical on
    # Windows and physical on Linux, and this file runs on both.
    through_app = here / "app"
    if through_app.is_dir():
        candidate = through_app.resolve().parent / "migrations"
        if candidate.is_dir():
            return candidate
    return here.parent / "padiem-chat" / "migrations"


MIGRATION_DIR = migration_dir()

QUEUE_MIGRATIONS = (
    "047_oracle_mesh_dispatch.sql",
    "048_oracle_mesh_command.sql",
    "049_oracle_mesh_command_result_meta.sql",
    "063_oracle_mesh_dispatch_tool_call_scope.sql",
    "067_mesh_device_presence.sql",
    "070_mesh_device_presence_source.sql",
    "072_pc_device_pairing.sql",
    "073_pc_device_link_pause.sql",
    "074_oracle_mesh_dispatch_claim_lease.sql",
    "086_mesh_device_drives.sql",
)

QUEUE_TABLES = (
    "oracle_mesh_dispatch",
    "mesh_device_presence",
    "pc_pairing_codes",
    "pc_device_links",
    "mesh_device_drives",
)

#: The ledger itself, plus the columns the queue's own SQL reads. A database that lacks any
#: of these is not a database the stores can serve, whatever the ledger says.
LEDGER_TABLE = "queue_schema_applied"

REQUIRED_COLUMNS = {
    "oracle_mesh_dispatch": (
        "kind",
        "command_text",
        "termination",
        "exit_code",
        "tool_call_ref",
        "claimed_until",
    ),
    "mesh_device_presence": ("device_id", "connected", "received_at", "source"),
    "pc_pairing_codes": ("code_id", "state", "mesh_node_id", "expires_at"),
    "pc_device_links": ("link_id", "state", "roots_json", "paused_at"),
    "mesh_device_drives": ("device_id", "drives_json", "received_at"),
}

__all__ = [
    "LEDGER_TABLE",
    "MIGRATION_DIR",
    "QUEUE_MIGRATIONS",
    "QUEUE_TABLES",
    "REQUIRED_COLUMNS",
    "QueueSchemaIncomplete",
    "apply",
    "open_queue",
]


class QueueSchemaIncomplete(RuntimeError):
    """The database does not have the shape the queue's stores depend on.

    Raised instead of letting a service start that would fail on its first real call.
    """


def _statements(sql: str) -> list[str]:
    """The file's statements, whole.

    ``executescript`` runs a file as one opaque blob, which is exactly why a repeat run
    could not be reasoned about per statement. ``sqlite3.complete_statement`` is SQLite's
    own "is this terminated" answer, so a semicolon inside a string literal or a trigger
    body cannot split a statement in half.
    """

    parts: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            parts.append(buffer)
            buffer = ""
    if buffer.strip():
        parts.append(buffer)
    return parts


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _already_satisfied(message: str) -> bool:
    """Whether a rejected statement describes something the database already has."""

    return message.startswith("duplicate column name:") or "already exists" in message


def _table_names(connection: Any) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("select name from sqlite_master where type = 'table'")
    }


def _ensure_ledger(connection: Any) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS %s ("
        " name TEXT PRIMARY KEY,"
        " sha256 TEXT NOT NULL,"
        " applied_at TEXT NOT NULL)" % LEDGER_TABLE
    )


def _ledger(connection: Any) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in connection.execute("select name, sha256 from %s" % LEDGER_TABLE)
    }


def _record(connection: Any, name: str, digest: str) -> None:
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    connection.execute(
        "INSERT OR REPLACE INTO %s (name, sha256, applied_at) VALUES (?, ?, ?)" % LEDGER_TABLE,
        (name, digest, stamp),
    )


def _settle(connection: Any) -> None:
    """Finish one migration file as one unit.

    The service's own connection is autocommit, where this is a no-op. A caller that opens
    the database with Python's default isolation is not: without it the ledger row and the
    DDL that follows it would sit in one implicit transaction and vanish on close, which is
    how a test helper building a database would end up with no tables at all.
    """

    commit = getattr(connection, "commit", None)
    if callable(commit):
        commit()


def _discard(connection: Any) -> None:
    rollback = getattr(connection, "rollback", None)
    if callable(rollback):
        rollback()


def _require_shape(connection: Any) -> None:
    missing: list[str] = []
    present = _table_names(connection)
    for table in QUEUE_TABLES:
        if table not in present:
            missing.append(table)
            continue
        columns = {str(row[1]) for row in connection.execute("pragma table_info(%s)" % table)}
        missing.extend(
            "%s.%s" % (table, column)
            for column in REQUIRED_COLUMNS[table]
            if column not in columns
        )
    if missing:
        raise QueueSchemaIncomplete(
            "queue database is missing: %s" % ", ".join(sorted(missing))
        )


def apply(connection, *, migrations: tuple[str, ...] = QUEUE_MIGRATIONS) -> None:
    texts: dict[str, str] = {}
    for name in migrations:
        path = MIGRATION_DIR / name
        if not path.is_file():
            raise FileNotFoundError("queue migration missing: %s" % path)
        texts[name] = path.read_text(encoding="utf-8")

    _ensure_ledger(connection)
    recorded = _ledger(connection)
    # The pre-ledger deployment owned the first nine migrations. An additive
    # table introduced later (086) must not make those destructive table rebuilds
    # replay on an old database whose ledger has not been backfilled yet.
    legacy_tables = ("oracle_mesh_dispatch", "mesh_device_presence",
                     "pc_pairing_codes", "pc_device_links")
    if not recorded and all(table in _table_names(connection) for table in legacy_tables):
        # Built by the version of this file that had no ledger: the statements have
        # already run here, so replaying them would fail on the first ALTER.
        for name in migrations:
            if name not in QUEUE_MIGRATIONS[:9]:
                continue
            _record(connection, name, _digest(texts[name]))
        recorded = _ledger(connection)
        _settle(connection)

    for name in migrations:
        digest = _digest(texts[name])
        if name in recorded:
            if recorded[name] != digest:
                print(
                    "queue schema drift: %s changed after it was applied; this database"
                    " keeps the version the ledger recorded" % name,
                    file=sys.stderr,
                )
            continue
        try:
            for statement in _statements(texts[name]):
                try:
                    connection.execute(statement)
                except sqlite3.OperationalError as exc:
                    if not _already_satisfied(str(exc)):
                        raise
            _record(connection, name, digest)
        except Exception:
            # Nothing of this file is left behind, so the next open replays it from the
            # start rather than from its middle.
            _discard(connection)
            raise
        _settle(connection)

    _require_shape(connection)


def open_queue(path: str):
    """Open (creating if needed) the queue database and its D1-shaped surface."""

    connection = connect(path)
    apply(connection)
    return connection, SqliteD1(connection)
