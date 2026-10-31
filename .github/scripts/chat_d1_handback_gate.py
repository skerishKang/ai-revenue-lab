"""Chat COM2 -> D1 handback gate: the reviewed rollback path (#5115).

Cutover moves the Chat database to COM2. If the cutover has to be undone after
COM2 accepted writes, D1 must receive exactly those writes: the rows COM2 added,
the rows it changed, and the rows it deleted, measured against the baseline
snapshot D1 held when the cutover froze writes. Option (가) of #6197.

This module owns the reasoning. It never opens a network connection and never
prints row content: only table names, counts and digests.

Three modes
-----------
* ``plan``   — read both SQLite files read-only and compute the delta
               (added / changed / removed per table). Writes one JSON plan.
* ``verify`` — recompute the delta and compare it to an approved plan. Drift in
               either file is a refusal. Writes nothing.
* ``apply``  — re-run the same comparison, and only when it still matches the
               approved plan render the bounded SQL file the workflow feeds to
               D1. Any drift renders zero statements and exits 3.

Write-zero guarantee
--------------------
``plan`` and ``verify`` open both files with ``mode=ro`` URIs, so SQLite itself
rejects a write. ``apply`` writes only the SQL output file, and only after the
approved plan matches; the plan file is an input and is never edited. No
function here executes SQL against D1 — the workflow owns that one step, behind
``environment: production`` and a confirmation phrase.

Scope
-----
Tables owned by another authority never travel: the COM2 queue owns dispatch,
pairing and presence; the broker owns ``local_agent_*``; both migration ledgers
are bookkeeping. A table without a primary key is refused outright, because a
delta cannot be expressed for it.

Exit codes: 0 success, 2 usage/config, 3 refused (drift, schema mismatch).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

PLAN_SCHEMA = "chat-d1-handback/plan/v1"

#: COM2 queue authority (PR #6115/#6121) — never overwritten by a handback.
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

#: A handback is a bounded recovery action, not a re-import.
MAX_STATEMENTS = 50_000


class GateError(ValueError):
    """A fixed, public-safe refusal. Never carries SQL bodies or row data."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise GateError("CHAT_HANDBACK_FILE_MISSING")
    return sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _key_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = [
        (int(row[5]), str(row[1]))
        for row in connection.execute(f'PRAGMA table_info("{table}")')
        if int(row[5]) > 0
    ]
    rows.sort()
    return [name for _position, name in rows]


