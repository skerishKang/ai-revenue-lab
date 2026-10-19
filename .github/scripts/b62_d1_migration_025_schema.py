#!/usr/bin/env python3
"""Classify B66 quote-history migration 025 from schema-only D1 evidence.

Bounded, read-only classifier for the #3405 durable quote-history table.
It proves the migration 025 contract from `sqlite_master` plus `PRAGMA`
metadata only; it never reads application rows and never mutates anything.

The table contract is matched **exactly**, not by substring: the CREATE TABLE
body is split into its top-level definitions and compared, one by one, to the
reviewed migration 025 definition. Any added constraint that the reviewed
migration does not contain is therefore drift, including

* an added ``NOT NULL`` (e.g. ``quote_no TEXT NOT NULL``),
* an added column or table ``CHECK`` (e.g. ``CHECK (0)``),
* an added ``DEFAULT`` or any other extra column/table clause.

The index is likewise proven to be the *reviewed* index:

* it is owned by ``b66_quote_history`` (present in ``PRAGMA index_list`` for
  that table, and its ``sqlite_master`` SQL names that table);
* it is not a UNIQUE index; and
* it is not a partial index (no ``WHERE`` clause).

Two further index properties are proven from ``PRAGMA`` metadata:

* **no extra index** — apart from the reviewed index, the only index allowed on
  the table is the one SQLite creates for the ``id`` primary key (``origin =
  'pk'``). Any other index (``origin = 'c'`` with a different name, or ``origin
  = 'u'`` from a UNIQUE constraint) is drift; this rejects an added
  ``CREATE UNIQUE INDEX ... (quote_no)`` that the reviewed migration does not
  contain; and
* **default collation** — every key column of the reviewed index must use the
  ``BINARY`` collation, so an index column written as ``user_id COLLATE NOCASE``
  is drift.
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
# The reviewed index uses SQLite's default BINARY collation on every key column.
INDEX_COLLATIONS = ("BINARY", "BINARY", "BINARY")

# The reviewed migration 025 CREATE TABLE body, normalized (whitespace collapsed,
# lowercased) and split into its top-level definitions. Matched exactly.
TABLE_DEFINITION = (
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


def _table_definition_parts(table_sql: str) -> tuple[str, ...] | None:
    """Split the CREATE TABLE body into its top-level definitions.

    Commas inside a nested clause (e.g. ``CHECK (x IN (1, 2))``) do not split.
    Returns None when the statement is not a recognizable CREATE TABLE.
    """
    match = re.search(
        rf"create table (?:if not exists )?{re.escape(TABLE)}\s*\((.*)\)\s*$",
        table_sql,
        re.S,
    )
    if match is None:
        return None
    body = match.group(1)
    parts: list[str] = []
    depth = 0
    buffer: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    parts.append("".join(buffer))
    return tuple(
        re.sub(r"\s+", " ", part).strip().lower()
        for part in parts
        if part.strip()
    )


def _index_is_reviewed(index: object, index_list: list[dict[str, object]]) -> bool:
    """Prove the table carries only the reviewed non-unique, non-partial index.

    The reviewed index must be owned by ``b66_quote_history`` exactly once; every
    *other* index on the table must be the primary-key autoindex SQLite creates
    for ``id TEXT PRIMARY KEY`` (``origin = 'pk'``). Any other index — a second
    ``CREATE INDEX`` or a UNIQUE constraint/``CREATE UNIQUE INDEX`` — is drift.
    """
    # 1. owned by b66_quote_history: it must be listed for that table, exactly once.
    owned = [row for row in index_list if row.get("name") == INDEX]
    if len(owned) != 1:
        return False
    entry = owned[0]
    if _as_int(entry.get("unique")) != 0:
        return False
    if _as_int(entry.get("partial")) != 0:
        return False

    # 2. no extra index: every other index must be the id primary-key autoindex.
    for row in index_list:
        if row.get("name") == INDEX:
            continue
        if str(row.get("origin")) != "pk":
            return False

    # 3. sqlite_master SQL: same table, not UNIQUE, no WHERE (partial) clause.
    index_sql = _normalized_sql(index.get("sql"))
    if f"on {TABLE}" not in index_sql:
        return False
    if re.search(r"\bunique\b", index_sql):
        return False
    if re.search(r"\bwhere\b", index_sql):
        return False
    return True


def classify_schema(payload: object) -> str:
    """Return missing, exact or drift without reading application rows."""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SchemaEvidenceError("Cloudflare D1 response is not successful")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 6:
        raise SchemaEvidenceError("expected exactly six schema query results")

    objects = _results(result[0])
    columns = _results(result[1])
    index_list = _results(result[2])
    index_columns = _results(result[3])
    index_detail = _results(result[4])
    foreign_keys = _results(result[5])

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
        and not index_list
        and not index_columns
        and not index_detail
        and not foreign_keys
    ):
        return "missing"
    if table is None or table.get("type") != "table":
        return "drift"
    if index is None or index.get("type") != "index":
        return "drift"

    # 1. the index is the reviewed index of this table (owned, non-unique, non-partial)
    if not _index_is_reviewed(index, index_list):
        return "drift"

    # 2. the CREATE TABLE body matches the reviewed migration 025 definition exactly;
    #    any added NOT NULL / CHECK / DEFAULT / extra clause is drift.
    definition = _table_definition_parts(_normalized_sql(table.get("sql")))
    if definition is None or definition != TABLE_DEFINITION:
        return "drift"

    # 3. eleven columns, exact names and order
    if tuple(str(row.get("name", "")) for row in columns) != COLUMNS:
        return "drift"

    # 4. single-column primary key on id
    pk = tuple(
        str(row.get("name", ""))
        for row in sorted(columns, key=lambda row: _as_int(row.get("pk")) or 0)
        if (_as_int(row.get("pk")) or 0) > 0
    )
    if pk != PRIMARY_KEY:
        return "drift"

    # 5. index column order
    if tuple(str(row.get("name", "")) for row in index_columns) != INDEX_COLUMNS:
        return "drift"

    # 6. index sort direction, including updated_at DESC (index_xinfo key columns)
    key_rows = [row for row in index_detail if _as_int(row.get("key")) == 1]
    if tuple(str(row.get("name", "")) for row in key_rows) != INDEX_COLUMNS:
        return "drift"
    if tuple(_as_int(row.get("desc")) for row in key_rows) != INDEX_DESCENDING:
        return "drift"

    # 7. index collation: every key column must use the default BINARY collation,
    #    so a column written as `user_id COLLATE NOCASE` is drift.
    if tuple(
        str(row.get("coll", "")).strip().upper() for row in key_rows
    ) != INDEX_COLLATIONS:
        return "drift"

    # 8. foreign key user_id -> users(id) ON DELETE CASCADE
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
