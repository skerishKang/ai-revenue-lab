#!/usr/bin/env python3
"""Classify B66 quote-history migration 025 from schema-only D1 evidence.

Bounded, read-only classifier for the #3405 durable quote-history table.
It proves the migration 025 contract from `sqlite_master` plus `PRAGMA`
metadata only; it never reads application rows and never mutates anything.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "b66_quote_history"
INDEX = "idx_b66_quote_history_owner_workspace_updated"
COLUMNS = (
    "id", "user_id", "workspace_id", "quote_no", "issue_date", "saved_skill_id",
    "skill_fingerprint", "snapshot_json", "sender_json", "created_at", "updated_at",
)
PRIMARY_KEY = ("id",)
INDEX_COLUMNS = ("user_id", "workspace_id", "updated_at")
INDEX_DESCENDING = (0, 0, 1)


class SchemaEvidenceError(RuntimeError):
    pass


def _results(entry: object) -> list[dict[str, object]]:
    if not isinstance(entry, dict) or entry.get("success") is not True:
        raise SchemaEvidenceError("D1 query result is not successful")
    rows = entry.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SchemaEvidenceError("D1 query result rows are malformed")
    return rows


def _normalized_sql(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return None


def classify_schema(payload: object) -> str:
    """Return missing, exact or drift without reading application rows."""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SchemaEvidenceError("Cloudflare D1 response is not successful")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 5:
        raise SchemaEvidenceError("expected exactly five schema query results")

    objects = _results(result[0])
    columns = _results(result[1])
    index_columns = _results(result[2])
    index_detail = _results(result[3])
    foreign_keys = _results(result[4])

    by_name = {
        row.get("name"): row
        for row in objects
        if isinstance(row.get("name"), str)
    }
    table = by_name.get(TABLE)
    index = by_name.get(INDEX)

    if (
        table is None
        and index is None
        and not columns
        and not index_columns
        and not index_detail
        and not foreign_keys
    ):
        return "missing"
    if table is None or table.get("type") != "table":
        return "drift"
    if index is None or index.get("type") != "index":
        return "drift"

    # 1. eleven columns, exact names and order
    if tuple(str(row.get("name", "")) for row in columns) != COLUMNS:
        return "drift"

    # 2. single-column primary key on id
    pk = tuple(
        str(row.get("name", ""))
        for row in sorted(columns, key=lambda row: _as_int(row.get("pk")) or 0)
        if (_as_int(row.get("pk")) or 0) > 0
    )
    if pk != PRIMARY_KEY:
        return "drift"

    # 3. index column order
    if tuple(str(row.get("name", "")) for row in index_columns) != INDEX_COLUMNS:
        return "drift"

    # 4. index sort direction, including updated_at DESC (index_xinfo key columns)
    key_rows = [row for row in index_detail if _as_int(row.get("key")) == 1]
    if tuple(str(row.get("name", "")) for row in key_rows) != INDEX_COLUMNS:
        return "drift"
    if tuple(_as_int(row.get("desc")) for row in key_rows) != INDEX_DESCENDING:
        return "drift"

    # 5. additive table contract fragments
    table_sql = _normalized_sql(table.get("sql"))
    required = (
        "id text primary key",
        "user_id text not null references users(id) on delete cascade",
        "workspace_id text not null",
        "quote_no text",
        "issue_date text",
        "saved_skill_id text",
        "skill_fingerprint text",
        "snapshot_json text not null",
        "sender_json text",
        "created_at text not null",
        "updated_at text not null",
    )
    if any(fragment not in table_sql for fragment in required):
        return "drift"

    # 6. foreign key user_id -> users(id) ON DELETE CASCADE
    if len(foreign_keys) != 1:
        return "drift"
    fk = foreign_keys[0]
    if (
        fk.get("table") != "users"
        or fk.get("from") != "user_id"
        or fk.get("to") != "id"
        or str(fk.get("on_delete", "")).upper() != "CASCADE"
    ):
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: b62_d1_migration_025_schema.py <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_025_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_025_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
