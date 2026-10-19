"""Negative control: the deploy gate's hard-refusal grep against real migration fixtures."""
import importlib.util, re, sqlite3, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/scripts/b62_d1_migration_040_schema.py"
M031 = ROOT / "apps/padiem-chat/migrations/031_claw_web_xlsx_p01_decision_receipts.sql"
M040 = ROOT / "apps/padiem-chat/migrations/040_claw_web_xlsx_p01_decision_release.sql"
TABLE = "claw_web_xlsx_p01_decision_receipts"

spec = importlib.util.spec_from_file_location("b62_d1_040", HELPER)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def live(apply_040):
    conn = sqlite3.connect(":memory:")
    conn.executescript(M031.read_text(encoding="utf-8"))
    if apply_040:
        conn.executescript(M040.read_text(encoding="utf-8"))
    objects = [{"name": r[0], "type": r[1], "sql": r[2]}
               for r in conn.execute("SELECT name, type, sql FROM sqlite_master WHERE name = ?", (TABLE,))]
    columns = [{"name": r[1], "type": r[2], "notnull": r[3], "dflt_value": r[4], "pk": r[5]}
               for r in conn.execute(f"PRAGMA table_info({TABLE})")]
    conn.close()
    return {"success": True, "result": [{"success": True, "results": objects},
                                        {"success": True, "results": columns}]}

def gate_verdict(payload):
    """Mirror the deploy-gate step: classifier then the exact grep with set -e semantics."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json_tmp = fh.name
        import json; json.dump(payload, fh)
    proc = subprocess.run([sys.executable, str(HELPER), json_tmp],
                          capture_output=True, text=True)
    stdout_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    stderr_lines = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip()]
    grep = subprocess.run(["grep", "-q", r"^B62_D1_MIGRATION_040_SCHEMA=EXACT$"],
                          input="\n".join(stdout_lines) + "\n",
                          capture_output=True, text=True)
    Path(json_tmp).unlink(missing_ok=True)
    key = "<none>"
    for ln in stdout_lines + stderr_lines:
        if ln.startswith("B62_D1_MIGRATION_040_SCHEMA="):
            key = ln.split("=", 1)[1].strip()
            break
    shown = " ; ".join(stdout_lines + stderr_lines)
    return key, shown, grep.returncode, proc.returncode

cases = []
p = live(True);  cases.append(("EXACT_040_APPLIED", p, "EXACT", 0))
p = live(False); cases.append(("PRE_040_SCHEMA", p, "PRE_040", 1))
p = live(True)
for row in p["result"][1]["results"]:
    if row["name"] == "released_at":
        row["notnull"] = 1
cases.append(("DRIFT_RELEASED_AT_NOTNULL", p, "DRIFT", 1))
p = live(True); p["result"][1]["results"].append(
    {"name": "extra_col", "type": "TEXT", "notnull": 0, "dflt_value": None, "pk": 0})
cases.append(("DRIFT_EXTRA_COLUMN", p, "DRIFT", 1))
p = live(True); p["success"] = False
cases.append(("FAIL_API_ERROR", p, "FAIL", 1))

ok = True
for name, payload, want_key, want_rc in cases:
    key, shown, grep_rc, helper_rc = gate_verdict(payload)
    passed = (key == want_key and grep_rc == want_rc and helper_rc in (0, 1))
    ok = ok and passed
    print(f"{'PASS' if passed else 'FAIL'} {name}: classifier={key!r} grep_rc={grep_rc} "
          f"helper_rc={helper_rc} (want={want_key}/{want_rc}) :: {shown!r}")
print("NEGATIVE_CONTROL_RESULT=" + ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
