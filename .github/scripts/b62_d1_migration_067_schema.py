#!/usr/bin/env python3
"""Exact additive migration 067 for the Mesh device presence receipt table."""
from __future__ import annotations
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/067_mesh_device_presence.sql"
TABLE = "mesh_device_presence"
OBJECTS = (TABLE,)
QUERY = (
 "SELECT name,type,sql FROM sqlite_master WHERE name IN "
 "('users','mesh_device_presence');"
 "PRAGMA table_info(mesh_device_presence);"
)


def norm(sql):
    return re.sub(r"\s+", " ", re.sub(r"\s*([(),;=])\s*", r"\1",
                     re.sub(r"--[^\n]*", "", sql).strip().lower())).strip()


def source():
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    if ("drop table" in upper or "alter table" in upper or "delete from" in upper
            or "create trigger" in upper
            or upper.count("create table if not exists") != 1):
        raise ValueError("Migration 067 is not the reviewed additive D1 SQL")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(text)
        objects = {x[0] for x in db.execute("SELECT name FROM sqlite_master")}
        if not set(OBJECTS).issubset(objects):
            raise ValueError("Migration 067 does not create its required object")
        columns = {row[1] for row in db.execute("PRAGMA table_info(" + TABLE + ")")}
        required = {"device_id", "connected", "received_at", "credential_generation"}
        if columns != required:
            raise ValueError("Migration 067 table columns are not the reviewed set")
        pk = [row[1] for row in db.execute("PRAGMA table_info(" + TABLE + ")")
              if row[5]]
        if pk != ["device_id"]:
            raise ValueError("Migration 067 primary key is not device_id alone")
    finally:
        db.close()
    return text


def classify(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 schema API error")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != 2:
        raise ValueError("D1 schema response incomplete")
    blocks = []
    for record in results:
        if not isinstance(record, dict) or record.get("success") is not True:
            raise ValueError("D1 statement failed")
        rows = record.get("results")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("D1 rows malformed")
        blocks.append(rows)
    objects, columns = blocks
    names = {item.get("name"): item for item in objects}
    if names.get("users", {}).get("type") != "table":
        return "drift"
    if TABLE not in names:
        return "missing" if not columns else "drift"
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(source())
        expected = norm(str(names[TABLE].get("sql") or ""))
        if norm(str(db.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()["sql"])) != expected:
            return "drift"
        wanted = [dict(x) for x in db.execute("PRAGMA table_info(" + TABLE + ")")]
        if [(v.get("name"), v.get("type"), v.get("notnull"), v.get("pk"))
                for v in columns] != [
                (v["name"], v["type"], v["notnull"], v["pk"]) for v in wanted]:
            return "drift"
        return "exact"
    finally:
        db.close()


def main():
    if len(sys.argv) != 3:
        raise ValueError("expected <query|classify|apply|check-apply> <file>")
    action, path = sys.argv[1], Path(sys.argv[2])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        print("B62_D1_MIGRATION_067_SCHEMA="
              + classify(json.loads(path.read_text(encoding="utf-8"))).upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(rows, list) or len(rows) < 1 or any(
                not isinstance(x, dict) or x.get("success") is not True for x in rows):
            raise ValueError("D1 additive 067 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_067_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 067 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_067_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
