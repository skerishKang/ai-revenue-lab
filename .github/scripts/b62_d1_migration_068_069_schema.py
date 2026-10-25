#!/usr/bin/env python3
"""Fail-closed schema release for existing project_files D1 003 -> 068 -> 069."""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "apps/padiem-chat/migrations"
FILES = ("003_project_files.sql", "068_project_files_extracted_media.sql", "069_project_files_image_media.sql")
INDEXES = {"idx_project_files_owner_project", "idx_project_files_project_updated"}
QUERY = ("SELECT type,name,sql FROM sqlite_master WHERE name IN "
         "('project_files','idx_project_files_owner_project','idx_project_files_project_updated');"
         "SELECT count(*) AS n FROM project_files;"
         "PRAGMA foreign_key_check;")

def source():
    scripts = [(ROOT / name).read_text(encoding="utf-8") for name in FILES]
    for text in scripts[1:]:
        if not all(x in text.upper() for x in ("CREATE TABLE PROJECT_FILES_REBUILT_", "INSERT INTO PROJECT_FILES_REBUILT_", "DROP TABLE PROJECT_FILES", "ALTER TABLE PROJECT_FILES_REBUILT_")):
            raise ValueError("migration rebuild SQL contract changed")
    return scripts

def norm(value):
    return re.sub(r"\\s+", " ", re.sub(r"--[^\\n]*", "", value or "")).strip().lower()

def reference_schemas():
    scripts = source()
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
    expected = {}
    for idx, script in enumerate(scripts):
        db.executescript(script)
        label = ("003", "068", "069")[idx]
        expected[label] = {row[0]: norm(row[1]) for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE name IN "
            "('project_files','idx_project_files_owner_project','idx_project_files_project_updated')")}
    db.close()
    for label in expected:
        if set(expected[label]) != INDEXES | {"project_files"}:
            raise ValueError("migration "+label+" loses a project_files index")
    return expected

def rows(payload, size):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 API response failed")
    blocks = payload.get("result")
    if not isinstance(blocks, list) or len(blocks) != size:
        raise ValueError("D1 response incomplete")
    for block in blocks:
        if not isinstance(block, dict) or block.get("success") is not True or not isinstance(block.get("results"), list):
            raise ValueError("D1 SQL statement failed")
    return [x["results"] for x in blocks]

def classify(payload):
    schemas, counts, invalid = rows(payload, 3)
    if invalid or len(counts) != 1 or not isinstance(counts[0].get("n"), int):
        return "DRIFT", -1
    found = {row.get("name"): norm(row.get("sql")) for row in schemas}
    for label, expected in reference_schemas().items():
        if found == expected:
            return label, counts[0]["n"]
    return "DRIFT", counts[0]["n"]

def write(path, sql):
    path.write_text(json.dumps({"sql": sql}), encoding="utf-8")

def main():
    mode, filename = sys.argv[1:3]
    path = Path(filename)
    if mode == "query":
        reference_schemas()
        write(path, QUERY)
    elif mode == "classify":
        label, count = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_PROJECT_FILES_SCHEMA="+label)
        print("B62_PROJECT_FILES_ROW_COUNT="+str(count))
        if label == "DRIFT":
            raise ValueError("production schema drift or foreign key violation")
    elif mode == "apply":
        label = sys.argv[3] if len(sys.argv) > 3 else None
        if label not in ("003", "068"):
            raise ValueError("apply allowed only from 003 or 068")
        scripts = source()
        reference_schemas()
        sql = "".join(scripts[1:] if label == "003" else scripts[2:])
        write(path, sql)
    elif mode == "check-apply":
        rows(json.loads(path.read_text(encoding="utf-8")), 1)
        print("B62_PROJECT_FILES_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown operation")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, IndexError) as exc:
        print("B62_PROJECT_FILES_GATE=FAIL:"+str(exc), file=sys.stderr)
        sys.exit(1)
