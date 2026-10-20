#!/usr/bin/env python3
"""Schema-only gate for #5080 migration 058 (Android sign-in handoff table).

058 creates exactly one additive table under the canonical ``PADIEM_CHAT_DB``:

    padiem_android_auth_handoffs(
      handoff_id, secret_hash, code_hash, status, pending_user_id,
      attempts, created_at, updated_at, pending_at, confirmed_at,
      claimed_at, expires_at,
      PRIMARY KEY(handoff_id),
      FK pending_user_id -> users(id) ON DELETE CASCADE
    )

plus exactly one index on ``expires_at``.

The merged Android sign-in handoff (#5162) writes and reads this table from the
production Chat Worker. While the table is absent the worker answers
``POST /auth/android/handoff`` with ``503 android_handoff_unavailable`` and
the Android app cannot open the external Google sign-in window, so the table
is a hard prerequisite of that already-deployed code.

This helper reads schema metadata only (``sqlite_master`` +
``PRAGMA table_info`` + ``PRAGMA foreign_key_list``). It never reads row
contents, user data or secret values, and it never emits an account, database
or binding identifier.

Dispositions:
  ``MISSING`` the table is absent; 058 is applicable.
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
MIGRATION = ROOT / "apps/padiem-chat/migrations/058_android_auth_handoff.sql"
TABLE = "padiem_android_auth_handoffs"
INDEX = "idx_padiem_android_auth_handoffs_expires_at"

# (name, declared type, notnull, pk position) in the reviewed order.
EXPECTED_COLUMNS = (
    ("handoff_id", "TEXT", 0, 1),
    ("secret_hash", "TEXT", 1, 0),
    ("code_hash", "TEXT", 1, 0),
    ("status", "TEXT", 1, 0),
    ("pending_user_id", "TEXT", 0, 0),
    ("attempts", "INTEGER", 1, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
    ("pending_at", "TEXT", 0, 0),
    ("confirmed_at", "TEXT", 0, 0),
    ("claimed_at", "TEXT", 0, 0),
    ("expires_at", "TEXT", 1, 0),
)
EXPECTED_FK = ("users", "pending_user_id", "id", "CASCADE")
# Column defaults are part of the reviewed shape: the store relies on them.
EXPECTED_DEFAULTS = {
    "status": "'awaiting_login'",
    "attempts": "0",
}
# CHECK clauses are absent from PRAGMA table_info; verify them from the DDL.
EXPECTED_CHECKS = (
    "check(statusin('awaiting_login','awaiting_confirmation','ready','claimed','cancelled'))",
    "check(attempts>=0)",
)

QUERY = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type='table' AND name='padiem_android_auth_handoffs';\n"
    "PRAGMA table_info(padiem_android_auth_handoffs);\n"
    "PRAGMA foreign_key_list(padiem_android_auth_handoffs);\n"
    "SELECT name, sql FROM sqlite_master "
    "WHERE type='index' AND name='idx_padiem_android_auth_handoffs_expires_at';"
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
    # 058 is additive only. `create index` is part of the reviewed change, so
    # it is allowed here and checked separately below.
    for forbidden in (
        "drop table", "drop index", "delete from", "create trigger",
        "alter table", "insert into", "update ",
    ):
        if forbidden in upper:
            raise ValueError("Migration 058 is not additive: " + forbidden)
    if upper.count("create table if not exists padiem_android_auth_handoffs") != 1:
        raise ValueError("Migration 058 must create the reviewed table exactly once")
    if upper.count("create index if not exists idx_padiem_android_auth_handoffs_expires_at") != 1:
        raise ValueError("Migration 058 must create the reviewed index exactly once")
    for fragment in (
        "handoff_idtextprimarykey",
        "secret_hashtextnotnull",
        "code_hashtextnotnull",
        "statustextnotnulldefault'awaiting_login'",
        "pending_user_idtextreferencesusers(id)ondeletecascade",
        "attemptsintegernotnulldefault0",
        "created_attextnotnull",
        "updated_attextnotnull",
        "pending_attext",
        "confirmed_attext",
        "claimed_attext",
        "expires_attextnotnull",
    ):
        if fragment not in tight(text):
            raise ValueError("Migration 058 shape is not the reviewed shape: " + fragment)

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
            raise ValueError("Migration 058 columns/PK do not match the reviewed shape")
        defaults = {
            row[1]: row[4]
            for row in columns
            if row[4] is not None
        }
        if defaults != EXPECTED_DEFAULTS:
            raise ValueError("Migration 058 defaults do not match the reviewed shape")
        foreign_keys = db.execute(f"PRAGMA foreign_key_list({TABLE})").fetchall()
        if len(foreign_keys) != 1:
            raise ValueError("Migration 058 must declare exactly one foreign key")
        fk = foreign_keys[0]
        if (fk[2], fk[3], fk[4], str(fk[6]).upper()) != EXPECTED_FK:
            raise ValueError("Migration 058 foreign key does not match the reviewed shape")
        index_rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (INDEX,)
        ).fetchall()
        if len(index_rows) != 1:
            raise ValueError("Migration 058 must create the reviewed expires_at index")
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
    defaults = {
        row.get("name"): row.get("dflt_value")
        for row in columns
        if row.get("dflt_value") is not None
    }
    if defaults != EXPECTED_DEFAULTS:
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
    if len(indexes) != 1 or indexes[0].get("name") != INDEX:
        return "drift"
    index_sql = tight(indexes[0].get("sql", ""))
    if f"on{TABLE}(expires_at)" not in index_sql:
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
        print("B62_D1_MIGRATION_058_SCHEMA=" + verdict.upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if (not isinstance(rows, list) or not rows
                or any(not isinstance(item, dict) or item.get("success") is not True for item in rows)):
            raise ValueError("D1 additive 058 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_058_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 058 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_058_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
