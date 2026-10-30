"""Fail-closed evidence checks for the engine D1 0012/0013 gate.

This module performs no network access or database mutations.
"""
import json
import sys

RUNS = "padiem_engine_agent_runs_v1"
XLSX = "padiem_web_xlsx_tool_continuations"
QUOTE = "padiem_web_quote_write_tool_continuations"
RESULTS = "padiem_engine_tool_results_v1"
EXPECTED_INDEXES = {
    "idx_engine_agent_runs_expiry", "idx_engine_agent_runs_owner",
    "sqlite_autoindex_padiem_engine_agent_runs_v1_1",
}

def counts(payload, expected):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("count query failed")
    blocks = payload.get("result")
    if not isinstance(blocks, list) or len(blocks) != 1 or not isinstance(blocks[0], dict) or blocks[0].get("success") is not True:
        raise ValueError("invalid count response")
    rows = blocks[0].get("results")
    if not isinstance(rows, list):
        raise ValueError("invalid count rows")
    values = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("name") not in expected or row["name"] in values or type(row.get("n")) is not int or row["n"] < 0:
            raise ValueError("invalid count entry")
        values[row["name"]] = row["n"]
    if set(values) != expected:
        raise ValueError("incomplete counts")
    return values

def before(schema, count_payload, fk):
    if not isinstance(schema, dict) or schema.get("migrations") != {
        "0009":"EXACT", "0010":"EXACT", "0011":"EXACT",
        "0012":"MISSING", "0013":"MISSING",
    }:
        raise ValueError("unexpected schema state")
    if schema.get("rebuild_table") != RUNS or set(schema.get("indexes", [])) != EXPECTED_INDEXES:
        raise ValueError("unexpected run indexes")
    if not isinstance(fk, dict) or fk.get("inbound_foreign_keys") != [] or type(fk.get("tables_inspected")) is not int or fk["tables_inspected"] < 1:
        raise ValueError("FK inventory unavailable or references exist")
    data=counts(count_payload,{XLSX,QUOTE,RUNS})
    if data[RUNS] != 0:
        raise ValueError("run table is not empty")
    return data

def after(schema, count_payload, baseline):
    if not isinstance(schema, dict) or schema.get("migrations") != {str(i).zfill(4):"EXACT" for i in range(9,14)}:
        raise ValueError("post schema mismatch")
    if schema.get("rebuild_table") != RUNS or set(schema.get("indexes", [])) != EXPECTED_INDEXES:
        raise ValueError("post index mismatch")
    data=counts(count_payload,{XLSX,QUOTE,RUNS,RESULTS})
    if not isinstance(baseline,dict) or set(baseline)!={XLSX,QUOTE,RUNS}:
        raise ValueError("invalid baseline")
    if any(data[k] != baseline[k] for k in baseline):
        raise ValueError("row count changed")
    return data

def main(args):
    mode, schema_path, counts_path, evidence_path = args
    def load(path):
        with open(path, encoding="utf-8") as f: return json.load(f)
    schema, count_payload, evidence = map(load, (schema_path,counts_path,evidence_path))
    result = before(schema,count_payload,evidence) if mode=="before" else after(schema,count_payload,evidence) if mode=="after" else (_ for _ in ()).throw(ValueError("invalid mode"))
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    try: main(sys.argv[1:])
    except (ValueError, OSError, TypeError) as e:
        print("ENGINE_APPLY_EVIDENCE=FAIL: "+str(e),file=sys.stderr)
        sys.exit(1)
