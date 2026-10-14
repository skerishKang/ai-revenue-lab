#!/usr/bin/env python3
"""Read-only, fail-closed B62 Production D1 migrations 041/042 schema gate.

Never touches application rows, calls Cloudflare, performs SQL mutation,
or prints database identifiers, values, or customer information.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TABLE_041 = "b66_ai_conversation"
TABLE_CHAT = "conversations"
INDEX_042 = "idx_conversations_user_product_updated"

# Exactly five independent metadata-only queries; no row-data SELECT.
SCHEMA_SQL = """SELECT name, type, sql FROM sqlite_master WHERE name IN ('b66_ai_conversation','conversations','idx_conversations_user_product_updated') ORDER BY name;
PRAGMA table_info(b66_ai_conversation);
PRAGMA table_info(conversations);
PRAGMA index_xinfo(idx_conversations_user_product_updated);
PRAGMA index_list(conversations);"""

B66_COLUMNS = (
    ("user_id", "TEXT", 1, None, 1),
    ("workspace_id", "TEXT", 1, None, 2),
    ("state_json", "TEXT", 1, None, 0),
    ("revision", "INTEGER", 1, "0", 0),
    ("updated_at", "TEXT", 1, None, 0),
)
CHAT_PRE_042 = (
    ("id", "TEXT", 0, None, 1),
    ("user_id", "TEXT", 1, None, 0),
    ("title", "TEXT", 1, None, 0),
    ("created_at", "TEXT", 1, None, 0),
    ("updated_at", "TEXT", 1, None, 0),
    ("project_id", "TEXT", 0, None, 0),
)
CHAT_042 = CHAT_PRE_042 + (("product_scope", "TEXT", 1, "'b62-chat'", 0),)
B66_SQL = (
    "user_id text not null references users(id) on delete cascade",
    "workspace_id text not null",
    "state_json text not null",
    "revision integer not null default 0",
    "updated_at text not null",
    "primary key (user_id, workspace_id)",
)
CHAT_SQL = (
    "id text primary key",
    "user_id text not null references users(id) on delete cascade",
    "title text not null check (length(title) between 1 and 80)",
    "project_id text references projects(id) on delete set null",
)
INDEX_SQL = "on conversations(user_id, product_scope, updated_at desc)"


class InvalidEvidence(ValueError):
    pass


def _rows(item: object) -> list[dict]:
    if not isinstance(item, dict) or item.get("success") is not True:
        raise InvalidEvidence("D1 schema result unsuccessful")
    rows = item.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise InvalidEvidence("invalid schema metadata rows")
    return rows


def _normal(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip().lower() if isinstance(value, str) else ""


def _columns(rows: list[dict], expected: tuple) -> bool:
    if len(rows) != len(expected):
        return False
    for idx, (row, (name, declared, notnull, default, pk)) in enumerate(zip(rows, expected)):
        if (row.get("cid") != idx or row.get("name") != name
                or str(row.get("type", "")).upper() != declared
                or type(row.get("notnull")) is not int or row["notnull"] != notnull
                or row.get("dflt_value") != default
                or type(row.get("pk")) is not int or row["pk"] != pk):
            return False
    return True


def _objects(rows: list[dict]) -> dict[str, dict] | None:
    if len(rows) != len({v.get("name") for v in rows}):
        return None
    allowed = {TABLE_041, TABLE_CHAT, INDEX_042}
    if any(row.get("name") not in allowed for row in rows):
        return None
    return {row["name"]: row for row in rows}


def classify(payload: object) -> str:
    """exact/pre_041/pre_042/missing/drift; only exact may release B62 code."""
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise InvalidEvidence("Cloudflare D1 query unsuccessful")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != 5:
        raise InvalidEvidence("expected five independent schema statements")
    objects, b66, chat, index_xinfo, index_list = [_rows(x) for x in results]
    matched = _objects(objects)
    if matched is None:
        return "drift"
    if TABLE_CHAT not in matched:
        return "missing"
    if matched[TABLE_CHAT].get("type") != "table":
        return "drift"
    chat_sql = _normal(matched[TABLE_CHAT].get("sql"))
    if not all(f in chat_sql for f in CHAT_SQL):
        return "drift"
    # A pre-042 conversation table is accepted only as a *non-deployable*
    # rollout state. The migration cannot repair altered/renamed columns.
    pre = _columns(chat, CHAT_PRE_042)
    post = _columns(chat, CHAT_042)
    if not (pre or post):
        return "drift"
    if not any(row.get("name") == "idx_conversations_user_updated"
               for row in index_list):
        return "drift"
    if TABLE_041 not in matched:
        if b66 or post or INDEX_042 in matched or index_xinfo:
            return "drift"
        return "pre_041"
    if matched[TABLE_041].get("type") != "table":
        return "drift"
    b66_sql = _normal(matched[TABLE_041].get("sql"))
    if not _columns(b66, B66_COLUMNS) or not all(f in b66_sql for f in B66_SQL):
        return "drift"
    if pre:
        if INDEX_042 in matched or index_xinfo:
            return "drift"
        return "pre_042"
    if INDEX_042 not in matched or matched[INDEX_042].get("type") != "index":
        return "drift"
    index_sql = _normal(matched[INDEX_042].get("sql"))
    if INDEX_SQL not in index_sql or "where " in index_sql:
        return "drift"
    qualified = [r for r in index_list if r.get("name") == INDEX_042]
    if len(qualified) != 1 or qualified[0].get("unique") != 0 or qualified[0].get("origin") != "c" or qualified[0].get("partial") != 0:
        return "drift"
    if len(index_xinfo) != 4:
        return "drift"
    for i, (name, desc) in enumerate((("user_id", 0), ("product_scope", 0), ("updated_at", 1))):
        row = index_xinfo[i]
        if row.get("seqno") != i or row.get("name") != name or row.get("desc") != desc or row.get("key") != 1:
            return "drift"
    # Fourth xinfo row is the automatically appended ROWID suffix, not key.
    suffix = index_xinfo[3]
    if suffix.get("seqno") != 3 or suffix.get("cid") != -1 or suffix.get("key") != 0:
        return "drift"
    if "product_scope text not null default 'b62-chat'" not in chat_sql:
        return "drift"
    return "exact"


def main(args: list[str] | None = None) -> int:
    argv = sys.argv[1:] if args is None else args
    if len(argv) != 2 or argv[0] not in {"write-query", "check"}:
        print("Usage: <write-query|check> <file>", file=sys.stderr)
        return 2
    mode, filename = argv
    try:
        path = Path(filename)
        if mode == "write-query":
            if path.exists():
                raise InvalidEvidence("query file already exists")
            path.write_text(json.dumps({"sql": SCHEMA_SQL}) + "\n", encoding="utf-8")
            print("B62_D1_SCHEMA_041_042_QUERY=METADATA_ONLY")
        else:
            state = classify(json.loads(path.read_text(encoding="utf-8")))
            print(f"B62_D1_SCHEMA_041_042={state.upper()}")
            if state != "exact":
                return 1
            print("MIGRATION_041_042_PREDEPLOY=EXACT")
            print("D1_SCHEMA_QUERY=READ_ONLY")
            print("APPLICATION_ROW_READ=0")
            print("D1_IDENTIFIER_OUTPUT=0")
            print("PRODUCTION_MUTATION=0")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # No live payload data or secrets in error output.
        print("B62_D1_SCHEMA_041_042=INVALID_EVIDENCE", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
