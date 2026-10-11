#!/usr/bin/env python3
"""#3396 migration 028: schema-only D1 guard. No application row reads."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/028_b66_guided_draft.sql"
TABLE = "b66_guided_draft"
EXPECTED_SOURCE = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS b66_guided_draft (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, workspace_id)
);
"""
QUERY = """SELECT name,type,sql FROM sqlite_master WHERE name IN ('users','b66_guided_draft') ORDER BY name;
PRAGMA table_info(b66_guided_draft);
PRAGMA index_list(b66_guided_draft);
PRAGMA foreign_key_list(b66_guided_draft);"""


def norm(value: str) -> str:
    value = re.sub(r"--[^\n]*", "", value)
    value = re.sub(r"\s*([(),;=])\s*", r"\1", value.strip().lower())
    return re.sub(r"\s+", " ", value).strip()


def source_sql() -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    if norm(sql) != norm(EXPECTED_SOURCE):
        raise ValueError("028 migration source differs from reviewed additive-only SQL")
    return sql


def expected_table_sql() -> str:
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
        db.executescript(source_sql())
        return norm(db.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (TABLE,)
        ).fetchone()[0])
    finally:
        db.close()


def query_results(payload: object, n: int) -> list[list[dict]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 query request was not successful")
    blocks = payload.get("result")
    if not isinstance(blocks, list) or len(blocks) != n:
        raise ValueError("unexpected D1 schema query shape")
    result = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("success") is not True:
            raise ValueError("D1 schema query contains an error")
        rows = block.get("results")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("invalid D1 schema result rows")
        result.append(rows)
    return result


def classify(payload: object) -> str:
    objects, columns, indexes, fks = query_results(payload, 4)
    names = {o.get("name"): o for o in objects}
    if names.get("users", {}).get("type") != "table":
        return "drift"  # The parent account table is mandatory.
    entry = names.get(TABLE)
    if entry is None:
        return "missing" if not columns and not indexes and not fks else "drift"
    if entry.get("type") != "table" or norm(str(entry.get("sql") or "")) != expected_table_sql():
        return "drift"
    expected = (
        ("user_id", "TEXT", 1, 1),
        ("workspace_id", "TEXT", 1, 2),
        ("state_json", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    )
    actual = tuple(
        (r.get("name"), str(r.get("type") or "").upper(), r.get("notnull"), r.get("pk"))
        for r in columns
    )
    if actual != expected:
        return "drift"
    if len(indexes) != 1 or any(
        r.get("origin") != "pk" or r.get("unique") != 1 or r.get("partial") != 0
        for r in indexes
    ):
        return "drift"
    if len(fks) != 1 or not all(
        fks[0].get(k) == v
        for k, v in {"table": "users", "from": "user_id", "to": "id"}.items()
    ) or str(fks[0].get("on_delete") or "").upper() != "CASCADE":
        return "drift"
    return "exact"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: b62_d1_migration_028_schema.py <query|classify|apply|check-apply> <file>", file=sys.stderr)
        return 2
    action, path = sys.argv[1:]
    try:
        if action == "query":
            source_sql()
            Path(path).write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
        elif action == "classify":
            value = classify(json.loads(Path(path).read_text(encoding="utf-8")))
            print("B62_D1_MIGRATION_028_SCHEMA=" + value.upper())
        elif action == "apply":
            Path(path).write_text(json.dumps({"sql": source_sql()}), encoding="utf-8")
        elif action == "check-apply":
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            blocks = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
            if not isinstance(blocks, list) or not blocks or any(
                not isinstance(block, dict) or block.get("success") is not True for block in blocks
            ):
                raise ValueError("D1 apply API reported an error")
            print("B62_D1_MIGRATION_028_APPLY_RESPONSE=PASS")
        else:
            raise ValueError("unsupported 028 gate action")
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        print("B62_D1_MIGRATION_028_GATE=FAIL: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
