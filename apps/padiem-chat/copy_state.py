#!/usr/bin/env python3
"""Stage-3 preparation — copy a D1 export into the COM2 Chat SQLite database.

PREPARED ONLY. Nothing in this PR runs it; the cutover step that uses it waits
for the CTO's instruction. The shape follows the mesh queue's copy_state.py:

* the source is a READ-ONLY D1 export (a SQLite file produced by the reviewed
  export path), and every source table must already exist in the target — a
  missing table stops the run instead of wiping a lane;
* each table is replaced in ONE transaction: either all of its rows move or the
  previous content stays;
* the report carries counts and row hashes only — a chat row holds a person's
  text, and none of it is printed;
* a snapshot table records every copied row's hash, so a later diff can name
  exactly what changed on the target since the copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone

SNAPSHOT_TABLE = "chat_copy_snapshot"
#: Never copied: SQLite internals, the export's own bookkeeping, and our own
#: local migration ledger (the target's schema state is owned by it).
SKIP_TABLES = {"d1_migrations", "sqlite_sequence", "padiem_local_migration_ledger"}

__all__ = ["SNAPSHOT_TABLE", "SKIP_TABLES", "copy_state", "row_hash", "source_tables"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def source_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [str(row[0]) for row in rows]
    return [name for name in names if name not in SKIP_TABLES and not name.startswith("sqlite_")]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info('{table}')")]


def _key_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    keys = [
        str(row[1]) for row in connection.execute(f"PRAGMA table_info('{table}')")
        if int(row[5]) > 0
    ]
    if not keys:
        raise SystemExit(f"CHAT_COPY=REFUSED reason=no_primary_key table={table}")
    return keys


def row_hash(columns: list[str], row: tuple) -> str:
    """One digest of a whole row; column names are part of the digest."""

    payload = json.dumps(
        {name: value for name, value in zip(columns, row)},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def copy_state(
    source_path: str, target_path: str, *, tables: tuple[str, ...] | None = None
) -> dict[str, dict]:
    """Replace each named table on the target with the export's rows, then verify."""

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path, isolation_level=None)
    try:
        chosen = tables or tuple(source_tables(source))
        existing = set(source_tables(target))
        missing = [table for table in chosen if table not in existing]
        if missing:
            raise SystemExit(
                "CHAT_COPY=REFUSED reason=target_table_missing tables=" + ",".join(missing)
            )
        target.execute(
            f"CREATE TABLE IF NOT EXISTS {SNAPSHOT_TABLE} ("
            "table_name TEXT NOT NULL, row_key TEXT NOT NULL, row_sha256 TEXT NOT NULL,"
            " copied_at TEXT NOT NULL, PRIMARY KEY (table_name, row_key))"
        )
        report: dict[str, dict] = {}
        copied_at = _now()
        for table in chosen:
            columns = _columns(source, table)
            target_columns = _columns(target, table)
            if columns != target_columns:
                raise SystemExit(f"CHAT_COPY=REFUSED reason=column_mismatch table={table}")
            keys = _key_columns(source, table)
            key_index = [columns.index(key) for key in keys]
            rows = source.execute(f"SELECT * FROM {table}").fetchall()
            target.execute("BEGIN")
            try:
                target.execute(f"DELETE FROM {table}")
                placeholders = ",".join("?" for _ in columns)
                target.executemany(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                    rows,
                )
                target.execute(f"DELETE FROM {SNAPSHOT_TABLE} WHERE table_name = ?", (table,))
                target.executemany(
                    f"INSERT INTO {SNAPSHOT_TABLE} (table_name, row_key, row_sha256, copied_at)"
                    " VALUES (?, ?, ?, ?)",
                    [
                        (
                            table,
                            "|".join(str(row[index]) for index in key_index),
                            row_hash(columns, row),
                            copied_at,
                        )
                        for row in rows
                    ],
                )
                target.execute("COMMIT")
            except Exception:
                target.execute("ROLLBACK")
                raise
            moved = target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if moved != len(rows):
                raise SystemExit(f"CHAT_COPY=REFUSED reason=row_count_mismatch table={table}")
            report[table] = {"rows": len(rows), "sha256": _table_digest(columns, rows)}
        return report
    finally:
        source.close()
        target.close()


def _table_digest(columns: list[str], rows: list[tuple]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row_hash(columns, row).encode("ascii"))
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    copy = sub.add_parser("copy")
    copy.add_argument("--source", required=True, help="read-only D1 export (.sqlite3)")
    copy.add_argument("--target", required=True, help="COM2 chat.sqlite3")
    copy.add_argument("--tables", default="", help="comma-separated subset (default: all)")
    args = parser.parse_args(argv)
    if args.command != "copy":  # pragma: no cover - argparse enforces this
        return 2
    chosen = tuple(item.strip() for item in args.tables.split(",") if item.strip()) or None
    report = copy_state(args.source, args.target, tables=chosen)
    for table, stats in sorted(report.items()):
        print(f"CHAT_COPY_TABLE={table} ROWS={stats['rows']} SHA256={stats['sha256'][:16]}")
    print(f"CHAT_COPY=PASS TABLES={len(report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
