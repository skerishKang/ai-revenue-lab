#!/usr/bin/env python3
"""Classify B66 private quote asset migration 022 from schema-only D1 evidence."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "b66_quote_asset"
INDEX = "idx_b66_quote_asset_owner_workspace_status"
COLUMNS = (
    "id", "user_id", "workspace_id", "asset_kind", "media_type",
    "object_key", "byte_length", "sha256", "status", "created_at", "updated_at",
)
INDEX_COLUMNS = ("user_id", "workspace_id", "status", "updated_at")

# #4379 releases the 256 KiB byte ceiling of migration 022 with a forward
# rebuild, so the probe accepts exactly the two reviewed shapes of the column
# CHECK: the released one and the one after the release. The non-empty lower
# bound is part of both.
_BYTE_LENGTH_CHECK = re.compile(r"byte_length integer not null check \([^)]*\)")
_ALLOWED_BYTE_LENGTH_CHECKS = (
    "byte_length integer not null check (byte_length >= 1 and byte_length <= 262144)",
    "byte_length integer not null check (byte_length >= 1)",
)


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
    """Return missing, exact or drift without reading application rows."""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SchemaEvidenceError("Cloudflare D1 response is not successful")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 4:
        raise SchemaEvidenceError("expected exactly four schema query results")

    objects = _results(result[0])
    columns = _results(result[1])
    index_columns = _results(result[2])
    foreign_keys = _results(result[3])
    by_name = {
        row.get("name"): row
        for row in objects
        if isinstance(row.get("name"), str)
    }
    table = by_name.get(TABLE)
    index = by_name.get(INDEX)

    if table is None and index is None and not columns and not index_columns and not foreign_keys:
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
    # #4379 releases the 256 KiB byte ceiling by a forward rebuild, so the same
    # pre-deploy probe must accept the table on both sides of that release. The
    # structural contract the B66 code depends on is still pinned: the column has
    # a CHECK and it still refuses a zero-length row. Any other ceiling is
    # drift, not a third accepted shape.
    required = (
        "id text primary key",
        "user_id text not null references users(id) on delete cascade",
        "workspace_id text not null",
        "asset_kind text not null check (asset_kind in ('logo', 'stamp'))",
        "media_type text not null check (media_type in ('image/png', 'image/jpeg', 'image/webp'))",
        "object_key text not null unique",
        "sha256 text not null",
        "status text not null check (status in ('approved', 'disabled'))",
        "created_at text not null",
        "updated_at text not null",
    )
    if any(fragment not in table_sql for fragment in required):
        return "drift"

    byte_length_check = _BYTE_LENGTH_CHECK.search(table_sql)
    if byte_length_check is None:
        return "drift"
    if byte_length_check.group(0) not in _ALLOWED_BYTE_LENGTH_CHECKS:
        return "drift"

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
        print("usage: b62_d1_migration_022_schema.py <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_022_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_022_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
