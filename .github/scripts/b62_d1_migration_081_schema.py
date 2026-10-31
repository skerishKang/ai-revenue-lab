#!/usr/bin/env python3
"""Exact 029 -> 081 XLSX selection gate; metadata/counts only on live D1."""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "apps/padiem-chat/migrations"
UPLOAD_MAX_BYTES = 1024 * 1024 * 1024
TABLES = ("claw_web_xlsx_selections", "claw_web_xlsx_quote_edit_receipts")
FILES = ("029_claw_web_xlsx_selection.sql", "032_claw_web_xlsx_quote_edit_receipts.sql",
         "081_claw_web_xlsx_selection_limit.sql")
QUERY = (
    "SELECT name,type,sql FROM sqlite_master WHERE name IN "
    "('claw_web_xlsx_selections','claw_web_xlsx_quote_edit_receipts');"
    "SELECT count(*) AS n FROM claw_web_xlsx_selections;"
    "SELECT count(*) AS n FROM claw_web_xlsx_quote_edit_receipts;PRAGMA foreign_key_check;"
)


def norm(value):
    # SQL keywords are case-insensitive; CHECK string literals are not.
    # Keep literal case/spacing so a changed status constraint is DRIFT.
    tokens = re.split(r"('(?:''|[^'])*')", value or "")
    return "".join(
        token if index % 2 else re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", token)).lower()
        for index, token in enumerate(tokens)
    ).strip()


def source():
    scripts = [(ROOT / name).read_text(encoding="utf-8") for name in FILES]
    if not all(token in scripts[2] for token in (
        f"size_bytes <= {UPLOAD_MAX_BYTES}",
        "CREATE TABLE claw_web_xlsx_receipts_limits_backup AS",
        "DELETE FROM claw_web_xlsx_quote_edit_receipts;",
        "INSERT INTO claw_web_xlsx_selections_limits_next",
        "DROP TABLE claw_web_xlsx_selections;",
        "ALTER TABLE claw_web_xlsx_selections_limits_next RENAME TO claw_web_xlsx_selections;",
        "INSERT INTO claw_web_xlsx_quote_edit_receipts",
        "DROP TABLE claw_web_xlsx_receipts_limits_backup;",
    )):
        raise ValueError("reviewed XLSX rebuild SQL changed")
    return scripts


def schemas(db):
    return {name: norm(db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0])
            for name in TABLES}


def reference_schemas():
    db = sqlite3.connect(":memory:")
    try:
        old, receipt, new = source()
        db.executescript(old + receipt)
        expected = {"029": schemas(db)}
        db.executescript(new)
        expected["081"] = schemas(db)
        return expected
    finally:
        db.close()


def classify(payload):
    records = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
    if not isinstance(records, list) or len(records) != 4 or any(
        not isinstance(r, dict) or r.get("success") is not True or not isinstance(r.get("results"), list)
        for r in records
    ):
        raise ValueError("D1 schema response failed or incomplete")
    rows, selections, receipts, foreign = [r["results"] for r in records]
    counts = {}
    if len(rows) != 2 or foreign or any(
        not isinstance(r, dict) or r.get("type") != "table" or r.get("name") not in TABLES
        or not isinstance(r.get("sql"), str) or not r["sql"] for r in rows
    ):
        return "DRIFT", counts
    actual = {r["name"]: norm(r["sql"]) for r in rows}
    if len(actual) != 2:
        return "DRIFT", counts
    for name, values in zip(TABLES, (selections, receipts)):
        if len(values) != 1 or not isinstance(values[0], dict):
            return "DRIFT", counts
        count = values[0].get("n")
        if type(count) is not int or count < 0:
            return "DRIFT", counts
        counts[name] = count
    for label, expected in reference_schemas().items():
        if actual == expected:
            return label, counts
    return "DRIFT", counts


def verify_preservation(before, after):
    old_label, old_counts = classify(before)
    new_label, new_counts = classify(after)
    if old_label not in ("029", "081") or new_label != "081" or old_counts != new_counts:
        raise ValueError("XLSX schema, row preservation, or foreign keys failed")


def check_apply(payload):
    blocks = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
    if not isinstance(blocks, list) or not blocks or any(
        not isinstance(b, dict) or b.get("success") is not True for b in blocks
    ):
        raise ValueError("D1 XLSX rebuild failed")


def main():
    action, filename = sys.argv[1:3]
    path = Path(filename)
    if action == "query":
        reference_schemas()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        label, counts = classify(json.loads(path.read_text()))
        print("B62_WEB_XLSX_SCHEMA=" + label)
        if label == "DRIFT":
            raise ValueError("XLSX schema drift")
        print("B62_WEB_XLSX_SELECTION_ROW_COUNT=" + str(counts[TABLES[0]]))
        print("B62_WEB_XLSX_RECEIPT_ROW_COUNT=" + str(counts[TABLES[1]]))
        print("B62_WEB_XLSX_FOREIGN_KEYS=PASS")
    elif action == "apply":
        if len(sys.argv) != 4 or sys.argv[3] != "029":
            raise ValueError("081 rebuild requires exact 029 schema")
        reference_schemas()
        path.write_text(json.dumps({"sql": source()[2]}), encoding="utf-8")
    elif action == "check-apply":
        check_apply(json.loads(path.read_text()))
        print("B62_WEB_XLSX_APPLY_RESPONSE=PASS")
    elif action == "verify-preservation":
        verify_preservation(json.loads(path.read_text()), json.loads(Path(sys.argv[3]).read_text()))
        print("B62_WEB_XLSX_SELECTION_ROWS_PRESERVED=PASS")
        print("B62_WEB_XLSX_RECEIPT_ROWS_PRESERVED=PASS")
        print("B62_WEB_XLSX_FOREIGN_KEYS=PASS")
    else:
        raise ValueError("unknown operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error):
        print("B62_WEB_XLSX_GATE=FAIL", file=sys.stderr)
        raise SystemExit(1)
