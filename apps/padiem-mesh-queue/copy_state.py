#!/usr/bin/env python3
"""#5881 follow-on — copy the PC-lane state from the D1 export into the queue, and be
able to say afterwards exactly what changed on the queue since that copy.

Why a snapshot instead of a write-path journal: the pairing and presence write paths stay
untouched, so nothing new can be missed, and nothing is added to a code path that a
customer is waiting on. The copy records a hash of every row it moved; a later `diff`
against that snapshot IS the list of pairing changes made during the switch, which is what
a rollback needs to hand back to D1.

Safety rules this tool refuses to break:
* the source is a read-only D1 export (a SQLite file produced by scripts/ops/refresh_d1.py)
  and must contain every table named - a missing table stops the run rather than an empty
  table wiping the queue;
* the copy is one transaction per table: it either fully replaces the table's rows or
  leaves the previous content in place;
* nothing prints row content. Counts and hashes only - a link row carries a machine name
  and a folder path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone

TABLES = ("pc_pairing_codes", "pc_device_links", "mesh_device_presence")
SNAPSHOT_TABLE = "queue_copy_snapshot"
#: Columns that identify a row. A row whose identity columns collide across the two
#: databases is not the same row, so the copy refuses instead of guessing.
KEY_COLUMNS = {
    "pc_pairing_codes": ("code_sha256",),
    "pc_device_links": ("link_id",),
    "mesh_device_presence": ("device_id",),
}

__all__ = ["KEY_COLUMNS", "SNAPSHOT_TABLE", "TABLES", "copy_state", "diff_state",
           "row_hash"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute("PRAGMA table_info(%s)" % table)]


def row_hash(columns: list[str], row: tuple) -> str:
    """One digest of a whole row. Columns are named in it, so a reordered column
    cannot hide a difference."""

    payload = json.dumps({name: value for name, value in zip(columns, row)},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_snapshot(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS %s (table_name TEXT NOT NULL, row_key TEXT NOT NULL,"
        " row_sha256 TEXT NOT NULL, copied_at TEXT NOT NULL,"
        " PRIMARY KEY (table_name, row_key))" % SNAPSHOT_TABLE)


def _read_rows(source: sqlite3.Connection, table: str):
    columns = _columns(source, table)
    rows = source.execute("SELECT * FROM %s" % table).fetchall()
    return columns, rows


def copy_state(source_path: str, target_path: str,
               tables: tuple[str, ...] = TABLES) -> dict:
    """Replace each named table in the queue with the export's rows, then verify."""

    source = sqlite3.connect("file:%s?mode=ro" % source_path, uri=True)
    target = sqlite3.connect(target_path, isolation_level=None)
    report: dict[str, dict] = {}
    try:
        source_names = {str(row[0]) for row in
                        source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [table for table in tables if table not in source_names]
        if missing:
            raise RuntimeError("the D1 export is missing tables: %s" % ",".join(missing))
        _ensure_snapshot(target)
        for table in tables:
            columns, rows = _read_rows(source, table)
            keys = KEY_COLUMNS[table]
            absent = [key for key in keys if key not in columns]
            if absent:
                raise RuntimeError("%s is missing key columns %s" % (table, absent))
            digests: list[tuple[str, str, str, str]] = []
            for row in rows:
                record = dict(zip(columns, row))
                key = str(record[keys[0]])
                digests.append((table, key, row_hash(columns, row), _now()))
            with target:
                target.execute("DELETE FROM %s" % table)
                if rows:
                    placeholders = ",".join("?" * len(columns))
                    quoted = ",".join('"%s"' % name for name in columns)
                    target.executemany(
                        "INSERT INTO %s (%s) VALUES (%s)" % (table, quoted, placeholders),
                        rows)
                target.execute("DELETE FROM %s WHERE table_name=?" % SNAPSHOT_TABLE,
                               (table,))
                target.executemany(
                    "INSERT INTO %s (table_name, row_key, row_sha256, copied_at)"
                    " VALUES (?,?,?,?)" % SNAPSHOT_TABLE, digests)
            moved = target.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            reported = target.execute(
                "SELECT COUNT(*) FROM %s WHERE table_name=?" % SNAPSHOT_TABLE,
                (table,)).fetchone()[0]
            if moved != len(rows) or reported != len(rows):
                raise RuntimeError("%s did not copy cleanly" % table)
            report[table] = {"rows": len(rows), "written": moved, "keys": list(keys)}
    finally:
        source.close()
        target.close()
    return report


def diff_state(target_path: str, tables: tuple[str, ...] = TABLES) -> dict:
    """What the queue changed since the copy: added, removed and changed row keys."""

    connection = sqlite3.connect("file:%s?mode=ro" % target_path, uri=True)
    out: dict[str, dict] = {}
    try:
        names = {str(row[0]) for row in
                 connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if SNAPSHOT_TABLE not in names:
            raise RuntimeError("no copy snapshot - the state has never been copied")
        for table in tables:
            columns = _columns(connection, table)
            keys = KEY_COLUMNS[table]
            current = {}
            for row in connection.execute("SELECT * FROM %s" % table):
                record = dict(zip(columns, row))
                current[str(record[keys[0]])] = row_hash(columns, row)
            copied = {str(row[0]): str(row[1]) for row in connection.execute(
                "SELECT row_key, row_sha256 FROM %s WHERE table_name=?" % SNAPSHOT_TABLE,
                (table,))}
            out[table] = {
                "added": sorted(set(current) - set(copied)),
                "removed": sorted(set(copied) - set(current)),
                "changed": sorted(key for key in set(current) & set(copied)
                                  if current[key] != copied[key]),
            }
    finally:
        connection.close()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    copy = sub.add_parser("copy")
    copy.add_argument("--source", required=True, help="read-only D1 export (SQLite)")
    copy.add_argument("--target", required=True, help="queue database (SQLite, WAL)")
    diff = sub.add_parser("diff")
    diff.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "copy":
            report = copy_state(args.source, args.target)
            print("PC_STATE_COPY " + json.dumps(report, sort_keys=True))
        else:
            changes = diff_state(args.target)
            for table, item in sorted(changes.items()):
                print("PC_STATE_DIFF %s added=%d removed=%d changed=%d"
                      % (table, len(item["added"]), len(item["removed"]),
                         len(item["changed"])))
            print("PC_STATE_DIFF_TOTAL %s"
                  % sum(len(v) for item in changes.values() for v in item.values()))
    except (RuntimeError, sqlite3.Error, OSError) as exc:
        print("PC_STATE_REFUSED reason=%s" % str(exc)[:120])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
