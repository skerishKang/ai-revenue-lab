"""Owner-authorized production D1 026 exact-schema gate; never reads user rows."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/026_claw_conversation_artifact_index.sql"
PINNED_SHA256 = "c416aee25bacd1748140a737d5e24e261f41cee09543e65a6d0de1a8fd7cece3"
TABLE = "claw_conversation_artifact_index"
INDEX = "idx_claw_conversation_artifact_owner"
QUERY = f"""SELECT type,name,sql FROM sqlite_master WHERE name IN ('{TABLE}','{INDEX}') ORDER BY name;
PRAGMA table_info({TABLE});
PRAGMA foreign_key_list({TABLE});
PRAGMA index_xinfo({INDEX});
PRAGMA table_info(claw_run_history);"""


def assert_approved_source() -> str:
    contents = MIGRATION.read_bytes()
    if hashlib.sha256(contents).hexdigest() != PINNED_SHA256:
        raise ValueError("026 source SHA differs from the owner-approved merged migration")
    text = contents.decode("utf-8")
    # Only two CREATE objects; neither a table ALTER nor a user-row mutation.
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    statements = [stmt.strip() for stmt in code.split(";") if stmt.strip()]
    if (len(statements) != 2
        or not re.fullmatch(r"CREATE TABLE IF NOT EXISTS claw_conversation_artifact_index \([\s\S]+\)", statements[0])
        or not re.fullmatch(r"CREATE INDEX IF NOT EXISTS idx_claw_conversation_artifact_owner[\s\S]+", statements[1])
        or any(re.search(r"\b(ALTER|DROP|UPDATE|INSERT|REPLACE|TRUNCATE|ATTACH|DETACH)\b", x, re.I) for x in statements)):
        raise ValueError("approved 026 cannot contain any non-create mutation")
    return code.strip()


def normalized(sql: str) -> str:
    sql = re.sub(r"(?i)\bIF NOT EXISTS\b\s*", "", sql)
    return re.sub(r"\s+", "", sql).casefold()


def expected_metadata():
    con = sqlite3.connect(":memory:")
    try:
        con.execute("PRAGMA foreign_keys=ON")
        for name in ("001_auth_history.sql", "009_claw_run_history.sql",
                     "014_claw_run_history_conversation.sql",
                     "015_claw_run_history_workspace.sql"):
            con.executescript((MIGRATION.parent / name).read_text(encoding="utf8"))
        con.executescript(assert_approved_source())
        master = {name: (kind, normalized(sql)) for kind, name, sql in con.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name IN (?,?)", (TABLE, INDEX))}
        cols = [(row[1], row[2].upper(), row[3], row[5]) for row in con.execute(
            f"PRAGMA table_info({TABLE})")]
        fks = [(row[2], row[3], row[4], row[6]) for row in con.execute(
            f"PRAGMA foreign_key_list({TABLE})")]
        idx = [(row[0], row[2], row[3], row[5]) for row in con.execute(
            f"PRAGMA index_xinfo({INDEX})")]
        return master, cols, fks, idx
    finally:
        con.close()


def _results(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("success") is not True or not isinstance(doc.get("result"), list):
        raise ValueError("D1 API unsuccessful")
    if len(doc["result"]) != 5:
        raise ValueError("unexpected D1 metadata query count")
    outputs = []
    for part in doc["result"]:
        if part.get("success") is not True or not isinstance(part.get("results"), list):
            raise ValueError("D1 statement result unsuccessful")
        outputs.append(part["results"])
    return outputs


def classify(path: str) -> str:
    master_rows, col_rows, fk_rows, idx_rows, history_rows = _results(path)
    history = {r.get("name") for r in history_rows}
    if not {"conversation_id", "workspace_id", "run_id", "user_id"}.issubset(history):
        raise ValueError("D1 base 014/015 history columns not ready")
    if not master_rows and not col_rows and not fk_rows and not idx_rows:
        return "MISSING"
    expected_master, expected_cols, expected_fks, expected_idx = expected_metadata()
    if len(master_rows) != 2:
        return "DRIFT"
    actual_master = {}
    for item in master_rows:
        name, kind, sql = item.get("name"), item.get("type"), item.get("sql")
        if not isinstance(sql, str) or name in actual_master or name not in expected_master:
            return "DRIFT"
        actual_master[name] = (kind, normalized(sql))
    cols = [(r.get("name"), str(r.get("type", "")).upper(),
             r.get("notnull"), r.get("pk")) for r in col_rows]
    fks = [(r.get("table"), r.get("from"), r.get("to"), r.get("on_delete")) for r in fk_rows]
    idx = [(r.get("seqno"), r.get("name"), r.get("desc"), r.get("key")) for r in idx_rows]
    return "EXACT" if (
        actual_master == expected_master
        and cols == expected_cols and sorted(fks) == sorted(expected_fks)
        and idx == expected_idx
    ) else "DRIFT"


def offline() -> None:
    expected_metadata()
    con = sqlite3.connect(":memory:")
    try:
        con.execute("PRAGMA foreign_keys=ON")
        for name in ("001_auth_history.sql", "009_claw_run_history.sql",
                     "014_claw_run_history_conversation.sql",
                     "015_claw_run_history_workspace.sql"):
            con.executescript((MIGRATION.parent / name).read_text(encoding="utf8"))
        missing = _pack(con)
        assert classify(str(missing)) == "MISSING"
        con.executescript(assert_approved_source())
        ready = _pack(con)
        assert classify(str(ready)) == "EXACT"
        con.execute(f"DROP INDEX {INDEX}")
        drift = _pack(con)
        assert classify(str(drift)) == "DRIFT"
        print("D1_026_APPROVED_SOURCE_SHA=PASS")
        print("D1_026_SCHEMA_STATES=MISSING_EXACT_DRIFT_PASS")
        print("PRODUCTION_MUTATION=0")
    finally:
        con.close()


def _pack(con):
    import tempfile
    # Used only in isolated source contract tests.
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False)
    con.row_factory = sqlite3.Row
    try:
        out = []
        for stmt in QUERY.split(";"):
            if stmt.strip():
                rows = [dict(x) for x in con.execute(stmt)]
                out.append({"success": True, "results": rows})
        json.dump({"success": True, "result": out}, tmp)
        tmp.close()
        return Path(tmp.name)
    finally:
        if not tmp.closed:
            tmp.close()


def main(argv):
    if len(argv) == 2 and argv[1] == "offline":
        offline()
    elif len(argv) == 3 and argv[1] == "query":
        assert_approved_source()
        Path(argv[2]).write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif len(argv) == 3 and argv[1] == "payload":
        Path(argv[2]).write_text(json.dumps({"sql": assert_approved_source()}), encoding="utf-8")
    elif len(argv) == 3 and argv[1] == "inspect":
        state = classify(argv[2])
        print(f"CLAW_D1_026_SCHEMA={state}")
        print("D1_USER_ROW_DATA_READ=0")
        if state == "DRIFT":
            raise ValueError("026 schema drift, refusing to apply")
    else:
        raise SystemExit("usage: [offline | query OUT | payload OUT | inspect RESPONSE]")


if __name__ == "__main__":
    main(sys.argv)