def _row_digest(columns: list[str], row: tuple) -> str:
    payload = json.dumps(
        [columns, [None if value is None else str(value) for value in row]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _key_text(parts) -> str:
    return json.dumps([None if part is None else str(part) for part in parts])


def _rows(connection: sqlite3.Connection, table: str) -> tuple[list[str], dict[str, tuple]]:
    columns = _columns(connection, table)
    keys = _key_columns(connection, table)
    if not keys:
        raise GateError("CHAT_HANDBACK_NO_PRIMARY_KEY")
    key_indexes = [columns.index(name) for name in keys]
    selected = ", ".join(f'"{name}"' for name in columns)
    found: dict[str, tuple] = {}
    for row in connection.execute(f'SELECT {selected} FROM "{table}"'):
        found[_key_text([row[index] for index in key_indexes])] = row
    return columns, found


def _comparable_tables(connection: sqlite3.Connection) -> list[str]:
    return [name for name in _tables(connection) if name not in SKIP_TABLES]


def snapshot(path: str | Path) -> dict[str, dict[str, str]]:
    """Per-table ``{key: row digest}`` for every comparable table."""

    connection = _read_only(path)
    try:
        tables = _comparable_tables(connection)
        if not tables:
            raise GateError("CHAT_HANDBACK_NO_TABLES")
        out: dict[str, dict[str, str]] = {}
        for table in tables:
            columns, rows = _rows(connection, table)
            out[table] = {key: _row_digest(columns, row) for key, row in rows.items()}
        return out
    finally:
        connection.close()


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_plan(baseline_path: str | Path, handback_path: str | Path) -> dict:
    """Compute the delta COM2 accepted since the baseline snapshot."""

    baseline = snapshot(baseline_path)
    handback = snapshot(handback_path)
    if set(baseline) != set(handback):
        raise GateError("CHAT_HANDBACK_SCHEMA_MISMATCH")

    per_table: dict[str, dict[str, int]] = {}
    added: dict[str, list[str]] = {}
    changed: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for table in sorted(baseline):
        before, after = baseline[table], handback[table]
        insert_keys = sorted(set(after) - set(before))
        delete_keys = sorted(set(before) - set(after))
        update_keys = sorted(key for key in set(before) & set(after) if before[key] != after[key])
        per_table[table] = {
            "added": len(insert_keys),
            "changed": len(update_keys),
            "removed": len(delete_keys),
            "baseline_rows": len(before),
            "handback_rows": len(after),
        }
        if insert_keys:
            added[table] = insert_keys
        if update_keys:
            changed[table] = update_keys
        if delete_keys:
            removed[table] = delete_keys

    statement_count = sum(
        row["added"] + row["changed"] + row["removed"] for row in per_table.values()
    )
    if statement_count > MAX_STATEMENTS:
        raise GateError("CHAT_HANDBACK_PLAN_TOO_LARGE")

    return {
        "schema": PLAN_SCHEMA,
        "created_at": _now(),
        "baseline_sha256": _file_sha256(baseline_path),
        "handback_sha256": _file_sha256(handback_path),
        "statement_count": statement_count,
        "tables": per_table,
        "keys": {"added": added, "changed": changed, "removed": removed},
    }


def plan_digest(plan: dict) -> str:
    """The identity of an approved plan: everything except its timestamp."""

    payload = {key: value for key, value in plan.items() if key != "created_at"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verify_plan(plan: dict, baseline_path: str | Path, handback_path: str | Path) -> dict:
    """Recompute the delta and refuse when it is not the approved plan."""

    if plan.get("schema") != PLAN_SCHEMA:
        raise GateError("CHAT_HANDBACK_PLAN_SCHEMA_UNKNOWN")
    current = build_plan(baseline_path, handback_path)
    if plan_digest(current) != plan_digest(plan):
        raise GateError("CHAT_HANDBACK_PLAN_DRIFT")
    return current


def _literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "X'" + bytes(value).hex() + "'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise GateError("CHAT_HANDBACK_VALUE_TYPE_UNSUPPORTED")


def _where(columns: list[str], row: tuple, key_indexes: list[int]) -> str:
    return " AND ".join(
        f'"{columns[index]}" = {_literal(row[index])}' for index in key_indexes
    )


def render_statements(
    plan: dict,
    baseline_path: str | Path,
    handback_path: str | Path,
) -> list[str]:
    """Render the bounded statement list for an approved delta."""

    statements: list[str] = []

    connection = _read_only(handback_path)
    try:
        for kind in ("added", "changed"):
            for table in sorted(plan["keys"][kind]):
                columns, rows = _rows(connection, table)
                keys = _key_columns(connection, table)
                key_indexes = [columns.index(name) for name in keys]
                column_sql = ", ".join(f'"{name}"' for name in columns)
                for key in plan["keys"][kind][table]:
                    row = rows[key]
                    if kind == "added":
                        statements.append(
                            f'INSERT INTO "{table}" ({column_sql}) VALUES ('
                            + ", ".join(_literal(value) for value in row)
                            + ");"
                        )
                        continue
                    assignments = ", ".join(
                        f'"{columns[index]}" = {_literal(row[index])}'
                        for index in range(len(columns))
                        if index not in key_indexes
                    )
                    if assignments:
                        statements.append(
                            f'UPDATE "{table}" SET {assignments} '
                            f"WHERE {_where(columns, row, key_indexes)};"
                        )
    finally:
        connection.close()

    if plan["keys"]["removed"]:
        connection = _read_only(baseline_path)
        try:
            for table in sorted(plan["keys"]["removed"]):
                columns, rows = _rows(connection, table)
                keys = _key_columns(connection, table)
                key_indexes = [columns.index(name) for name in keys]
                for key in plan["keys"]["removed"][table]:
                    row = rows[key]
                    statements.append(
                        f'DELETE FROM "{table}" WHERE {_where(columns, row, key_indexes)};'
                    )
        finally:
            connection.close()

    return statements


def render_sql(statements: list[str]) -> str:
    header = [
        "-- Chat COM2 -> D1 handback, generated by .github/scripts/chat_d1_handback_gate.py",
        "-- One transaction: a partial handback must never be left behind.",
        "BEGIN IMMEDIATE;",
    ]
    footer = ["COMMIT;", ""]
    return "\n".join(header + statements + footer)


def load_plan(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GateError("CHAT_HANDBACK_PLAN_UNREADABLE") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat COM2 -> D1 handback gate")
    parser.add_argument("mode", choices=("plan", "verify", "apply"))
    parser.add_argument("--baseline", required=True, help="D1 snapshot taken at the cutover freeze")
    parser.add_argument("--handback", required=True, help="current COM2 Chat SQLite copy")
    parser.add_argument("--plan", help="approved plan JSON (required by verify/apply)")
    parser.add_argument("--out", help="plan JSON (plan) or SQL file (apply)")
    args = parser.parse_args(argv)

    try:
        if args.mode == "plan":
            if not args.out:
                raise GateError("CHAT_HANDBACK_OUT_REQUIRED")
            plan = build_plan(args.baseline, args.handback)
            Path(args.out).write_text(
                json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8",
            )
            print(
                f"CHAT_HANDBACK_PLAN=OK tables={len(plan['tables'])} "
                f"statements={plan['statement_count']} digest={plan_digest(plan)}"
            )
            return EXIT_OK

        if not args.plan:
            raise GateError("CHAT_HANDBACK_PLAN_REQUIRED")
        approved = load_plan(args.plan)

        if args.mode == "verify":
            current = verify_plan(approved, args.baseline, args.handback)
            print(
                f"CHAT_HANDBACK_VERIFY=PASS statements={current['statement_count']} "
                f"digest={plan_digest(current)}"
            )
            return EXIT_OK

        if not args.out:
            raise GateError("CHAT_HANDBACK_OUT_REQUIRED")
        current = verify_plan(approved, args.baseline, args.handback)
        statements = render_statements(current, args.baseline, args.handback)
        Path(args.out).write_text(render_sql(statements), encoding="utf-8")
        print(
            f"CHAT_HANDBACK_APPLY=READY statements={len(statements)} "
            f"digest={plan_digest(current)}"
        )
        return EXIT_OK
    except GateError as exc:
        print(f"CHAT_HANDBACK_REFUSED reason={exc}")
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
