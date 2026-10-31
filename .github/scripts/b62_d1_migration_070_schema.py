#!/usr/bin/env python3
"""Exact 067 -> 070 presence rebuild; classify schema and preserve row count."""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "apps/padiem-chat/migrations"
FILES = ("067_mesh_device_presence.sql", "070_mesh_device_presence_source.sql")
QUERY = ("SELECT name,type,sql FROM sqlite_master WHERE name='mesh_device_presence';"
         "SELECT count(*) AS n FROM mesh_device_presence;PRAGMA foreign_key_check;")


def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", value or "")).strip().lower()


def source():
    scripts = [(ROOT / name).read_text(encoding="utf-8") for name in FILES]
    if not all(token in scripts[1] for token in (
        "CREATE TABLE mesh_device_presence_rebuilt_070", "INSERT INTO mesh_device_presence_rebuilt_070",
        "DROP TABLE mesh_device_presence;", "ALTER TABLE mesh_device_presence_rebuilt_070 RENAME TO mesh_device_presence;",
    )):
        raise ValueError("reviewed presence rebuild SQL changed")
    return scripts


def reference_schemas():
    db = sqlite3.connect(":memory:")
    try:
        schemas = {}
        for label, sql in zip(("067", "070"), source()):
            db.executescript(sql)
            schemas[label] = norm(db.execute("SELECT sql FROM sqlite_master WHERE name='mesh_device_presence'").fetchone()[0])
        return schemas
    finally:
        db.close()


def classify(payload):
    records = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
    if not isinstance(records, list) or len(records) != 3 or any(
        not isinstance(r, dict) or r.get("success") is not True or not isinstance(r.get("results"), list)
        for r in records
    ):
        raise ValueError("D1 schema response failed or incomplete")
    schemas, counts, foreign = [r["results"] for r in records]
    if len(schemas) != 1 or schemas[0].get("type") != "table" or len(counts) != 1 or foreign:
        return "DRIFT", -1
    count = counts[0].get("n")
    if type(count) is not int or count < 0:
        return "DRIFT", -1
    for label, expected in reference_schemas().items():
        if norm(schemas[0].get("sql")) == expected:
            return label, count
    return "DRIFT", count


def write(path, sql):
    path.write_text(json.dumps({"sql": sql}), encoding="utf-8")


def main():
    action, filename = sys.argv[1:3]
    path = Path(filename)
    if action == "query":
        reference_schemas()
        write(path, QUERY)
    elif action == "classify":
        label, count = classify(json.loads(path.read_text()))
        print("B62_MESH_PRESENCE_SCHEMA=" + label)
        print("B62_MESH_PRESENCE_ROW_COUNT=" + str(count))
        if label == "DRIFT":
            raise ValueError("presence schema drift")
    elif action == "apply":
        if len(sys.argv) != 4 or sys.argv[3] != "067":
            raise ValueError("070 rebuild requires exact 067 schema")
        reference_schemas()
        write(path, source()[1])
    elif action == "check-apply":
        payload = json.loads(path.read_text())
        blocks = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(blocks, list) or not blocks or any(
                not isinstance(b, dict) or b.get("success") is not True for b in blocks):
            raise ValueError("D1 presence rebuild failed")
        print("B62_MESH_PRESENCE_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print("B62_MESH_PRESENCE_GATE=FAIL:" + str(exc), file=sys.stderr)
        raise SystemExit(1)
