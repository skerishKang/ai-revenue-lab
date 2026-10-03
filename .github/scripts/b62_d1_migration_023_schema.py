#!/usr/bin/env python3
"""Classify B66 CompanyProfile migration 023 from schema-only D1 evidence."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "b66_company_profile"
INDEX = "idx_b66_company_profile_workspace_updated"
COLUMNS = (
    "user_id", "workspace_id", "company", "representative", "contact_person",
    "business_number", "address", "phone", "email", "default_validity_days",
    "default_tax_mode", "created_at", "updated_at",
)
INDEX_COLUMNS = ("workspace_id", "updated_at")


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
    required = (
        "user_id text not null references users(id) on delete cascade",
        "workspace_id text not null",
        "company text",
        "representative text",
        "contact_person text",
        "business_number text",
        "address text",
        "phone text",
        "email text",
        "default_validity_days integer check (default_validity_days is null or (default_validity_days >= 0 and default_validity_days <= 3650))",
        "default_tax_mode text check (default_tax_mode is null or default_tax_mode in ('exclusive', 'inclusive', 'exempt'))",
        "created_at text not null",
        "updated_at text not null",
        "primary key (user_id, workspace_id)",
    )
    if any(fragment not in table_sql for fragment in required):
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
        print("usage: b62_d1_migration_023_schema.py <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_023_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_023_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
