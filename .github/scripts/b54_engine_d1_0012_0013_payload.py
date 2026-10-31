"""Build reviewed SQL payloads for the engine 0012/0013 dispatch gate."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2] / "apps/padiem-ai-engine/migrations"
FILES = {
    "0012": "0012_engine_tool_results.sql",
    "0013": "0013_engine_agent_run_checkpoint_step.sql",
}
# abs(INT64_MIN) raises SQLite integer overflow. CASE is lazy, so zero rows
# returns 0; any row aborts the batch before the first schema mutation.
GUARD = "SELECT CASE WHEN EXISTS (SELECT 1 FROM padiem_engine_agent_runs_v1) THEN abs(-9223372036854775808) ELSE 0 END;"

def payload(number):
    if number not in FILES: raise ValueError("unsupported migration")
    sql = (ROOT / FILES[number]).read_text(encoding="utf-8")
    if number == "0013":
        # D1 enables FK enforcement within transactions. Explicit OFF is not
        # supported there; the preflight rejects all inbound references instead.
        for pragma in ("PRAGMA foreign_keys=OFF;", "PRAGMA foreign_keys=ON;"):
            if sql.count(pragma) != 1: raise ValueError("unexpected migration source")
            sql = sql.replace(pragma, "")
        sql = GUARD + "\n" + sql
    return {"sql":sql}

def main():
    number, destination = sys.argv[1:]
    Path(destination).write_text(json.dumps(payload(number)),encoding="utf-8")

if __name__=="__main__":
    main()
