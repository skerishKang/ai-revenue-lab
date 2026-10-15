#!/usr/bin/env python3
"""Exact additive migration 046 for private, owner-scoped CLAW GitHub App OAuth."""
from __future__ import annotations
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/046_claw_github_app_oauth.sql"
TABLES = ("claw_github_oauth_states", "claw_github_connections")
INDEX = "idx_claw_github_oauth_states_expiry"
OBJECTS = (*TABLES, INDEX)
QUERY = (
 "SELECT name,type,sql FROM sqlite_master WHERE name IN "
 "('users','claw_github_oauth_states','claw_github_connections','idx_claw_github_oauth_states_expiry');"
 "PRAGMA table_info(claw_github_oauth_states);"
 "PRAGMA table_info(claw_github_connections);"
 "PRAGMA foreign_key_list(claw_github_oauth_states);"
 "PRAGMA foreign_key_list(claw_github_connections);"
 "PRAGMA index_info(idx_claw_github_oauth_states_expiry);"
)

def norm(sql):
    return re.sub(r"\s+", " ", re.sub(r"\s*([(),;=])\s*", r"\1",
                     re.sub(r"--[^\n]*", "", sql).strip().lower())).strip()

def source():
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    if ("drop table" in upper or "alter table" in upper or "delete from" in upper
            or "create trigger" in upper or upper.count("create table if not exists") != 2
            or upper.count("create index if not exists") != 1):
        raise ValueError("Migration 046 is not the reviewed additive D1 SQL")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(text)
        objects = {x[0] for x in db.execute("SELECT name FROM sqlite_master")}
        if not set(OBJECTS).issubset(objects):
            raise ValueError("Migration 046 does not create its three required objects")
        for table in TABLES:
            fk = list(db.execute("PRAGMA foreign_key_list("+table+")"))
            if len(fk) != 1 or fk[0][2:7] != ("users","user_id","id","NO ACTION","CASCADE"):
                raise ValueError("GitHub owner foreign key does not delete by owner")
    finally:
        db.close()
    return text

def classify(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 schema API error")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != 6:
        raise ValueError("D1 schema response incomplete")
    blocks=[]
    for record in results:
        if not isinstance(record, dict) or record.get("success") is not True:
            raise ValueError("D1 statement failed")
        rows=record.get("results")
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):
            raise ValueError("D1 rows malformed")
        blocks.append(rows)
    objs, states, connections, fks_a, fks_b, index_cols=blocks
    names={item.get("name"):item for item in objs}
    if names.get("users",{}).get("type") != "table":
        return "drift"
    found=[name for name in OBJECTS if name in names]
    if not found:
        return "missing" if not any((states,connections,fks_a,fks_b,index_cols)) else "drift"
    if len(found)!=3:
        return "drift"
    db=sqlite3.connect(":memory:")
    db.row_factory=sqlite3.Row
    try:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.executescript(source())
        expected={row["name"]:norm(row["sql"]) for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE name IN (?,?,?)",OBJECTS)}
        for name in OBJECTS:
            if norm(str(names[name].get("sql") or "")) != expected[name]:
                return "drift"
        for table,cols in ((TABLES[0],states),(TABLES[1],connections)):
            wanted=[dict(x) for x in db.execute("PRAGMA table_info("+table+")")]
            if [(v.get("name"),v.get("type"),v.get("notnull"),v.get("pk")) for v in cols]!=[
                    (v["name"],v["type"],v["notnull"],v["pk"]) for v in wanted]:
                return "drift"
        for table,actual in ((TABLES[0],fks_a),(TABLES[1],fks_b)):
            wanted=[dict(x) for x in db.execute("PRAGMA foreign_key_list("+table+")")]
            keys=("table","from","to","on_delete")
            if [tuple(v.get(k) for k in keys) for v in actual]!=[
                    tuple(v[k] for k in keys) for v in wanted]:
                return "drift"
        desired=[dict(x) for x in db.execute("PRAGMA index_info("+INDEX+")")]
        if [(v.get("seqno"),v.get("name")) for v in index_cols]!=[
                (v["seqno"],v["name"]) for v in desired]:
            return "drift"
        return "exact"
    finally:
        db.close()

def main():
    if len(sys.argv)!=3:
        raise ValueError("expected <query|classify|apply|check-apply> <file>")
    action,path=sys.argv[1],Path(sys.argv[2])
    if action=="query":
        source()
        path.write_text(json.dumps({"sql":QUERY}), encoding="utf-8")
    elif action=="classify":
        print("B62_D1_MIGRATION_046_SCHEMA="+classify(json.loads(path.read_text(encoding="utf-8"))).upper())
    elif action=="apply":
        path.write_text(json.dumps({"sql":source()}), encoding="utf-8")
    elif action=="check-apply":
        payload=json.loads(path.read_text(encoding="utf-8"))
        rows=payload.get("result") if isinstance(payload,dict) and payload.get("success") is True else None
        if not isinstance(rows,list) or len(rows)<3 or any(
            not isinstance(x,dict) or x.get("success") is not True for x in rows):
            raise ValueError("D1 additive 046 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_046_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 046 gate operation")

if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,TypeError,sqlite3.Error) as error:
        print("B62_D1_MIGRATION_046_GATE=FAIL:"+str(error),file=sys.stderr)
        raise SystemExit(1)
