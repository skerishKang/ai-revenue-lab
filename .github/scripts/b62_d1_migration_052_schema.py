#!/usr/bin/env python3
"""Schema-only gate for #5015 migration 052 (preferred PC target table).

052 creates exactly one additive table under the canonical ``PADIEM_CHAT_DB``:

    claw_pc_device_selection(
      user_id, workspace_id, device_id, updated_at,
      PRIMARY KEY(user_id, workspace_id), FK user_id -> users(id) ON DELETE CASCADE
    )

The merged B62 selection restore reads and writes this table. The deploy gate
must prove the table exists before uploading that code. This helper reads
schema metadata only (``sqlite_master`` + ``PRAGMA table_info`` + ``PRAGMA
foreign_key_list``). It never reads row contents, user data or secret values,
and it never emits an account, database or binding identifier.

Dispositions:
  ``MISSING`` the table is absent; 052 is applicable.
  ``EXACT``   the reviewed shape is present (idempotent apply).
  ``DRIFT``   the table exists with another shape; never mutated.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/052_claw_pc_device_selection.sql"
TABLE = "claw_pc_device_selection"
# (name, declared type, notnull, pk position) in the reviewed order.
EXPECTED_COLUMNS = (
    ("user_id", "TEXT", 1, 1),
    ("workspace_id", "TEXT", 1, 2),
    ("device_id", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
)
EXPECTED_FK = ("users", "user_id", "id", "CASCADE")
QUERY = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type='table' AND name='claw_pc_device_selection';\n"
    "PRAGMA table_info(claw_pc_device_selection);\n"
    "PRAGMA foreign_key_list(claw_pc_device_selection);"
)


def norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def source() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    for forbidden in (
        "drop table", "delete from", "create trigger", "alter table",
        "create index", "insert into", "update ",
    ):
        if forbidden in upper:
            raise ValueError("Migration 052 is not additive: " + forbidden)
    if upper.count("create table if not exists claw_pc_device_selection") != 1:
        raise ValueError("Migration 052 must create the reviewed table exactly once")
    for fragment in (
        "user_id text not null references users(id) on delete cascade",
        "workspace_id text not null check(length(workspace_id) between 1 and 160)",
        "device_id text not null check(length(device_id) between 1 and 128)",
        "updated_at text not null",
        "primary key(user_id, workspace_id)",
    ):
        if fragment not in upper:
            raise ValueError("Migration 052 shape is not the reviewed shape: " + fragment)
    # Prove the SQL creates the exact reviewed shape on a real SQLite database.
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
        db.executescript(text)
        columns = db.execute(f"PRAGMA table_info({TABLE})").fetchall()
        shape = tuple(
            (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in columns
        )
        if shape != EXPECTED_COLUMNS:
            raise ValueError("Migration 052 columns/PK do not match the reviewed shape")
        foreign_keys = db.execute(f"PRAGMA foreign_key_list({TABLE})").fetchall()
        if len(foreign_keys) != 1:
            raise ValueError("Migration 052 must declare exactly one foreign key")
        fk = foreign_keys[0]
        if (fk[2], fk[3], fk[4], str(fk[6]).upper()) != EXPECTED_FK:
            raise ValueError("Migration 052 foreign key does not match the reviewed shape")
    finally:
        db.close()
    return text


def _blocks(payload: object, count: int) -> list[list[dict[str, object]]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 schema API error")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != count:
        raise ValueError("D1 schema response incomplete")
    blocks: list[list[dict[str, object]]] = []
    for record in results:
        if not isinstance(record, dict) or record.get("success") is not True:
            raise ValueError("D1 statement failed")
        rows = record.get("results")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("D1 rows malformed")
        blocks.append(rows)
    return blocks


def classify(payload: object) -> str:
    objects, columns, foreign_keys = _blocks(payload, 3)
    table_rows = [row for row in objects if row.get("name") == TABLE]
    if not table_rows:
        return "missing" if not columns and not foreign_keys else "drift"
    if len(table_rows) != 1 or not isinstance(table_rows[0].get("sql"), str):
        return "drift"
    shape = tuple(
        (row.get("name"), str(row.get("type", "")).upper(),
         int(row.get("notnull", -1)), int(row.get("pk", -1)))
        for row in columns
    )
    if shape != EXPECTED_COLUMNS:
        return "drift"
    if len(foreign_keys) != 1:
        return "drift"
    fk = foreign_keys[0]
    if (
        fk.get("table"), fk.get("from"), fk.get("to"),
        str(fk.get("on_delete", "")).upper(),
    ) != EXPECTED_FK:
        return "drift"
    return "exact"


def main() -> None:
    if len(sys.argv) != 3:
        raise ValueError("expected <query|classify|apply|check-apply> <file>")
    action, path = sys.argv[1], Path(sys.argv[2])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        verdict = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_D1_MIGRATION_052_SCHEMA=" + verdict.upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(rows, list) or not rows or any(
            not isinstance(item, dict) or item.get("success") is not True for item in rows
        ):
            raise ValueError("D1 additive 052 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_052_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 052 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_052_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
