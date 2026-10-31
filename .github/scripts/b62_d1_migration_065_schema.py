#!/usr/bin/env python3
"""B62 D1 migration 065 gate: Web Push device subscriptions (#5034).

065 (``apps/padiem-chat/migrations/065_claw_push_subscriptions.sql``) adds ONE
additive table, ``claw_push_subscription``, that stores the browser device
endpoint a user explicitly opted in. It stores no notification record: the
inbox records stay in the existing ``claw_task_alert`` authority.

This helper is the contract of the 065 preflight step in
``.github/workflows/b62-production-code-deploy-gate.yml``:

* it pins the approved 065 source by SHA-256, so the applied SQL is exactly the
  reviewed file;
* it proves on a real SQLite database that the SQL creates the reviewed table
  and index, that the owner uniqueness constraint refuses a duplicate endpoint,
  and that a second device for the same account is accepted;
* it reads schema metadata only (``sqlite_master``, ``PRAGMA table_info``,
  ``PRAGMA index_list``); it never reads row content, an endpoint, a key or a
  secret value, and it never emits an account, database or binding identifier.

Dispositions:
  ``MISSING``  the table is absent; 065 is applicable.
  ``EXACT``    the reviewed 065 shape is present (idempotent no-op).
  ``DRIFT``    the table exists with another shape; never mutated.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
MIGRATION = MIGRATIONS / "065_claw_push_subscriptions.sql"
TABLE = "claw_push_subscription"
INDEX = "idx_claw_push_subscription_owner"

# The applied SQL must be exactly the reviewed file.
PINNED_SHA256 = "269e06b06ef6d69454d10d3d28ec379a192619b83ff99e9fe5ce28afac500f8c"

# (name, declared type, notnull, pk) in the reviewed order.
EXPECTED_COLUMNS = (
    ("id", "TEXT", 0, 1),
    ("workspace_id", "TEXT", 1, 0),
    ("member_id", "TEXT", 1, 0),
    ("endpoint", "TEXT", 1, 0),
    ("p256dh", "TEXT", 1, 0),
    ("auth", "TEXT", 1, 0),
    ("scope", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
)

# name -> (unique, partial) for the reviewed 065 indexes.
EXPECTED_INDEXES = {
    INDEX: (0, 0),
}

QUERY = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type='table' AND name='claw_push_subscription';\n"
    "PRAGMA table_info(claw_push_subscription);\n"
    "PRAGMA index_list(claw_push_subscription);"
)


def norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def code(value: str) -> str:
    """The executable statements, with the explanatory comments removed."""
    return norm("\n".join(line.split("--", 1)[0] for line in value.splitlines()))


def _shape(connection: sqlite3.Connection, table: str) -> tuple:
    return tuple(
        (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _indexes(connection: sqlite3.Connection, table: str) -> dict:
    """Named, non-automatic indexes as name -> (unique, partial)."""
    found = {}
    for row in connection.execute(f"PRAGMA index_list({table})").fetchall():
        # seq, name, unique, origin, partial
        if str(row[3]).lower() != "c":
            continue
        found[str(row[1])] = (int(row[2]), int(row[4]))
    return found


def _seed(connection: sqlite3.Connection, *, member: str, endpoint: str, ident: str) -> None:
    connection.execute(
        f"INSERT INTO {TABLE} "
        "(id, workspace_id, member_id, endpoint, p256dh, auth, scope, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ident,
            "ws_gate",
            member,
            endpoint,
            "p256dh_gate",
            "auth_gate",
            "https://chat.example.test/",
            "2026-10-23T00:00:00Z",
            "2026-10-23T00:00:00Z",
        ),
    )


def source(path: Path | None = None) -> str:
    """Return the reviewed 065 SQL, or refuse anything that is not it."""
    target = MIGRATION if path is None else Path(path)
    text = target.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if path is None:
        if not PINNED_SHA256 or digest != PINNED_SHA256:
            raise ValueError("Migration 065 is not the pinned reviewed file")
    upper = code(text)

    # 065 is additive: one new table and one index. It must never touch an
    # existing authority, rewrite data or drop anything.
    for forbidden in (
        "delete from",
        "update ",
        "drop table",
        "drop index",
        "alter table",
        "create trigger",
        "create view",
    ):
        if forbidden in upper:
            raise ValueError("Migration 065 exceeds the reviewed additive change: " + forbidden)
    if upper.count(f"create table if not exists {TABLE}") != 1:
        raise ValueError("Migration 065 must create the reviewed table exactly once")
    if upper.count(f"create index if not exists {INDEX}") != 1:
        raise ValueError("Migration 065 must create the reviewed index exactly once")

    # Prove the SQL produces the reviewed shape on a real database.
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(text)
        if _shape(db, TABLE) != EXPECTED_COLUMNS:
            raise ValueError("Migration 065 columns do not match the reviewed shape")
        if _indexes(db, TABLE) != EXPECTED_INDEXES:
            raise ValueError("Migration 065 indexes are not the reviewed set")

        # One device endpoint is one row per account.
        _seed(db, member="usr_gate", endpoint="https://push.example.test/a", ident="push_a")
        try:
            _seed(db, member="usr_gate", endpoint="https://push.example.test/a", ident="push_a2")
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 065 lets one endpoint register twice for one account")

        # A second device for the same account is accepted.
        _seed(db, member="usr_gate", endpoint="https://push.example.test/b", ident="push_b")

        # The same endpoint for another account is a separate row.
        _seed(db, member="usr_other", endpoint="https://push.example.test/a", ident="push_c")

        if db.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] != 3:
            raise ValueError("Migration 065 owner scoping is not the reviewed one")

        # Re-applying the reviewed file is an idempotent no-op.
        db.executescript(text)
        if db.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] != 3:
            raise ValueError("Migration 065 is not idempotent")
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


def _shape_from(rows: list[dict[str, object]]) -> tuple:
    return tuple(
        (
            row.get("name"),
            str(row.get("type", "")).upper(),
            int(row.get("notnull", -1)),
            int(row.get("pk", -1)),
        )
        for row in rows
    )


def _indexes_from(rows: list[dict[str, object]]) -> dict:
    found = {}
    for row in rows:
        if str(row.get("origin", "")).lower() != "c":
            continue
        found[str(row.get("name"))] = (
            int(row.get("unique", -1)),
            int(row.get("partial", -1)),
        )
    return found


def classify(payload: object) -> str:
    objects, columns, indexes = _blocks(payload, 3)
    table_rows = [row for row in objects if row.get("name") == TABLE]
    shape = _shape_from(columns)
    if not table_rows:
        return "missing" if not shape and not indexes else "drift"
    if len(table_rows) != 1 or not isinstance(table_rows[0].get("sql"), str):
        return "drift"
    if shape != EXPECTED_COLUMNS:
        return "drift"
    if _indexes_from(indexes) != EXPECTED_INDEXES:
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        raise ValueError("expected an operation")
    action = argv[0]
    if action == "offline":
        source()
        print("B62_D1_MIGRATION_065_SOURCE_CONTRACT=PASS")
        print("PRODUCTION_MUTATION=0")
        return
    if len(argv) < 2:
        raise ValueError("expected an operation and a file")
    path = Path(argv[1])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        verdict = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_D1_MIGRATION_065_SCHEMA=" + verdict.upper())
    elif action == "apply":
        source()
        path.write_text(
            json.dumps({"sql": MIGRATION.read_text(encoding="utf-8")}), encoding="utf-8"
        )
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = (
            payload.get("result")
            if isinstance(payload, dict) and payload.get("success") is True
            else None
        )
        if (
            not isinstance(rows, list)
            or not rows
            or any(
                not isinstance(item, dict) or item.get("success") is not True
                for item in rows
            )
        ):
            raise ValueError("D1 migration 065 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_065_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 065 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_065_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
