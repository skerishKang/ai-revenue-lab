#!/usr/bin/env python3
"""#4672 B66 D1 044 metadata-only predeploy gate. No row reads or mutations."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE = "b66_ai_turn_attempt"
INDEX = "idx_b66_attempt_owner_state"
SQL = """SELECT name, type, sql FROM sqlite_master WHERE name IN ('b66_ai_turn_attempt','idx_b66_attempt_owner_state') ORDER BY name;
PRAGMA table_info(b66_ai_turn_attempt);
PRAGMA index_list(b66_ai_turn_attempt);
PRAGMA index_xinfo(idx_b66_attempt_owner_state);"""
COLUMNS = [
    ("user_id", "TEXT", 1, 1),
    ("product_scope", "TEXT", 1, 2),
    ("turn_token", "TEXT", 1, 3),
    ("model_id", "TEXT", 1, 0),
    ("request_digest", "TEXT", 1, 0),
    ("state", "TEXT", 1, 0),
    ("conversation_id", "TEXT", 0, 0),
    ("created_at", "TEXT", 1, 0),
]
TABLE_CHECKS = (
    "user_id text not null references users(id) on delete cascade",
    "product_scope text not null check (product_scope = 'b66-quote')",
    "turn_token text not null check (length(turn_token) = 32)",
    "request_digest text not null check (length(request_digest) = 64)",
    "state text not null check (state in ('claimed', 'completed'))",
    "primary key (user_id, product_scope, turn_token)",
    "state = 'claimed' and conversation_id is null",
    "state = 'completed' and conversation_id is not null",
)
INDEX_CHECK = "on b66_ai_turn_attempt (user_id, product_scope, state, created_at)"


class InvalidEvidence(ValueError):
    pass


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip().lower() if isinstance(value, str) else ""


def _results(value: object) -> list[dict]:
    if not isinstance(value, dict) or value.get("success") is not True:
        raise InvalidEvidence("query result failed")
    rows = value.get("results")
    if not isinstance(rows, list) or not all(isinstance(v, dict) for v in rows):
        raise InvalidEvidence("invalid result rows")
    return rows


def classify(payload: object) -> str:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise InvalidEvidence("D1 response failed")
    data = payload.get("result")
    if not isinstance(data, list) or len(data) != 4:
        raise InvalidEvidence("expected 4 metadata statements")
    objects, columns, index_list, xinfo = [_results(value) for value in data]
    if len({o.get("name") for o in objects}) != len(objects) or any(
        o.get("name") not in (TABLE, INDEX) for o in objects
    ):
        return "drift"
    named = {o["name"]: o for o in objects}
    if TABLE not in named:
        return "pre_044" if not objects and not columns and not index_list and not xinfo else "drift"
    table = named[TABLE]
    if table.get("type") != "table" or len(columns) != len(COLUMNS):
        return "drift"
    for cid, (row, (name, kind, notnull, pk)) in enumerate(zip(columns, COLUMNS)):
        if (row.get("cid") != cid or row.get("name") != name
                or str(row.get("type", "")).upper() != kind
                or type(row.get("notnull")) is not int or row["notnull"] != notnull
                or type(row.get("pk")) is not int or row["pk"] != pk
                or row.get("dflt_value") is not None):
            return "drift"
    ddl = _norm(table.get("sql"))
    if not all(fragment in ddl for fragment in TABLE_CHECKS):
        return "drift"
    if INDEX not in named or named[INDEX].get("type") != "index":
        return "drift"
    index_sql = _norm(named[INDEX].get("sql"))
    if INDEX_CHECK not in index_sql or "where " in index_sql:
        return "drift"
    configured = [row for row in index_list if row.get("name") == INDEX]
    if len(configured) != 1 or any(
        configured[0].get(k) != v for k, v in (("unique", 0), ("origin", "c"), ("partial", 0))
    ):
        return "drift"
    if len(xinfo) != 5:
        return "drift"
    for i, name in enumerate(("user_id", "product_scope", "state", "created_at")):
        row = xinfo[i]
        if (row.get("seqno") != i or row.get("name") != name
                or row.get("desc") != 0 or row.get("key") != 1):
            return "drift"
    suffix = xinfo[4]
    if suffix.get("seqno") != 4 or suffix.get("cid") != -1 or suffix.get("key") != 0:
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in ("write-query", "check"):
        print("Usage: write-query|check FILE", file=sys.stderr)
        return 2
    try:
        path = Path(args[1])
        if args[0] == "write-query":
            with path.open("x", encoding="utf-8") as handle:
                json.dump({"sql": SQL}, handle)
            print("B62_D1_044_QUERY=METADATA_ONLY")
            return 0
        disposition = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_D1_SCHEMA_044=" + disposition.upper())
        if disposition != "exact":
            return 1
        print("MIGRATION_044_PREDEPLOY=EXACT")
        print("D1_SCHEMA_QUERY=READ_ONLY")
        print("APPLICATION_ROW_READ=0")
        print("D1_IDENTIFIER_OUTPUT=0")
        print("PRODUCTION_MUTATION=0")
        return 0
    except (InvalidEvidence, ValueError, OSError) as exc:
        print("B62_D1_SCHEMA_044=INVALID_EVIDENCE", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
