#!/usr/bin/env python3
"""Schema-only gate for #5441 migration 062 (lost-password reset tables).

062 creates exactly two additive tables under the canonical ``PADIEM_CHAT_DB``:

    password_reset_tokens(token_id, user_id, token_digest, issued_at,
      expires_at, consumed_at, revoked_at, attempts, created_at)
    password_reset_audit(id, event, user_id, identifier_digest, reason_code,
      occurred_at)

plus their reviewed indexes. The merged B62 reset routes read and write these
tables, so the deploy gate must prove they exist before uploading that code.

This helper reads schema metadata only (``sqlite_master`` +
``PRAGMA table_info``). It never reads row contents, account data or secret
values, and it never emits an account, database or binding identifier.

Dispositions:
  ``MISSING`` the reset tables are absent; 062 is applicable.
  ``EXACT``   the reviewed shape is present (idempotent apply).
  ``DRIFT``   a reset table exists with another shape; never mutated.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/062_password_reset.sql"

TOKEN_TABLE = "password_reset_tokens"
AUDIT_TABLE = "password_reset_audit"
TOKEN_INDEXES = (
    "idx_password_reset_tokens_user",
    "idx_password_reset_tokens_expiry",
)
AUDIT_INDEXES = (
    "idx_password_reset_audit_identifier",
    "idx_password_reset_audit_occurred",
    "idx_password_reset_audit_user",
)

# (name, declared type, notnull, pk position) in the reviewed order.
EXPECTED_TOKEN_COLUMNS = (
    ("token_id", "TEXT", 0, 1),
    ("user_id", "TEXT", 1, 0),
    ("token_digest", "TEXT", 1, 0),
    ("issued_at", "TEXT", 1, 0),
    ("expires_at", "TEXT", 1, 0),
    ("consumed_at", "TEXT", 0, 0),
    ("revoked_at", "TEXT", 0, 0),
    ("attempts", "INTEGER", 1, 0),
    ("created_at", "TEXT", 1, 0),
)
EXPECTED_AUDIT_COLUMNS = (
    ("id", "INTEGER", 0, 1),
    ("event", "TEXT", 1, 0),
    ("user_id", "TEXT", 0, 0),
    ("identifier_digest", "TEXT", 1, 0),
    ("reason_code", "TEXT", 0, 0),
    ("occurred_at", "TEXT", 1, 0),
)
EXPECTED_TOKEN_FK = ("users", "user_id", "id", "CASCADE")
EXPECTED_AUDIT_EVENTS = (
    "requested",
    "issued",
    "delivered",
    "delivery_failed",
    "consumed",
    "rejected",
    "expired",
)

QUERY = (
    "SELECT name, type, sql FROM sqlite_master WHERE name IN ("
    "'password_reset_tokens','password_reset_audit',"
    "'idx_password_reset_tokens_user','idx_password_reset_tokens_expiry',"
    "'idx_password_reset_audit_identifier','idx_password_reset_audit_occurred',"
    "'idx_password_reset_audit_user') ORDER BY name;\n"
    "PRAGMA table_info(password_reset_tokens);\n"
    "PRAGMA table_info(password_reset_audit);\n"
    "PRAGMA foreign_key_list(password_reset_tokens);"
)


def norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def source() -> str:
    """The reviewed 062 migration, proved additive and of the reviewed shape."""
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    for forbidden in (
        "drop table",
        "alter table",
        "delete from",
        "create trigger",
        "insert into users",
        "update users",
        "update password_credentials",
        "pragma foreign_keys",
    ):
        if forbidden in upper:
            raise ValueError("Migration 062 is not additive: " + forbidden)
    for fragment in (
        "create table if not exists password_reset_tokens",
        "create table if not exists password_reset_audit",
        "create index if not exists idx_password_reset_tokens_user",
        "create index if not exists idx_password_reset_tokens_expiry",
        "create index if not exists idx_password_reset_audit_identifier",
        "create index if not exists idx_password_reset_audit_occurred",
        "create index if not exists idx_password_reset_audit_user",
        "token_digest text not null unique",
        "identifier_digest text not null",
    ):
        if fragment not in upper:
            raise ValueError("Migration 062 shape is not the reviewed shape: " + fragment)
    # Prove the SQL creates the exact reviewed shape on a real SQLite database.
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
        db.executescript(text)
        token_shape = tuple(
            (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in db.execute(f"PRAGMA table_info({TOKEN_TABLE})").fetchall()
        )
        if token_shape != EXPECTED_TOKEN_COLUMNS:
            raise ValueError("Migration 062 token columns do not match the reviewed shape")
        audit_shape = tuple(
            (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in db.execute(f"PRAGMA table_info({AUDIT_TABLE})").fetchall()
        )
        if audit_shape != EXPECTED_AUDIT_COLUMNS:
            raise ValueError("Migration 062 audit columns do not match the reviewed shape")
        foreign_keys = db.execute(f"PRAGMA foreign_key_list({TOKEN_TABLE})").fetchall()
        if len(foreign_keys) != 1:
            raise ValueError("Migration 062 must declare exactly one foreign key")
        fk = foreign_keys[0]
        if (fk[2], fk[3], fk[4], str(fk[6]).upper()) != EXPECTED_TOKEN_FK:
            raise ValueError("Migration 062 foreign key does not match the reviewed shape")
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
    objects, token_columns, audit_columns, foreign_keys = _blocks(payload, 4)
    by_name = {
        row.get("name"): row
        for row in objects
        if isinstance(row.get("name"), str)
    }
    token = by_name.get(TOKEN_TABLE)
    audit = by_name.get(AUDIT_TABLE)
    if token is None and audit is None:
        return "missing"
    if token is None or audit is None:
        # A half-applied migration is not a state this gate owns.
        return "drift"
    if token.get("type") != "table" or audit.get("type") != "table":
        return "drift"
    for name in (*TOKEN_INDEXES, *AUDIT_INDEXES):
        index = by_name.get(name)
        if index is None or index.get("type") != "index":
            return "drift"
        ddl = norm(index.get("sql"))
        if TOKEN_TABLE not in ddl and AUDIT_TABLE not in ddl:
            return "drift"

    token_shape = tuple(
        (row.get("name"), str(row.get("type", "")).upper(),
         int(row.get("notnull", -1)), int(row.get("pk", -1)))
        for row in token_columns
    )
    if token_shape != EXPECTED_TOKEN_COLUMNS:
        return "drift"
    audit_shape = tuple(
        (row.get("name"), str(row.get("type", "")).upper(),
         int(row.get("notnull", -1)), int(row.get("pk", -1)))
        for row in audit_columns
    )
    if audit_shape != EXPECTED_AUDIT_COLUMNS:
        return "drift"

    audit_ddl = re.sub(r"\s+", " ", str(audit.get("sql", ""))).lower()
    for event in EXPECTED_AUDIT_EVENTS:
        if f"'{event}'" not in audit_ddl:
            return "drift"
    if len(foreign_keys) != 1:
        return "drift"
    fk = foreign_keys[0]
    if (
        fk.get("table"), fk.get("from"), fk.get("to"),
        str(fk.get("on_delete", "")).upper(),
    ) != EXPECTED_TOKEN_FK:
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
        print("B62_D1_MIGRATION_062_SCHEMA=" + verdict.upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = (
            payload.get("result")
            if isinstance(payload, dict) and payload.get("success") is True
            else None
        )
        if not isinstance(rows, list) or not rows or any(
            not isinstance(item, dict) or item.get("success") is not True for item in rows
        ):
            raise ValueError("D1 additive 062 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_062_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 062 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_062_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
