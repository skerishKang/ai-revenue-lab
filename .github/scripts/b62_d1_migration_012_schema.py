#!/usr/bin/env python3
"""Classify additive B62 password-auth migration 012 without row-data access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

USERS_TABLE = "users"
PASSWORD_TABLE = "password_credentials"
PASSWORD_INDEX = "idx_password_credentials_username"

USERS_COLUMNS = (
    "id",
    "auth_provider",
    "provider_subject",
    "email",
    "display_name",
    "picture_url",
    "created_at",
    "updated_at",
)
PASSWORD_COLUMNS = (
    "user_id",
    "username",
    "password_hash",
    "failed_attempts",
    "locked_until",
    "created_at",
    "updated_at",
)
PASSWORD_INDEX_COLUMNS = ("username",)


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
    if not isinstance(result, list) or len(result) != 4:
        raise SchemaEvidenceError("expected exactly four schema query results")

    objects = _results(result[0])
    users_columns = _results(result[1])
    password_columns = _results(result[2])
    index_columns = _results(result[3])

    by_name = {
        row.get("name"): row
        for row in objects
        if isinstance(row.get("name"), str)
    }
    users = by_name.get(USERS_TABLE)
    credentials = by_name.get(PASSWORD_TABLE)
    password_index = by_name.get(PASSWORD_INDEX)

    if users is None or users.get("type") != "table":
        return "drift"
    if tuple(str(row.get("name", "")) for row in users_columns) != USERS_COLUMNS:
        return "drift"

    users_sql = _normalized_sql(users.get("sql"))
    if "check (auth_provider = 'google')" not in users_sql:
        return "drift"

    if credentials is None and password_index is None and not password_columns and not index_columns:
        return "missing"
    if credentials is None or credentials.get("type") != "table":
        return "drift"
    if password_index is None or password_index.get("type") != "index":
        return "drift"
    if tuple(str(row.get("name", "")) for row in password_columns) != PASSWORD_COLUMNS:
        return "drift"
    if tuple(str(row.get("name", "")) for row in index_columns) != PASSWORD_INDEX_COLUMNS:
        return "drift"

    credentials_sql = _normalized_sql(credentials.get("sql"))
    required = (
        "user_id text primary key",
        "references users(id) on delete cascade",
        "username text not null collate nocase unique",
        "password_hash text not null",
        "failed_attempts integer not null default 0",
        "locked_until text",
        "created_at text not null",
        "updated_at text not null",
    )
    if any(fragment not in credentials_sql for fragment in required):
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: b62_d1_migration_012_schema.py <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        state = classify_schema(payload)
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print(f"B62_D1_MIGRATION_012_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_D1_MIGRATION_012_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
