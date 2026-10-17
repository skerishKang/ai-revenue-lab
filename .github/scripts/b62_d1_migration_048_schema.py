#!/usr/bin/env python3
"""Exact additive migration 048 for the Oracle Mesh command dispatch columns.

048 adds exactly two columns to the 047 table:

    kind          TEXT NOT NULL DEFAULT 'read'
    command_text  TEXT

The gate is additive-only and fail-closed:

* the source SQL may contain nothing but those two ``ALTER TABLE ... ADD
  COLUMN`` statements — no table rebuild, no data rewrite, no DROP/DELETE;
* the live readback is classified ``EXACT`` (both columns already present with
  the reviewed shape), ``MISSING`` (neither column present, i.e. 047 only) or
  ``DRIFT`` (anything else, including a half-applied or reshaped table);
* only ``MISSING`` may be applied, and the apply response must report success
  for both statements.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/048_oracle_mesh_command.sql"
TABLE = "oracle_mesh_dispatch"
NEW_COLUMNS = ("kind", "command_text")
#: Reviewed shape after 048: (name, type, notnull, dflt_value)
EXPECTED = (
    ("kind", "TEXT", 1, "'read'"),
    ("command_text", "TEXT", 0, None),
)
QUERY = (
    "SELECT name,sql FROM sqlite_master WHERE name='oracle_mesh_dispatch';"
    "PRAGMA table_info(oracle_mesh_dispatch);"
)
BASE_047 = ROOT / "apps/padiem-chat/migrations/047_oracle_mesh_dispatch.sql"


def norm(sql):
    return re.sub(
        r"\s+", " ",
        re.sub(r"\s*([(),;=])\s*", r"\1", re.sub(r"--[^\n]*", "", sql).strip().lower()),
    ).strip()


def source():
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    for forbidden in ("drop table", "delete from", "create trigger", "create table"):
        if forbidden in upper:
            raise ValueError("Migration 048 is not additive: " + forbidden)
    if upper.count("alter table oracle_mesh_dispatch add column") != 2:
        raise ValueError("Migration 048 must add exactly two columns")
    if "kind text not null default 'read'" not in upper:
        raise ValueError("Migration 048 kind column is not the reviewed shape")
    if "command_text text" not in upper:
        raise ValueError("Migration 048 command_text column is missing")
    # Prove the statements run on a real 047 table, in order, exactly once.
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(BASE_047.read_text(encoding="utf-8"))
        before = {row[1] for row in db.execute("PRAGMA table_info(" + TABLE + ")")}
        if set(NEW_COLUMNS) & before:
            raise ValueError("047 baseline unexpectedly carries 048 columns")
        db.executescript(text)
        after = {row[1] for row in db.execute("PRAGMA table_info(" + TABLE + ")")}
        if not set(NEW_COLUMNS).issubset(after):
            raise ValueError("Migration 048 does not add its two columns")
    finally:
        db.close()
    return text


def classify(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 schema API error")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != 2:
        raise ValueError("D1 schema response incomplete")
    blocks = []
    for record in results:
        if not isinstance(record, dict) or record.get("success") is not True:
            raise ValueError("D1 statement failed")
        rows = record.get("results")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("D1 rows malformed")
        blocks.append(rows)
    objects, columns = blocks
    table_rows = [item for item in objects if item.get("name") == TABLE]
    if len(table_rows) != 1 or table_rows[0].get("sql") is None:
        return "drift"
    by_name = {row.get("name"): row for row in columns}
    present = [name for name in NEW_COLUMNS if name in by_name]
    if not present:
        # 047-only table: still a real table, so this is the applicable state.
        return "missing" if "path_relative" in by_name else "drift"
    if len(present) != len(NEW_COLUMNS):
        return "drift"
    for name, sql_type, notnull, default in EXPECTED:
        row = by_name[name]
        if (
            str(row.get("type", "")).upper() != sql_type
            or int(row.get("notnull", 0)) != notnull
            or (row.get("dflt_value") if row.get("dflt_value") is not None else None) != default
        ):
            return "drift"
    return "exact"


def main():
    if len(sys.argv) != 3:
        raise ValueError("expected <query|classify|apply|check-apply> <file>")
    action, path = sys.argv[1], Path(sys.argv[2])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        print("B62_D1_MIGRATION_048_SCHEMA="
              + classify(json.loads(path.read_text(encoding="utf-8"))).upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(rows, list) or len(rows) < 2 or any(
            not isinstance(x, dict) or x.get("success") is not True for x in rows
        ):
            raise ValueError("D1 additive 048 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_048_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 048 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_048_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
