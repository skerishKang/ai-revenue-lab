#!/usr/bin/env python3
"""Exact additive migration 047 for the Oracle Mesh read dispatch table."""
from __future__ import annotations
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/047_oracle_mesh_dispatch.sql"
TABLE = "oracle_mesh_dispatch"
INDEX = "idx_oracle_mesh_dispatch_state_expiry"
OBJECTS = (TABLE, INDEX)
QUERY = (
 "SELECT name,type,sql FROM sqlite_master WHERE name IN "
 "('users','oracle_mesh_dispatch','idx_oracle_mesh_dispatch_state_expiry');"
 "PRAGMA table_info(oracle_mesh_dispatch);"
 "PRAGMA index_info(idx_oracle_mesh_dispatch_state_expiry);"
)


def norm(sql):
    return re.sub(r"\s+", " ", re.sub(r"\s*([(),;=])\s*", r"\1",
                     re.sub(r"--[^\n]*", "", sql).strip().lower())).strip()


def source():
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    if ("drop table" in upper or "alter table" in upper or "delete from" in upper
            or "create trigger" in upper
            or upper.count("create table if not exists") != 1
            or upper.count("create index if not exists") != 1):
        raise ValueError("Migration 047 is not the reviewed additive D1 SQL")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(text)
        objects = {x[0] for x in db.execute("SELECT name FROM sqlite_master")}
        if not set(OBJECTS).issubset(objects):
            raise ValueError("Migration 047 does not create its two required objects")
        columns = {row[1] for row in db.execute("PRAGMA table_info(" + TABLE + ")")}
        required = {
            "dispatch_id", "user_id", "run_id", "command_id", "tool_request_ref",
            "request_id", "revision_ref", "evidence_ref", "request_fingerprint",
            "account_ref", "workspace_ref", "device_id", "binding_ref", "node_ref",
            "root_ref", "path_relative", "file_path", "nonce_sha256", "state",
            "result_sha256", "result_bytes", "expires_at", "created_at",
        }
        if not required.issubset(columns):
            raise ValueError("Migration 047 table is missing required columns")
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
    objects, columns, index_cols = blocks
    names = {item.get("name"): item for item in objects}
    if names.get("users", {}).get("type") != "table":
        return "drift"
    found = [name for name in OBJECTS if name in names]
    if not found:
        return "missing" if not any((columns, index_cols)) else "drift"
    if len(found) != 2:
        return "drift"
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(source())
        expected = {row["name"]: norm(row["sql"]) for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE name IN (?,?)", OBJECTS)}
        for name in OBJECTS:
            if norm(str(names[name].get("sql") or "")) != expected[name]:
                return "drift"
        wanted = [dict(x) for x in db.execute("PRAGMA table_info(" + TABLE + ")")]
        if [(v.get("name"), v.get("type"), v.get("notnull"), v.get("pk"))
                for v in columns] != [
                (v["name"], v["type"], v["notnull"], v["pk"]) for v in wanted]:
            return "drift"
        desired = [dict(x) for x in db.execute("PRAGMA index_info(" + INDEX + ")")]
        if [(v.get("seqno"), v.get("name")) for v in index_cols] != [
                (v["seqno"], v["name"]) for v in desired]:
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
        print("B62_D1_MIGRATION_047_SCHEMA="
              + classify(json.loads(path.read_text(encoding="utf-8"))).upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(rows, list) or len(rows) < 2 or any(
            not isinstance(x, dict) or x.get("success") is not True for x in rows):
            raise ValueError("D1 additive 047 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_047_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 047 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_047_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)