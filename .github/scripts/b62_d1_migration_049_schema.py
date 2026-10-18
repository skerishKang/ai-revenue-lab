#!/usr/bin/env python3
"""Exact additive migration 049: executor-observed outcome on the Mesh dispatch.

049 adds exactly two nullable columns to the 047/048 table:

    termination  TEXT
    exit_code    INTEGER

The Engine model lane re-feeds these exact values instead of inventing an
exit code. The gate is additive-only and fail-closed, mirroring 048:

* the source SQL may contain nothing but those two ``ALTER TABLE ... ADD
  COLUMN`` statements — no table rebuild, data rewrite, DROP/DELETE;
* the live readback is classified ``EXACT`` (both columns present with the
  reviewed shape), ``MISSING`` (neither column present) or ``DRIFT``
  (anything else, including a half-applied table);
* only ``MISSING`` may be applied, and the apply response must report success
  for both statements.

Shared D1 response handling (norm, TABLE, QUERY) is reused from the reviewed
048 module instead of being restated here.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b62_d1_migration_048_schema as base

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/049_oracle_mesh_command_result_meta.sql"
TABLE = base.TABLE
NEW_COLUMNS = ("termination", "exit_code")
#: Reviewed shape after 049: (name, type, notnull, dflt_value). Both columns
#: are nullable on purpose — rows pinned before 049 keep NULL (unknown).
EXPECTED = (
    ("termination", "TEXT", 0, None),
    ("exit_code", "INTEGER", 0, None),
)
QUERY = base.QUERY
BASE_FILES = (
    ROOT / "apps/padiem-chat/migrations/047_oracle_mesh_dispatch.sql",
    ROOT / "apps/padiem-chat/migrations/048_oracle_mesh_command.sql",
)


def source():
    text = MIGRATION.read_text(encoding="utf-8")
    upper = base.norm(text)
    for forbidden in ("drop table", "delete from", "create trigger", "create table"):
        if forbidden in upper:
            raise ValueError("Migration 049 is not additive: " + forbidden)
    if upper.count("alter table oracle_mesh_dispatch add column") != 2:
        raise ValueError("Migration 049 must add exactly two columns")
    if "alter table oracle_mesh_dispatch add column termination text" not in upper:
        raise ValueError("Migration 049 termination column is not the reviewed shape")
    if "alter table oracle_mesh_dispatch add column exit_code integer" not in upper:
        raise ValueError("Migration 049 exit_code column is not the reviewed shape")
    # Prove the statements run on a real 047+048 table, in order, exactly once.
    db = sqlite3.connect(":memory:")
    try:
        for migration in BASE_FILES:
            db.executescript(migration.read_text(encoding="utf-8"))
        before = {row[1] for row in db.execute("PRAGMA table_info(" + TABLE + ")")}
        if set(NEW_COLUMNS) & before:
            raise ValueError("047+048 baseline unexpectedly carries 049 columns")
        db.executescript(text)
        after = {row[1] for row in db.execute("PRAGMA table_info(" + TABLE + ")")}
        if not set(NEW_COLUMNS).issubset(after):
            raise ValueError("Migration 049 does not add its two columns")
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
    if "kind" not in by_name or "command_text" not in by_name:
        # 049 applies only on the reviewed 048-shape table, never on an
        # older or reshaped baseline.
        return "drift"
    present = [name for name in NEW_COLUMNS if name in by_name]
    if not present:
        return "missing"
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
        print("B62_D1_MIGRATION_049_SCHEMA="
              + classify(json.loads(path.read_text(encoding="utf-8"))).upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(rows, list) or len(rows) < 2 or any(
            not isinstance(x, dict) or x.get("success") is not True for x in rows
        ):
            raise ValueError("D1 additive 049 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_049_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 049 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_049_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
