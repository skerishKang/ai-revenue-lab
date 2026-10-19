#!/usr/bin/env python3
"""Classify the live B62 P01 decision-receipt schema without row-data access.

#4522: migration 040 is an additive ``ALTER TABLE ... ADD COLUMN released_at
TEXT`` on ``claw_web_xlsx_p01_decision_receipts`` (schema 031). The merged B62
P01 code reads that column, so the canonical live private D1 must already carry
it before the new Worker code is uploaded or activated.

This helper reads schema metadata only (``sqlite_master`` + ``PRAGMA
table_info``). It never reads row contents, user data or secret values, and it
never emits an account, database or binding identifier.

Dispositions:
  ``exact``   031 columns in order PLUS the additive ``released_at`` column.
  ``pre_040`` 031 columns in order, no ``released_at``; 040 is applicable.
  ``missing`` the receipts table is absent (031 itself is not applied).
  ``drift``   any other shape; never mutated.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "claw_web_xlsx_p01_decision_receipts"
BASELINE_COLUMNS = (
    "request_ref",
    "selection_ref",
    "user_id",
    "workspace_id",
    "run_id",
    "source_sha256",
    "pause_id",
    "outcome",
    "state",
    "created_at",
    "updated_at",
)
ADDED_COLUMN = "released_at"
EXPECTED_COLUMNS = BASELINE_COLUMNS + (ADDED_COLUMN,)

# (name, declared type, notnull, pk) for the exact 031 + 040 shape.
# SQLite does not imply NOT NULL from ``TEXT PRIMARY KEY``, so request_ref
# reports notnull=0 while remaining the primary key; released_at is the only
# other nullable column (the additive 040 column).
_EXPECTED_SHAPE = (
    ("request_ref", "TEXT", 0, 1),
    ("selection_ref", "TEXT", 1, 0),
    ("user_id", "TEXT", 1, 0),
    ("workspace_id", "TEXT", 1, 0),
    ("run_id", "TEXT", 1, 0),
    ("source_sha256", "TEXT", 1, 0),
    ("pause_id", "TEXT", 1, 0),
    ("outcome", "TEXT", 1, 0),
    ("state", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
    ("released_at", "TEXT", 0, 0),
)

# Migration 031 table text, plus the additive column exactly as SQLite rewrites
# it after ``ALTER TABLE ... ADD COLUMN``.
_BASELINE_SQL_FRAGMENTS = (
    "request_ref text primary key",
    "selection_ref text not null",
    "user_id text not null",
    "workspace_id text not null",
    "run_id text not null",
    "source_sha256 text not null check(length(source_sha256)=64)",
    "pause_id text not null unique",
    "outcome text not null check(outcome in ('approve','deny'))",
    "state text not null check(state in ('dispatching','denied','confirmed'))",
    "created_at text not null",
    "updated_at text not null",
    "foreign key(request_ref) references claw_web_xlsx_p01_requests(request_ref)",
)
_ADDITIVE_SQL_FRAGMENT = "updated_at text not null, released_at text"


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


def _shape_ok(columns: list[dict[str, object]], *, with_released: bool) -> bool:
    expected = _EXPECTED_SHAPE if with_released else _EXPECTED_SHAPE[:-1]
    if len(columns) != len(expected):
        return False
    for row, (name, declared_type, notnull, pk) in zip(columns, expected):
        if str(row.get("name", "")) != name:
            return False
        if str(row.get("type", "")).upper() != declared_type:
            return False
        if int(row.get("notnull", -1)) != notnull:
            return False
        if int(row.get("pk", -1)) != pk:
            return False
        if row.get("dflt_value") is not None:
            return False
    return True


def classify_schema(payload: object) -> str:
    """Return ``exact``, ``pre_040``, ``missing`` or ``drift`` from schema-only evidence."""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SchemaEvidenceError("Cloudflare D1 response is not successful")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 2:
        raise SchemaEvidenceError("expected exactly two schema query results")

    objects = _results(result[0])
    columns = _results(result[1])

    table_rows = [
        row for row in objects
        if isinstance(row.get("name"), str) and row.get("name") == TABLE
    ]
    if len(table_rows) > 1:
        return "drift"
    if not table_rows and not columns:
        return "missing"
    if not table_rows:
        return "drift"
    table_row = table_rows[0]
    if table_row.get("type") != "table":
        return "drift"

    names = tuple(str(row.get("name", "")) for row in columns)
    if names not in (BASELINE_COLUMNS, EXPECTED_COLUMNS):
        return "drift"

    table_sql = _normalized_sql(table_row.get("sql"))
    if any(fragment not in table_sql for fragment in _BASELINE_SQL_FRAGMENTS):
        return "drift"

    if names == BASELINE_COLUMNS:
        return "pre_040" if _shape_ok(columns, with_released=False) else "drift"
    if not _shape_ok(columns, with_released=True):
        return "drift"
    # The column must be the additive ALTER result, not a redefined table.
    if _ADDITIVE_SQL_FRAGMENT not in table_sql:
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: b62_d1_migration_040_schema.py <d1-query-response.json>",
            file=sys.stderr,
        )
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_040_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_040_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
