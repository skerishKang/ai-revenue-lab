#!/usr/bin/env python3
"""Real SQLite source and payload checks for #5773 protected release."""
import importlib.util
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", BASE / "scripts/b62_d1_migration_068_069_schema.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

def payload(db):
    def block(query):
        return {"success": True, "results": [dict(zip([x[0] for x in cur.description], row)) for row in cur.fetchall()] if (cur := db.execute(query)).description else []}
    return {"success": True, "result": [
        block("SELECT type,name,sql FROM sqlite_master WHERE name IN ('project_files','idx_project_files_owner_project','idx_project_files_project_updated')"),
        block("SELECT count(*) AS n FROM project_files"),
        block("PRAGMA foreign_key_check"),
    ]}

def main():
    expected = release.reference_schemas()
    assert set(expected) == {"003", "068", "069"}
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE projects(id TEXT PRIMARY KEY)")
    for name, label in zip(release.FILES, ("003", "068", "069")):
        db.executescript((release.ROOT / name).read_text(encoding="utf-8"))
        if label == "003":
            db.execute("INSERT INTO users VALUES ('u')")
            db.execute("INSERT INTO projects VALUES ('p')")
            db.execute("INSERT INTO project_files VALUES ('f','p','u','test','text/plain','abc',3,'now','now')")
        assert release.classify(payload(db)) == (label, 1)
    db.execute("DROP INDEX idx_project_files_project_updated")
    assert release.classify(payload(db))[0] == "DRIFT"
    print("B62_PROJECT_FILES_068_069_SOURCE_TEST=PASS")

if __name__ == "__main__":
    main()
