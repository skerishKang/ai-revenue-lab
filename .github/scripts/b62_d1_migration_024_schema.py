#!/usr/bin/env python3
"""Classify additive B62 auth-abuse migration 024 without row-data access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "auth_login_abuse_buckets"
INDEX = "idx_auth_login_abuse_buckets_updated_at"
COLUMNS = (
    "subject_type",
    "subject_key",
    "bucket_start",
    "failure_count",
    "updated_at",
)
INDEX_COLUMNS = ("updated_at",)


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
    """Return missing, exact or drift from bounded schema-only evidence."""
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
    if tuple(str(row.get("name", "")) for row in columns) != COLUMNS:
        return "drift"
    if tuple(str(row.get("name", "")) for row in index_columns) != INDEX_COLUMNS:
        return "drift"

    table_sql = _normalized_sql(table.get("sql"))
    required = (
        "subject_type text not null",
        "subject_key text not null",
        "bucket_start text not null",
        "failure_count integer not null default 0",
        "updated_at text not null",
        "primary key (subject_type, subject_key, bucket_start)",
        "'identifier'",
        "'network'",
        "'global'",
        "failure_count >= 0",
    )
    if any(fragment not in table_sql for fragment in required):
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: b62_d1_migration_024_schema.py <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_024_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_024_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
