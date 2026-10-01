#!/usr/bin/env python3
"""Classify additive B66 Saved Quote Skill migration 021 without row-data access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "b66_saved_quote_skill"
INDEX = "idx_b66_saved_quote_skill_owner_workspace_status"
EXPECTED_COLUMNS = (
    "id", "user_id", "workspace_id", "skill_id", "skill_name",
    "skill_fingerprint", "skill_version", "skill_json", "status",
    "created_at", "updated_at",
)
EXPECTED_INDEX_COLUMNS = ("user_id", "workspace_id", "status", "updated_at")


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


def classify_schema(payload: object) -> str:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SchemaEvidenceError("Cloudflare D1 response is not successful")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 3:
        raise SchemaEvidenceError("expected exactly three schema query results")

    objects = _results(result[0])
    columns = _results(result[1])
    index_columns = _results(result[2])
    by_name = {
        row.get("name"): row
        for row in objects
        if isinstance(row.get("name"), str)
    }
    table = by_name.get(TABLE)
    index = by_name.get(INDEX)

    if table is None and index is None and not columns and not index_columns:
        return "missing"
    if table is None or table.get("type") != "table":
        return "drift"
    if index is None or index.get("type") != "index":
        return "drift"
    if tuple(str(row.get("name", "")) for row in columns) != EXPECTED_COLUMNS:
        return "drift"
    if tuple(str(row.get("name", "")) for row in index_columns) != EXPECTED_INDEX_COLUMNS:
        return "drift"

    table_sql = _normalized_sql(table.get("sql"))
    index_sql = _normalized_sql(index.get("sql"))
    required_table = (
        "id text primary key",
        "user_id text not null references users(id) on delete cascade",
        "workspace_id text not null",
        "skill_id text not null",
        "skill_name text not null",
        "skill_fingerprint text not null",
        "skill_version integer not null check (skill_version >= 1)",
        "skill_json text not null",
        "status text not null check (status in ('approved', 'disabled'))",
        "created_at text not null",
        "updated_at text not null",
        "unique (user_id, workspace_id, skill_id, skill_version)",
    )
    if any(fragment not in table_sql for fragment in required_table):
        return "drift"

    expected_index = (
        f"create index {INDEX} on {TABLE} "
        "(user_id, workspace_id, status, updated_at desc)"
    )
    if expected_index not in index_sql:
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: b62_d1_migration_021_schema.py <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_021_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_021_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
