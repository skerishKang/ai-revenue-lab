"""Shared read-only row-digest primitives for D1 <-> COM2 Chat comparisons.

Two tools answer questions about the same thing — "does this row exist on the
other side, and is it the same row?":

* ``chat_d1_handback_gate.py`` (#6358) — the rollback path: which rows COM2
  accepted after the cutover freeze, measured against the baseline snapshot.
* ``chat_copy_parity.py`` — the sync verdict: whether a D1 export copy and the
  COM2 database currently hold the same rows.

One implementation, so a rollback plan and a parity verdict can never disagree
about what "the same row" means. Everything here is read-only: connections use
``mode=ro`` URIs, so SQLite itself refuses a write. Nothing in this module
prints row content; callers see table names, counts and digests only.

Scope constants live here too: tables owned by another authority never take
part in either comparison. The COM2 queue owns dispatch, pairing and presence
(#6115/#6121); the Stage 2-C broker owns ``local_agent_*``; migration ledgers
are bookkeeping on both sides.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

#: COM2 queue authority — never compared and never overwritten by a handback.
OWNED_BY_QUEUE = frozenset({
    "oracle_mesh_dispatch",
    "mesh_device_presence",
    "pc_pairing_codes",
    "pc_device_links",
})
#: Stage 2-C broker storage.
OWNED_BY_BROKER = frozenset({
    "local_agent_broker_state",
    "local_agent_broker_used_command_id",
    "local_agent_command_material",
    "local_agent_http_session",
    "local_agent_office_artifact",
    "local_agent_office_part",
    "local_agent_text_result",
})
#: Bookkeeping that never travels as data.
SYSTEM_TABLES = frozenset({
    "d1_migrations",
    "padiem_local_migration_ledger",
    "chat_copy_snapshot",
    "chat_migration_runs",
    "chat_migration_summary",
    "chat_migration_snapshot",
})
SKIP_TABLES = OWNED_BY_QUEUE | OWNED_BY_BROKER | SYSTEM_TABLES


class GateError(ValueError):
    """A fixed, public-safe refusal. Never carries SQL bodies or row data."""


def read_only(path: str | Path) -> sqlite3.Connection:
    """Open an existing SQLite file so that SQLite itself refuses writes."""

    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise GateError("CHAT_HANDBACK_FILE_MISSING")
    return sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)


def tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]


def columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]


def key_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    """Primary-key columns in declared order. Empty when the table has none."""

    found = [
        (int(row[5]), str(row[1]))
        for row in connection.execute(f'PRAGMA table_info("{table}")')
        if int(row[5]) > 0
    ]
    found.sort()
    return [name for _position, name in found]


def row_digest(columns_of_table: list[str], row: tuple) -> str:
    """A stable identity for one row: column names plus stringified values."""

    payload = json.dumps(
        [columns_of_table, [None if value is None else str(value) for value in row]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def key_text(parts) -> str:
    return json.dumps([None if part is None else str(part) for part in parts])


def rows(connection: sqlite3.Connection, table: str) -> tuple[list[str], dict[str, tuple]]:
    """``(columns, {key_text: row})`` for a table that has a primary key."""

    names = columns(connection, table)
    keys = key_columns(connection, table)
    if not keys:
        raise GateError("CHAT_HANDBACK_NO_PRIMARY_KEY")
    key_indexes = [names.index(name) for name in keys]
    selected = ", ".join(f'"{name}"' for name in names)
    found: dict[str, tuple] = {}
    for row in connection.execute(f'SELECT {selected} FROM "{table}"'):
        found[key_text([row[index] for index in key_indexes])] = row
    return names, found


def comparable_tables(connection: sqlite3.Connection) -> list[str]:
    return [name for name in tables(connection) if name not in SKIP_TABLES]


def snapshot(path: str | Path) -> dict[str, dict[str, str]]:
    """Per-table ``{key: row digest}`` for every comparable table."""

    connection = read_only(path)
    try:
        names = comparable_tables(connection)
        if not names:
            raise GateError("CHAT_HANDBACK_NO_TABLES")
        out: dict[str, dict[str, str]] = {}
        for table in names:
            table_columns, found = rows(connection, table)
            out[table] = {
                key: row_digest(table_columns, row) for key, row in found.items()
            }
        return out
    finally:
        connection.close()


def file_sha256(path: str | Path) -> str:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise GateError("CHAT_HANDBACK_FILE_MISSING")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
