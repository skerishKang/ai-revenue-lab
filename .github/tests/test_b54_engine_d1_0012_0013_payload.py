import importlib.util
import sqlite3
from pathlib import Path
import pytest

root=Path(__file__).parents[2]
path=root/".github/scripts/b54_engine_d1_0012_0013_payload.py"
spec=importlib.util.spec_from_file_location("apply_payload",path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def statements(script):
    current=""
    for line in script.splitlines(keepends=True):
        current+=line
        if sqlite3.complete_statement(current):
            yield current
            current=""
    assert not current.strip()

def db_before():
    db=sqlite3.connect(":memory:")
    db.executescript((m.ROOT/m.FILES["0012"]).read_text(encoding="utf8"))
    db.executescript((m.ROOT/"0011_engine_agent_durable_runs.sql").read_text(encoding="utf8"))
    return db

def run_batch(db):
    db.execute("BEGIN")
    try:
        for statement in statements(m.payload("0013")["sql"]):
            db.execute(statement)
        db.commit()
    except Exception:
        db.rollback()
        raise

def test_empty_run_table_migrates():
    db=db_before()
    run_batch(db)
    sql=db.execute("SELECT sql FROM sqlite_master WHERE name='padiem_engine_agent_runs_v1'").fetchone()[0]
    assert "checkpoint_step>=0" in sql and "checkpoint_step<=64" not in sql

def test_inserted_row_after_preflight_aborts_before_rebuild():
    db=db_before()
    db.execute("INSERT INTO padiem_engine_agent_runs_v1 (run_id,owner_scope,request_fingerprint,worker_id,epoch,status,lease_until,heartbeat_at,checkpoint_step,side_effect_uncertain) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("r","o","a"*64,"w",1,"running",1,1,1,0))
    db.commit()
    before=db.execute("SELECT sql FROM sqlite_master WHERE name='padiem_engine_agent_runs_v1'").fetchone()[0]
    with pytest.raises(sqlite3.OperationalError,match="integer overflow"): run_batch(db)
    assert db.execute("SELECT count(*) FROM padiem_engine_agent_runs_v1").fetchone()[0]==1
    assert db.execute("SELECT sql FROM sqlite_master WHERE name='padiem_engine_agent_runs_v1'").fetchone()[0]==before
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='padiem_engine_agent_runs_v1_widened'").fetchone()[0]==0

def test_only_approved_migrations_and_guard_first():
    assert m.payload("0013")["sql"].startswith(m.GUARD)
    assert "PRAGMA foreign_keys" not in m.payload("0013")["sql"]
    with pytest.raises(ValueError): m.payload("0009")
