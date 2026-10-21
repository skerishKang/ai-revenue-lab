#!/usr/bin/env python3
"""Schema-only gate for #5222 migration 059 (account model selection table).

059 creates exactly one additive table under the canonical ``PADIEM_CHAT_DB``:

    padiem_account_model_selections(
      user_id, tier, updated_at,
      PRIMARY KEY(user_id),
      CHECK(tier IN ('free','plus','pro','max','admin')),
      FK user_id -> users(id) ON DELETE CASCADE
    )

The merged Chat/Claw account-scoped model selection (#5273) reads and writes
this table from the production Chat Worker. While the table is absent the
worker answers ``GET/PUT /api/account/model-selection`` with
``503 model_selection_unavailable`` and the browser keeps its existing
server-verified Free default, so the table is the prerequisite that makes the
account's last selected tier restorable.

The row is a UI preference only. It never grants model access: the server
re-verifies the member grade and the administrator gate on every read and on
every model request.

This helper reads schema metadata only (``sqlite_master`` +
``PRAGMA table_info`` + ``PRAGMA foreign_key_list`` + ``PRAGMA index_list``).
It never reads row contents, user data or secret values, and it never emits an
account, database or binding identifier.

Dispositions:
  ``MISSING`` the table is absent; 059 is applicable.
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
MIGRATION = ROOT / "apps/padiem-chat/migrations/059_account_model_selection.sql"
TABLE = "padiem_account_model_selections"

# (name, declared type, notnull, pk position) in the reviewed order.
EXPECTED_COLUMNS = (
    ("user_id", "TEXT", 1, 1),
    ("tier", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
)
EXPECTED_FK = ("users", "user_id", "id", "CASCADE")
# CHECK clauses are absent from PRAGMA table_info; verify them from the DDL.
# The tier vocabulary is the whole authority boundary of the row: a tier
# outside it is not a selectable lane and must never be storable.
EXPECTED_CHECKS = (
    "check(tierin('free','plus','pro','max','admin'))",
)
# The only index of the table is the implicit primary-key index, so the
# reviewed shape carries no user-defined index.
EXPECTED_INDEX_COUNT = 1

QUERY = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type='table' AND name='padiem_account_model_selections';\n"
    "PRAGMA table_info(padiem_account_model_selections);\n"
    "PRAGMA foreign_key_list(padiem_account_model_selections);\n"
    "PRAGMA index_list(padiem_account_model_selections);"
)


def norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def tight(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "", value).lower()


def source() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    # 059 is additive only: it creates one table and touches nothing else.
    for forbidden in (
        "drop table", "drop index", "delete from", "create trigger",
        "alter table", "create index", "insert into", "update ",
    ):
        if forbidden in upper:
            raise ValueError("Migration 059 is not additive: " + forbidden)
    if upper.count("create table if not exists padiem_account_model_selections") != 1:
        raise ValueError("Migration 059 must create the reviewed table exactly once")
    for fragment in (
        "user_id text not null primary key references users(id) on delete cascade",
        "tier text not null check (tier in ('free', 'plus', 'pro', 'max', 'admin'))",
        "updated_at text not null",
    ):
        if fragment not in norm(text):
            raise ValueError("Migration 059 shape is not the reviewed shape: " + fragment)

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
            raise ValueError("Migration 059 columns/PK do not match the reviewed shape")
        if any(row[4] is not None for row in columns):
            raise ValueError("Migration 059 must not carry a column default")
        foreign_keys = db.execute(f"PRAGMA foreign_key_list({TABLE})").fetchall()
        if len(foreign_keys) != 1:
            raise ValueError("Migration 059 must declare exactly one foreign key")
        fk = foreign_keys[0]
        if (fk[2], fk[3], fk[4], str(fk[6]).upper()) != EXPECTED_FK:
            raise ValueError("Migration 059 foreign key does not match the reviewed shape")
        indexes = db.execute(f"PRAGMA index_list({TABLE})").fetchall()
        if len(indexes) != EXPECTED_INDEX_COUNT:
            raise ValueError("Migration 059 must carry only the primary-key index")
        # PRAGMA index_list: seq, name, unique, origin, partial.
        if str(indexes[0][3]).lower() != "pk":
            raise ValueError("Migration 059 must carry only the primary-key index")
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
    objects, columns, foreign_keys, indexes = _blocks(payload, 4)
    table_rows = [row for row in objects if row.get("name") == TABLE]

    if not table_rows:
        return "missing" if not columns and not foreign_keys and not indexes else "drift"
    if len(table_rows) != 1 or not isinstance(table_rows[0].get("sql"), str):
        return "drift"
    shape = tuple(
        (row.get("name"), str(row.get("type", "")).upper(),
         int(row.get("notnull", -1)), int(row.get("pk", -1)))
        for row in columns
    )
    if shape != EXPECTED_COLUMNS:
        return "drift"
    if any(row.get("dflt_value") is not None for row in columns):
        return "drift"
    ddl = tight(table_rows[0]["sql"])
    if ddl.count("check(") != len(EXPECTED_CHECKS) or any(
        clause not in ddl for clause in EXPECTED_CHECKS
    ):
        return "drift"
    if len(foreign_keys) != 1:
        return "drift"
    fk = foreign_keys[0]
    if (
        fk.get("table"), fk.get("from"), fk.get("to"),
        str(fk.get("on_delete", "")).upper(),
    ) != EXPECTED_FK:
        return "drift"
    if len(indexes) != EXPECTED_INDEX_COUNT:
        return "drift"
    if str(indexes[0].get("origin", "")).lower() != "pk":
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        raise ValueError("expected <query|classify|apply|check-apply> <file>")
    action, path = argv[0], Path(argv[1])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        verdict = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_D1_MIGRATION_059_SCHEMA=" + verdict.upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if (not isinstance(rows, list) or not rows
                or any(not isinstance(item, dict) or item.get("success") is not True for item in rows)):
            raise ValueError("D1 additive 059 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_059_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 059 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_059_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
