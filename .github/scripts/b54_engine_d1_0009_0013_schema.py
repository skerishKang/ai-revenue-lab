#!/usr/bin/env python3
"""Read-only classification of Engine D1 migrations 0009–0013.

The input is Cloudflare D1 API /query JSON, collected separately with SELECT
against sqlite_master. No row contents are requested. DRIFT blocks mutation.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2] / "apps/padiem-ai-engine/migrations"
TABLES = {
    "0009": "padiem_web_xlsx_tool_continuations",
    "0010": "padiem_web_quote_write_tool_continuations",
    "0011": "padiem_engine_agent_runs_v1",
    "0012": "padiem_engine_tool_results_v1",
}
TEMP = "padiem_engine_agent_runs_v1_widened"
FILES = {
    "0009": "0009_web_xlsx_tool_continuations.sql",
    "0010": "0010_web_quote_write_tool_continuations.sql",
    "0011": "0011_engine_agent_durable_runs.sql",
    "0012": "0012_engine_tool_results.sql",
    "0013": "0013_engine_agent_run_checkpoint_step.sql",
}
def norm(sql):
    return re.sub(r"\s+", " ", (sql or "").strip()).lower()

def reference():
    db = sqlite3.connect(":memory:")
    versions = {}
    for key, name in FILES.items():
        db.executescript((ROOT / name).read_text(encoding="utf-8"))
        table = TABLES.get(key, TABLES["0011"])
        versions[key] = snapshot(db, table)
    db.close()
    return versions

def snapshot(db, table):
    rows = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name=? AND type IN ('table','index')", (table,))
    return sorted((r[0], r[1], r[2], norm(r[3])) for r in rows)

def schema_sql():
    names = list(TABLES.values()) + [TEMP]
    quoted = ",".join("'" + x + "'" for x in names)
    return "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('table','index') AND tbl_name IN ("+quoted+") ORDER BY type,name"

def api_rows(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 query failed")
    blocks = payload.get("result")
    if not isinstance(blocks, list) or len(blocks) != 1:
        raise ValueError("D1 response shape invalid")
    block = blocks[0]
    if not isinstance(block, dict) or block.get("success") is not True or not isinstance(block.get("results"), list):
        raise ValueError("D1 result failed")
    return block["results"]

def classify(payload):
    rows = api_rows(payload)
    refs = reference()
    grouped = {name: [] for name in list(TABLES.values()) + [TEMP]}
    for row in rows:
        if not isinstance(row, dict) or row.get("tbl_name") not in grouped:
            raise ValueError("unexpected schema row")
        t, name, owner, sql = (row.get("type"), row.get("name"), row.get("tbl_name"), row.get("sql"))
        if t not in ("table","index") or not isinstance(name,str) or not (sql is None or isinstance(sql,str)):
            raise ValueError("invalid schema object")
        grouped[owner].append((t,name,owner,norm(sql)))
    states = {}
    for number, table in TABLES.items():
        actual = sorted(grouped[table])
        if not actual: states[number] = "MISSING"
        elif number == "0011" and actual in (refs["0011"],refs["0013"]): states[number] = "EXACT"
        else: states[number] = "EXACT" if actual == refs[number] else "DRIFT"
    actual = sorted(grouped[TABLES["0011"]])
    if grouped[TEMP]: states["0013"] = "DRIFT"
    elif not actual or actual == refs["0011"]: states["0013"] = "MISSING"
    elif actual == refs["0013"]: states["0013"] = "EXACT"
    else: states["0013"] = "DRIFT"
    return states, grouped

def count_sql(states, grouped=None):
    # Fixed identifiers only; count even DRIFT when the table itself exists.
    present = [v for k,v in TABLES.items() if states[k] == "EXACT" or (grouped is not None and any(r[0] == "table" and r[1] == v for r in grouped[v]))]
    if not present: return "SELECT 'none' AS name, 0 AS n WHERE 0"
    return " UNION ALL ".join("SELECT '"+name+"' AS name, count(*) AS n FROM "+name for name in present)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode", choices=("query","classify","counts-query","counts"))
    p.add_argument("path", type=Path)
    a=p.parse_args()
    if a.mode == "query":
        reference()
        a.path.write_text(json.dumps({"sql":schema_sql()}),encoding="utf-8")
    elif a.mode == "counts":
        data = api_rows(json.loads(a.path.read_text(encoding="utf-8")))
        allowed = set(TABLES.values())
        if any(not isinstance(r, dict) or r.get("name") not in allowed or type(r.get("n")) is not int or r["n"] < 0 for r in data):
            raise ValueError("invalid count results")
        print(json.dumps({"row_counts": {r["name"]: r["n"] for r in data}}, indent=2))
    else:
        states, grouped = classify(json.loads(a.path.read_text(encoding="utf-8")))
        if a.mode == "counts-query":
            print(json.dumps({"sql":count_sql(states, grouped)}))
        else:
            print(json.dumps({"migrations":states,
                "indexes":sorted(x[1] for x in grouped[TABLES["0011"]] if x[0]=="index"),
                "rebuild_table":TABLES["0011"]},indent=2))
            if "DRIFT" in states.values(): return 1
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except (ValueError, OSError, sqlite3.Error) as e:
        print("ENGINE_D1_CLASSIFY_FAIL="+str(e),file=sys.stderr)
        sys.exit(1)
