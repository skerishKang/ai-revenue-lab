#!/usr/bin/env python3
"""Exact additive migration 072 for the PC pairing code and device link tables.

Additive only, by contract: the gate refuses the file the moment it stops being
two `CREATE TABLE IF NOT EXISTS` plus their indexes, because 072 must never
rebuild or touch an existing table.
"""
from __future__ import annotations
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/072_pc_device_pairing.sql"
TABLES = ("pc_pairing_codes", "pc_device_links")
INDEXES = ("idx_pc_pairing_codes_state_expiry", "idx_pc_device_links_owner_state")
OBJECTS = TABLES + INDEXES
QUERY = (
 "SELECT name,type,sql FROM sqlite_master WHERE name IN "
 "('users','pc_pairing_codes','pc_device_links','idx_pc_pairing_codes_state_expiry',"
 "'idx_pc_device_links_owner_state');"
 "PRAGMA table_info(pc_pairing_codes);"
 "PRAGMA table_info(pc_device_links);"
)
REQUIRED_COLUMNS = {
    "pc_pairing_codes": {
        "code_id", "code_sha256", "tag_sha256", "user_id", "state", "mesh_node_id",
        "issued_at", "expires_at", "claimed_at",
    },
    "pc_device_links": {
        "link_id", "user_id", "mesh_node_id", "label", "state", "roots_json",
        "pairing_code_id", "created_at", "updated_at", "revoked_at",
    },
}
PRIMARY_KEYS = {"pc_pairing_codes": ["code_id"], "pc_device_links": ["link_id"]}


def norm(sql):
    return re.sub(r"\s+", " ", re.sub(r"\s*([(),;=])\s*", r"\1",
                     re.sub(r"--[^\n]*", "", sql).strip().lower())).strip()


def source():
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    if ("drop table" in upper or "alter table" in upper or "delete from" in upper
            or "update " in upper or "insert into" in upper or "create trigger" in upper
            or "create view" in upper
            or upper.count("create table if not exists") != len(TABLES)
            or upper.count("create index if not exists") != len(INDEXES)):
        raise ValueError("Migration 072 is not the reviewed additive D1 SQL")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(text)
        objects = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
        if not set(OBJECTS).issubset(objects):
            raise ValueError("Migration 072 does not create its required objects")
        for table in TABLES:
            columns = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
            if columns != REQUIRED_COLUMNS[table]:
                raise ValueError("Migration 072 table columns are not the reviewed set")
            pk = [row[1] for row in db.execute("PRAGMA table_info(" + table + ")") if row[5]]
            if pk != PRIMARY_KEYS[table]:
                raise ValueError("Migration 072 primary key is not the reviewed column")
    finally:
        db.close()
    return text


def classify(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 schema API error")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != 3:
        raise ValueError("D1 schema response incomplete")
    blocks = []
    for record in results:
        if not isinstance(record, dict) or record.get("success") is not True:
            raise ValueError("D1 statement failed")
        rows = record.get("results")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("D1 rows malformed")
        blocks.append(rows)
    objects = blocks[0]
    names = {item.get("name"): item for item in objects}
    if names.get("users", {}).get("type") != "table":
        return "DRIFT"
    built = {table: columns for table, columns in zip(TABLES, blocks[1:])}
    if any(table not in names for table in OBJECTS):
        return "MISSING" if not any(columns for columns in built.values()) else "DRIFT"
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(source())
        for table in TABLES:
            expected = norm(str(names[table].get("sql") or ""))
            actual = norm(str(db.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]))
            if expected != actual:
                return "DRIFT"
            wanted = [dict(row) for row in db.execute("PRAGMA table_info(" + table + ")")]
            if [(row.get("name"), row.get("type"), row.get("notnull"), row.get("pk"))
                    for row in built[table]] != [
                    (item["name"], item["type"], item["notnull"], item["pk"]) for item in wanted]:
                return "DRIFT"
        return "EXACT"
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
        print("B62_D1_MIGRATION_072_SCHEMA="
              + classify(json.loads(path.read_text(encoding="utf-8"))))
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(rows, list) or len(rows) < 1 or any(
                not isinstance(x, dict) or x.get("success") is not True for x in rows):
            raise ValueError("D1 additive 072 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_072_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 072 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_072_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
