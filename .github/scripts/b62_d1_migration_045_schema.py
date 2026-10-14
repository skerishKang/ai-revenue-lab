#!/usr/bin/env python3
"""B66 D1 migration 045: exact schema-only owner-scoped transcript archive guard."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/045_b66_guided_transcript.sql"
TABLE = "b66_guided_transcript"
INDEX = "idx_b66_guided_transcript_recent"
EXPECTED_SOURCE = "-- B66 deterministic CGI Guided question/answer history (#4657 follow-up).\n-- Private owner/workspace scoped; independent of B66 AI model conversation history.\n-- Retained when the in-progress #028 Guided slot is cleared on quote completion.\nPRAGMA foreign_keys = ON;\nCREATE TABLE IF NOT EXISTS b66_guided_transcript (\n  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n  workspace_id TEXT NOT NULL,\n  conversation_id TEXT NOT NULL,\n  messages_json TEXT NOT NULL,\n  updated_at TEXT NOT NULL,\n  PRIMARY KEY (user_id, workspace_id, conversation_id)\n);\nCREATE INDEX IF NOT EXISTS idx_b66_guided_transcript_recent\n  ON b66_guided_transcript(user_id, workspace_id, updated_at DESC);\n"
QUERY = """SELECT name,type,sql FROM sqlite_master WHERE name IN ('users','b66_guided_transcript','idx_b66_guided_transcript_recent') ORDER BY name;
PRAGMA table_info(b66_guided_transcript);
PRAGMA index_list(b66_guided_transcript);
PRAGMA foreign_key_list(b66_guided_transcript);
PRAGMA index_info(idx_b66_guided_transcript_recent);"""


def norm(value: str) -> str:
    value = re.sub(r"--[^\n]*", "", value)
    value = re.sub(r"\s*([(),;=])\s*", r"\1", value.strip().lower())
    return re.sub(r"\s+", " ", value).strip()


def source_sql() -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    if norm(sql) != norm(EXPECTED_SOURCE):
        raise ValueError("045 migration differs from reviewed additive-only source")
    return sql


def expected_objects() -> tuple[str, str]:
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(source_sql())
        return tuple(norm(db.execute("SELECT sql FROM sqlite_master WHERE name=?", (x,)).fetchone()[0])
                     for x in (TABLE, INDEX))
    finally:
        db.close()


def query_results(payload: object, count: int) -> list[list[dict]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 query unsuccessful")
    blocks = payload.get("result")
    if not isinstance(blocks, list) or len(blocks) != count:
        raise ValueError("unexpected D1 schema query shape")
    output = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("success") is not True:
            raise ValueError("D1 schema query contains failure")
        rows = block.get("results")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid D1 schema rows")
        output.append(rows)
    return output


def classify(payload: object) -> str:
    objects, columns, indexes, fks, index_columns = query_results(payload, 5)
    named = {row.get("name"): row for row in objects}
    if named.get("users", {}).get("type") != "table":
        return "drift"
    if TABLE not in named and INDEX not in named:
        return "missing" if not columns and not indexes and not fks and not index_columns else "drift"
    if TABLE not in named or INDEX not in named:
        return "drift"
    expected_table, expected_index = expected_objects()
    if named[TABLE].get("type") != "table" or norm(str(named[TABLE].get("sql") or "")) != expected_table:
        return "drift"
    if named[INDEX].get("type") != "index" or norm(str(named[INDEX].get("sql") or "")) != expected_index:
        return "drift"
    actual_cols = tuple((x.get("name"), str(x.get("type") or "").upper(), x.get("notnull"), x.get("pk")) for x in columns)
    desired_cols = (
        ("user_id", "TEXT", 1, 1),
        ("workspace_id", "TEXT", 1, 2),
        ("conversation_id", "TEXT", 1, 3),
        ("messages_json", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    )
    if actual_cols != desired_cols:
        return "drift"
    if len(indexes) != 2:
        return "drift"
    ordinary = [row for row in indexes if row.get("name") == INDEX]
    pk = [row for row in indexes if row.get("origin") == "pk"]
    if (len(ordinary) != 1 or ordinary[0].get("unique") != 0 or
        ordinary[0].get("origin") != "c" or ordinary[0].get("partial") != 0 or
        len(pk) != 1 or pk[0].get("unique") != 1):
        return "drift"
    if len(fks) != 1 or any(fks[0].get(k) != v for k, v in
                            {"table":"users","from":"user_id","to":"id","on_delete":"CASCADE"}.items()):
        return "drift"
    if [(x.get("seqno"), x.get("name")) for x in index_columns] != [
        (0, "user_id"), (1, "workspace_id"), (2, "updated_at")
    ]:
        return "drift"
    return "exact"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: migration_045 <query|classify|apply|check-apply> <file>", file=sys.stderr)
        return 2
    action, raw_path = sys.argv[1:]
    path = Path(raw_path)
    try:
        if action == "query":
            source_sql()
            path.write_text(json.dumps({"sql":QUERY}), encoding="utf-8")
        elif action == "classify":
            print("B62_D1_MIGRATION_045_SCHEMA=" + classify(json.loads(path.read_text(encoding="utf-8"))).upper())
        elif action == "apply":
            path.write_text(json.dumps({"sql":source_sql()}), encoding="utf-8")
        elif action == "check-apply":
            result = json.loads(path.read_text(encoding="utf-8"))
            blocks = result.get("result") if isinstance(result, dict) and result.get("success") is True else None
            if not isinstance(blocks, list) or len(blocks) < 2 or any(
                    not isinstance(x, dict) or x.get("success") is not True for x in blocks):
                raise ValueError("045 D1 apply returned unsuccessful statements")
            print("B62_D1_MIGRATION_045_APPLY_RESPONSE=PASS")
        else:
            raise ValueError("unsupported migration gate action")
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        print("B62_D1_MIGRATION_045_GATE=FAIL: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
