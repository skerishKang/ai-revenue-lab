#!/usr/bin/env python3
"""Classify the live B62 Claw document-metadata schema without row-data access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "claw_document_metadata"
INDEX = "idx_claw_document_metadata_tenant_active"
EXPECTED_COLUMNS = (
    "document_id",
    "tenant_id",
    "object_key",
    "filename",
    "media_type",
    "byte_length",
    "created_at",
    "expires_at",
    "deleted_at",
)
EXPECTED_INDEX_COLUMNS = ("tenant_id", "deleted_at", "expires_at")


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
    """Return ``exact``, ``missing`` or ``drift`` from bounded schema-only evidence."""
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
    table_row = by_name.get(TABLE)
    index_row = by_name.get(INDEX)

    if table_row is None and index_row is None and not columns and not index_columns:
        return "missing"
    if table_row is None or index_row is None:
        return "drift"
    if table_row.get("type") != "table" or index_row.get("type") != "index":
        return "drift"

    column_names = tuple(str(row.get("name", "")) for row in columns)
    if column_names != EXPECTED_COLUMNS:
        return "drift"

    index_names = tuple(str(row.get("name", "")) for row in index_columns)
    if index_names != EXPECTED_INDEX_COLUMNS:
        return "drift"

    table_sql = _normalized_sql(table_row.get("sql"))
    index_sql = _normalized_sql(index_row.get("sql"))
    required_table_fragments = (
        "document_id text primary key",
        "tenant_id text not null",
        "object_key text not null unique",
        "filename text not null",
        "media_type text not null",
        "byte_length integer not null check",
        "byte_length > 0",
        "byte_length <= 10485760",
        "created_at text not null",
        "expires_at text not null",
        "deleted_at text",
    )
    if any(fragment not in table_sql for fragment in required_table_fragments):
        return "drift"
    if "on claw_document_metadata (tenant_id, deleted_at, expires_at)" not in index_sql:
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: b62_d1_migration_008_schema.py <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_008_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_008_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
