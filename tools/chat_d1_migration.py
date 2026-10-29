#!/usr/bin/env python3
"""Stage 3 — move the whole Chat D1 export into the COM2 SQLite database.

PREPARED + REHEARSED ONLY. Nothing here touches Production D1; the real export
and cutover run on COM2 under the CTO-approved window (design doc §3).

Shape (generalized from the mesh queue's `copy_state.py`):

* the source is a READ-ONLY D1 export (a SQLite file produced by the reviewed
  export path); every source table must already exist in the target with the
  same columns, and a table without a primary key stops the whole run;
* tables owned by another authority are NEVER written here: the COM2 queue is
  the authority for dispatch/pairing/presence, and the broker owns its
  `local_agent_*` tables — a second writer would be a second authority;
* the load is ONE transaction for every table: any mismatch or failure rolls
  the whole load back, so the target never holds a half-moved dataset;
* the ledger records per-table row counts, a table digest and one hash per row
  — counts and hashes only, never a chat row's content;
* `verify` re-derives the target from the recorded run, and also compares the
  source export to the ledger when asked: a row edited after the load is a
  refusal, not a silent overwrite.

Exit codes: 0 success, 2 usage/config, 3 refused (mismatch or drift).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SUMMARY_TABLE = "chat_migration_summary"
SNAPSHOT_TABLE = "chat_migration_snapshot"
RUNS_TABLE = "chat_migration_runs"

#: The COM2 queue is the authority for these (PR #6115/#6121): the migration
#: tool must not overwrite them even when the D1 export still carries rows.
OWNED_BY_QUEUE = frozenset({
    "oracle_mesh_dispatch",
    "mesh_device_presence",
    "pc_pairing_codes",
    "pc_device_links",
})
#: Stage 2-C broker storage (separate DB normally; skipped if ever present).
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
    "d1_migrations",                 # source ledger, recorded, never loaded
    "padiem_local_migration_ledger", # the target's own schema ledger
    "chat_copy_snapshot",
    SUMMARY_TABLE, SNAPSHOT_TABLE, RUNS_TABLE,
})
OWNED_TABLES = OWNED_BY_QUEUE | OWNED_BY_BROKER
SKIP_TABLES = OWNED_TABLES | SYSTEM_TABLES

__all__ = [
    "OWNED_BY_BROKER", "OWNED_BY_QUEUE", "SKIP_TABLES", "SYSTEM_TABLES",
    "export_readonly_copy", "load_state", "plan_state", "verify_state",
]


class MigrationRefused(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info('{table}')")]


def _key_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    keys = [
        str(row[1]) for row in connection.execute(f"PRAGMA table_info('{table}')")
        if int(row[5]) > 0
    ]
    if not keys:
        raise MigrationRefused(f"no_primary_key table={table}")
    return keys


def _tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows if not str(row[0]).startswith("sqlite_")]


def _row_hash(columns: list[str], row: tuple) -> str:
    payload = json.dumps(
        {name: value for name, value in zip(columns, row)}, sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _table_digest(hashes: list[str]) -> str:
    digest = hashlib.sha256()
    for value in hashes:
        digest.update(value.encode("ascii"))
    return digest.hexdigest()


def _ro(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _source_tables(path: str) -> tuple[list[str], list[str]]:
    connection = _ro(path)
    try:
        names = [name for name in _tables(connection) if name not in SYSTEM_TABLES]
        ledger: list[str] = []
        try:
            ledger = [
                str(row[0]) for row in connection.execute(
                    "SELECT name FROM d1_migrations ORDER BY name"
                )
            ]
        except sqlite3.DatabaseError:
            ledger = []
        return names, ledger
    finally:
        connection.close()


def plan_state(source_path: str, target_path: str) -> dict:
    """Read-only comparison; never writes. Reports counts only."""

    source_names, ledger = _source_tables(source_path)
    source = _ro(source_path)
    target = sqlite3.connect(f"file:{target_path}?mode=ro", uri=True)
    try:
        target_names = set(_tables(target))
        report: dict[str, dict] = {}
        for table in source_names:
            if table in SKIP_TABLES:
                report[table] = {"status": "EXCLUDED_OWNED" if table in OWNED_TABLES else "EXCLUDED_SYSTEM"}
                continue
            if table not in target_names:
                report[table] = {"status": "MISSING_IN_TARGET"}
                continue
            if _columns(source, table) != _columns(target, table):
                report[table] = {"status": "SCHEMA_MISMATCH"}
                continue
            rows = source.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
            report[table] = {"status": "OK", "rows": int(rows)}
        return {"tables": report, "ledger": ledger}
    finally:
        source.close()
        target.close()


def _prepare_target(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {RUNS_TABLE} ("
        "run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,"
        " source_latest_migration TEXT, tables INTEGER NOT NULL, rows INTEGER NOT NULL)"
    )
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {SUMMARY_TABLE} ("
        "run_id TEXT NOT NULL, table_name TEXT NOT NULL, row_count INTEGER NOT NULL,"
        " table_sha256 TEXT NOT NULL, copied_at TEXT NOT NULL,"
        " PRIMARY KEY (run_id, table_name))"
    )
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {SNAPSHOT_TABLE} ("
        "run_id TEXT NOT NULL, table_name TEXT NOT NULL, row_key TEXT NOT NULL,"
        " row_sha256 TEXT NOT NULL, copied_at TEXT NOT NULL,"
        " PRIMARY KEY (run_id, table_name, row_key))"
    )


def load_state(source_path: str, target_path: str) -> dict:
    """Load the export into the target as ONE transaction, or refuse entirely."""

    source_names, ledger = _source_tables(source_path)
    source = _ro(source_path)
    target = sqlite3.connect(target_path, isolation_level=None)
    target.row_factory = sqlite3.Row
    run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    started = _now()
    try:
        target_names = set(_tables(target))
        problems: list[str] = []
        payloads: list[tuple[str, list[str], list[tuple], list[str], list[str]]] = []
        for table in source_names:
            if table in SKIP_TABLES:
                continue
            if table not in target_names:
                problems.append(f"missing_in_target:{table}")
                continue
            source_columns = _columns(source, table)
            if source_columns != _columns(target, table):
                problems.append(f"column_mismatch:{table}")
                continue
            keys = _key_columns(source, table)
            rows = source.execute(f"SELECT * FROM '{table}'").fetchall()
            hashes = [_row_hash(source_columns, tuple(row)) for row in rows]
            payloads.append((table, source_columns, [tuple(row) for row in rows], keys, hashes))
        if problems:
            raise MigrationRefused(";".join(problems))

        target.execute("BEGIN IMMEDIATE")
        try:
            _prepare_target(target)
            total_rows = 0
            for table, columns, rows, keys, hashes in payloads:
                target.execute(f"DELETE FROM '{table}'")
                placeholders = ",".join("?" for _ in columns)
                target.executemany(
                    f"INSERT INTO '{table}' ({','.join(columns)}) VALUES ({placeholders})",
                    rows,
                )
                moved = target.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
                if int(moved) != len(rows):
                    raise MigrationRefused(f"row_count_mismatch:{table}")
                key_index = [columns.index(key) for key in keys]
                target.executemany(
                    f"INSERT INTO {SNAPSHOT_TABLE} (run_id, table_name, row_key, row_sha256, copied_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    [
                        (run_id, table,
                         "|".join(str(row[index]) for index in key_index),
                         value, started)
                        for row, value in zip(rows, hashes)
                    ],
                )
                target.execute(
                    f"INSERT INTO {SUMMARY_TABLE} (run_id, table_name, row_count, table_sha256, copied_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (run_id, table, len(rows), _table_digest(hashes), started),
                )
                total_rows += len(rows)
            # Triggers can alter tables copied earlier. Validate the entire
            # final image before commit, not just each table immediately after
            # insertion, so a late side effect rolls back all writes.
            for table, columns, rows, keys, hashes in payloads:
                actual = [_row_hash(columns, tuple(row)) for row in target.execute(f"SELECT * FROM '{table}'")]
                if sorted(actual) != sorted(hashes):
                    raise MigrationRefused(f"final_content_mismatch:{table}")
            target.execute(
                f"INSERT INTO {RUNS_TABLE} (run_id, started_at, finished_at,"
                " source_latest_migration, tables, rows) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, started, _now(), ledger[-1] if ledger else "",
                 len(payloads), total_rows),
            )
            target.execute("COMMIT")
        except BaseException:
            target.execute("ROLLBACK")
            raise
        return {"run_id": run_id, "tables": len(payloads), "rows": total_rows,
                "ledger_latest": ledger[-1] if ledger else ""}
    finally:
        source.close()
        target.close()


def _live_hashes(connection: sqlite3.Connection, table: str) -> tuple[int, str]:
    columns = _columns(connection, table)
    keys = _key_columns(connection, table)
    rows = connection.execute(f"SELECT * FROM '{table}'").fetchall()
    hashes = [_row_hash(columns, tuple(row)) for row in rows]
    return len(rows), _table_digest(hashes)


def verify_state(target_path: str, *, source_path: str | None = None) -> dict:
    """Compare the target (and optionally the source export) to the last run."""

    target = sqlite3.connect(f"file:{target_path}?mode=ro", uri=True)
    try:
        last = target.execute(
            f"SELECT run_id FROM {RUNS_TABLE} ORDER BY finished_at DESC, run_id DESC LIMIT 1"
        ).fetchone()
        if last is None:
            raise MigrationRefused("no_recorded_run")
        run_id = str(last[0])
        summary = {
            str(row[0]): (int(row[1]), str(row[2]))
            for row in target.execute(
                f"SELECT table_name, row_count, table_sha256 FROM {SUMMARY_TABLE} WHERE run_id = ?",
                (run_id,),
            )
        }
        results: dict[str, str] = {}
        for table, (expected_rows, expected_digest) in summary.items():
            rows, digest = _live_hashes(target, table)
            results[table] = "OK" if (rows, digest) == (expected_rows, expected_digest) else "DRIFT"
        if source_path is not None:
            source = _ro(source_path)
            try:
                for table in summary:
                    if table not in _tables(source):
                        results[table] = "SOURCE_MISSING"
                        continue
                    columns = _columns(source, table)
                    rows = source.execute(f"SELECT * FROM '{table}'").fetchall()
                    digest = _table_digest([_row_hash(columns, tuple(row)) for row in rows])
                    expected = summary[table]
                    if digest != expected[1]:
                        results[table] = "SOURCE_DRIFT"
            finally:
                source.close()
        return {"run_id": run_id, "tables": results}
    finally:
        target.close()


def export_readonly_copy(live_path: str, out_path: str) -> dict:
    """Reverse direction: a read-only copy of the live DB for the D1 hand-back."""

    live = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
    out = sqlite3.connect(out_path)
    try:
        names = [name for name in _tables(live) if name not in SKIP_TABLES]
        for table in names:
            columns = _columns(live, table)
            out.execute(f"CREATE TABLE '{table}' ({','.join(columns)})")
            rows = live.execute(f"SELECT * FROM '{table}'").fetchall()
            placeholders = ",".join("?" for _ in columns)
            out.executemany(
                f"INSERT INTO '{table}' ({','.join(columns)}) VALUES ({placeholders})", rows,
            )
            out.execute(
                "CREATE TABLE IF NOT EXISTS chat_export_summary ("
                "table_name TEXT PRIMARY KEY, row_count INTEGER NOT NULL, table_sha256 TEXT NOT NULL)"
            )
            hashes = [_row_hash(columns, tuple(row)) for row in rows]
            out.execute(
                "INSERT OR REPLACE INTO chat_export_summary VALUES (?, ?, ?)",
                (table, len(rows), _table_digest(hashes)),
            )
        out.commit()
        return {"tables": len(names), "out": out_path}
    finally:
        live.close()
        out.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--source", required=True)
    plan.add_argument("--target", required=True)

    load = sub.add_parser("load")
    load.add_argument("--source", required=True)
    load.add_argument("--target", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--target", required=True)
    verify.add_argument("--source")

    export = sub.add_parser("export")
    export.add_argument("--live", required=True)
    export.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            report = plan_state(args.source, args.target)
            for table, status in sorted(report["tables"].items()):
                print(f"CHAT_MIGRATION_TABLE={table} {status.get('status')} ROWS={status.get('rows', '-')}")
            print(f"CHAT_MIGRATION_PLAN=TABLES={len(report['tables'])} LEDGER={len(report['ledger'])}")
            return 0
        if args.command == "load":
            started = time.monotonic()
            result = load_state(args.source, args.target)
            elapsed = time.monotonic() - started
            print(
                f"CHAT_MIGRATION_LOAD=PASS RUN={result['run_id']} TABLES={result['tables']} "
                f"ROWS={result['rows']} ELAPSED_MS={int(elapsed * 1000)} "
                f"ROWS_PER_SEC={int(result['rows'] / elapsed) if elapsed > 0 else 0}"
            )
            return 0
        if args.command == "verify":
            result = verify_state(args.target, source_path=args.source)
            for table, status in sorted(result["tables"].items()):
                print(f"CHAT_MIGRATION_VERIFY_TABLE={table} {status}")
            bad = [status for status in result["tables"].values() if status != "OK"]
            print(f"CHAT_MIGRATION_VERIFY={'FAIL' if bad else 'PASS'} RUN={result['run_id']}")
            return 3 if bad else 0
        if args.command == "export":
            result = export_readonly_copy(args.live, args.out)
            print(f"CHAT_MIGRATION_EXPORT=PASS TABLES={result['tables']}")
            return 0
    except MigrationRefused as exc:
        print(f"CHAT_MIGRATION_REFUSED reason={exc}")
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
