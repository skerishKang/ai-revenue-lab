"""Derive and verify the B14 D1 schema from the complete migration directory.

The workflow runs this against an empty in-memory SQLite database, then compares
only remote table/column/index names with that local schema. No ledger rows or
secret values are read.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "apps" / "korean-ai-platform" / "migrations"


class SchemaError(ValueError):
    """A public-safe schema verification error."""


def migration_files(directory: Path = MIGRATIONS) -> list[Path]:
    """Return the SQL files in the same lexical order used by Wrangler."""
    if not directory.is_dir():
        raise SchemaError("B14_MIGRATIONS_DIRECTORY_MISSING")
    files = sorted(path for path in directory.glob("*.sql") if path.is_file())
    if not files:
        raise SchemaError("B14_MIGRATIONS_DIRECTORY_EMPTY")
    return files


def migration_names(directory: Path = MIGRATIONS) -> list[str]:
    return [path.name for path in migration_files(directory)]


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def schema_from_migrations(directory: Path = MIGRATIONS) -> dict[str, Any]:
    """Apply each migration to a blank SQLite database and return its schema."""
    db = sqlite3.connect(":memory:")
    try:
        db.execute("PRAGMA foreign_keys = ON")
        for path in migration_files(directory):
            try:
                db.executescript(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                raise SchemaError(f"B14_MIGRATION_UNREADABLE:{path.name}") from None
            except sqlite3.Error as exc:
                raise SchemaError(
                    f"B14_MIGRATION_NOT_REPLAYABLE:{path.name}:{type(exc).__name__}"
                ) from None

        tables: dict[str, list[str]] = {}
        table_names = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for table in table_names:
            tables[table] = [
                row[1]
                for row in db.execute(
                    f"PRAGMA table_info({_quoted_identifier(table)})"
                )
            ]

        indexes = sorted(
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name NOT LIKE 'sqlite_autoindex%' ORDER BY name"
            )
        )
        return {"tables": tables, "indexes": indexes}
    finally:
        db.close()


def _query_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SchemaError("B14_REMOTE_SCHEMA_JSON_INVALID") from None

    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            return payload["results"]
        raise SchemaError("B14_REMOTE_SCHEMA_RESULTS_MISSING")
    if isinstance(payload, list):
        rows: list[dict[str, Any]] = []
        for block in payload:
            if isinstance(block, dict) and isinstance(block.get("results"), list):
                rows.extend(block["results"])
            elif isinstance(block, dict):
                rows.append(block)
            else:
                raise SchemaError("B14_REMOTE_SCHEMA_ROW_INVALID")
        return rows
    raise SchemaError("B14_REMOTE_SCHEMA_PAYLOAD_INVALID")


def remote_tables_from_rows(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for row in rows:
        table = row.get("table_name")
        column = row.get("column_name")
        if not isinstance(table, str) or not isinstance(column, str):
            raise SchemaError("B14_REMOTE_COLUMN_ROW_INVALID")
        # Wrangler owns this bookkeeping table; it is outside application SQL.
        if table == "d1_migrations":
            continue
        tables.setdefault(table, []).append(column)
    return tables


def verify_remote_schema(columns_path: Path, indexes_path: Path) -> dict[str, Any]:
    expected = schema_from_migrations()
    remote_tables = remote_tables_from_rows(_query_rows(columns_path))
    remote_indexes = []
    for row in _query_rows(indexes_path):
        name = row.get("name")
        if not isinstance(name, str):
            raise SchemaError("B14_REMOTE_INDEX_ROW_INVALID")
        remote_indexes.append(name)
    remote_indexes.sort()

    if remote_tables != expected["tables"]:
        raise SchemaError(
            "B14_REMOTE_TABLE_COLUMN_MISMATCH:"
            f"expected={expected['tables']!r};found={remote_tables!r}"
        )
    if remote_indexes != expected["indexes"]:
        raise SchemaError(
            "B14_REMOTE_INDEX_MISMATCH:"
            f"expected={expected['indexes']!r};found={remote_indexes!r}"
        )
    return expected


def _report_schema(schema: dict[str, Any]) -> None:
    print("B14_LEDGER_SCHEMA_ASSERT=PASS")
    print("B14_LEDGER_TABLE_ASSERT=PASS")
    print("B14_LEDGER_TABLES=" + ",".join(schema["tables"]))
    print(
        "B14_LEDGER_COLUMNS="
        + ",".join(
            f"{table}:{len(columns)}" for table, columns in schema["tables"].items()
        )
    )
    print("B14_LEDGER_INDEX_ASSERT=PASS")
    print(f"B14_LEDGER_INDEXES={len(schema['indexes'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-migrations", action="store_true")
    parser.add_argument("--remote-columns", type=Path)
    parser.add_argument("--remote-indexes", type=Path)
    args = parser.parse_args(argv)

    if not args.print_migrations and (
        args.remote_columns is None or args.remote_indexes is None
    ):
        parser.error("provide --print-migrations or both remote schema files")
    try:
        if args.print_migrations:
            print("D1_MIGRATIONS=" + ",".join(migration_names()))
            return 0
        schema = verify_remote_schema(args.remote_columns, args.remote_indexes)
    except SchemaError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    _report_schema(schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
