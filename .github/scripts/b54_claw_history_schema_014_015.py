#!/usr/bin/env python3
"""Bounded, *read-only* production D1 Claw history migration 014/015 classifier.

Uses sqlite_master and PRAGMA metadata only; never reads user rows, writes data,
or prints Worker binding IDs. The preexisting 009 EXACT comparator intentionally
cannot consider additive 014/015 schema valid. This one can.
"""
from __future__ import annotations

import json
import sys

BASE_COLUMNS = (
    "id", "user_id", "run_id", "channel", "action", "title", "status",
    "created_at", "updated_at", "result_summary", "artifact_document_id",
    "artifact_filename", "artifact_media_type",
)
HISTORY_INDEX = "idx_claw_run_history_user_created"
TABLE = "claw_run_history"
QUERIES = (
    "SELECT name,type,sql FROM sqlite_master "
    "WHERE name IN ('claw_run_history','idx_claw_run_history_user_created') "
    "ORDER BY name;"
    "PRAGMA table_info(claw_run_history);"
    "PRAGMA index_info(idx_claw_run_history_user_created);"
)


class SchemaEvidenceError(ValueError):
    pass


def _rows(part: object) -> list[dict]:
    if not isinstance(part, dict) or part.get("success") is not True:
        raise SchemaEvidenceError("D1 metadata query failed")
    data = part.get("results")
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise SchemaEvidenceError("D1 metadata query has malformed result")
    return data


def classify(payload: object) -> str:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SchemaEvidenceError("D1 response not successful")
    parts = payload.get("result")
    if not isinstance(parts, list) or len(parts) != 3:
        raise SchemaEvidenceError("expected three metadata result sets")
    objects, columns, idxcols = (_rows(x) for x in parts)
    names = {str(x.get("name")): x for x in objects}
    if not names and not columns and not idxcols:
        return "MISSING"
    if set(names) != {TABLE, HISTORY_INDEX}:
        return "DRIFT"
    if names[TABLE].get("type") != "table" or names[HISTORY_INDEX].get("type") != "index":
        return "DRIFT"
    table_sql = names[TABLE].get("sql")
    index_sql = names[HISTORY_INDEX].get("sql")
    if not isinstance(table_sql, str) or not isinstance(index_sql, str):
        return "DRIFT"
    if "create table" not in table_sql.lower() or "create index" not in index_sql.lower():
        return "DRIFT"
    if "claw_run_history" not in table_sql.lower() or HISTORY_INDEX not in index_sql:
        return "DRIFT"
    if tuple(x.get("name") for x in idxcols) != ("user_id", "created_at"):
        return "DRIFT"
    ids = tuple(x.get("name") for x in columns)
    if ids[:len(BASE_COLUMNS)] != BASE_COLUMNS:
        return "DRIFT"
    if len({x for x in ids if isinstance(x, str)}) != len(ids):
        return "DRIFT"
    additional = ids[len(BASE_COLUMNS):]
    if additional == ():
        return "BASE_009"
    if additional == ("conversation_id",):
        return "CONVERSATION_014"
    if additional == ("conversation_id", "workspace_id"):
        for c in columns[-2:]:
            if str(c.get("type", "")).upper() != "TEXT" or c.get("notnull") not in (0, False):
                return "DRIFT"
        return "READY_015"
    return "DRIFT"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: b54_claw_history_schema_014_015.py <bounded-metadata.json>", file=sys.stderr)
        return 2
    try:
        with open(args[0], encoding="utf-8") as fp:
            status = classify(json.load(fp))
    except (OSError, json.JSONDecodeError, SchemaEvidenceError) as exc:
        print("B54_CLAW_HISTORY_D1_SCHEMA=UNVERIFIED", file=sys.stderr)
        print(f"SCHEMA_ERROR_CLASS={type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"B54_CLAW_HISTORY_D1_SCHEMA={status}")
    print("D1_SCHEMA_QUERY=READ_ONLY")
    print("ROW_DATA_READ=0")
    print("PRODUCTION_MUTATION=0")
    return 1 if status == "DRIFT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
