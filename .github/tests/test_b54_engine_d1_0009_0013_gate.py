import importlib.util
import sqlite3
from pathlib import Path
import pytest

P = Path(__file__).resolve().parents[1] / "scripts/b54_engine_d1_0009_0013_schema.py"
spec = importlib.util.spec_from_file_location("engine5359", P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def payload(db):
    rows = db.execute(m.schema_sql()).fetchall()
    return {"success":True,"result":[{"success":True,"results":[dict(zip(("type","name","tbl_name","sql"),r)) for r in rows]}]}

def make(last):
    db=sqlite3.connect(":memory:")
    for k, f in m.FILES.items():
        db.executescript((m.ROOT/f).read_text(encoding="utf8"))
        if k==last: break
    return db

def test_empty_is_missing():
    states,_=m.classify(payload(sqlite3.connect(":memory:")))
    assert set(states.values()) == {"MISSING"}

def test_pre_0013_and_post_0013():
    old=make("0012")
    states,_=m.classify(payload(old))
    assert [states[k] for k in ("0009","0010","0011","0012","0013")] == ["EXACT"]*4+["MISSING"]
    old.close()
    new=make("0013")
    states,objects=m.classify(payload(new))
    assert set(states.values()) == {"EXACT"}
    assert len([r for r in objects[m.TABLES["0011"]] if r[0]=="index"]) == 3

def test_drift_and_rebuild_debris_fail_closed():
    db=make("0012")
    db.execute("CREATE INDEX unexpected ON padiem_engine_agent_runs_v1(epoch)")
    states,_=m.classify(payload(db))
    assert states["0011"] == states["0013"] == "DRIFT"
    db.execute("DROP INDEX unexpected")
    db.execute("CREATE TABLE padiem_engine_agent_runs_v1_widened(x)")
    assert m.classify(payload(db))[0]["0013"] == "DRIFT"

def test_bad_api_does_not_look_empty():
    with pytest.raises(ValueError): m.classify({"success":False})
    with pytest.raises(ValueError): m.classify({"success":True,"result":[]})

def test_count_query_only_present_tables():
    db=make("0010")
    states,_=m.classify(payload(db))
    q=m.count_sql(states)
    rows=db.execute(q).fetchall()
    assert len(rows)==2 and all(r[1]==0 for r in rows)


def test_drift_table_counts_can_be_inspected_without_mutation():
    db=make("0012")
    db.execute("CREATE INDEX unexpected ON padiem_engine_agent_runs_v1(epoch)")
    states, grouped = m.classify(payload(db))
    assert states["0013"] == "DRIFT"
    assert any(name == m.TABLES["0011"] for name, count in db.execute(m.count_sql(states, grouped)))
    assert all(s.strip().upper().startswith("SELECT") for s in [m.schema_sql(),m.count_sql(states,grouped)])

def test_dispatch_workflow_is_read_only_and_sha_pinned():
    text=(P.parents[1]/"workflows/b54-engine-d1-0009-0013-readonly.yml").read_text(encoding="utf8")
    assert "workflow_dispatch:" in text and "pull_request:" not in text
    assert "^[0-9a-f]{40}$" in text and "git rev-parse FETCH_HEAD" in text
    assert "ENGINE_IDEMPOTENCY" in text and "padiem-ai-engine/settings" in text
    assert "PRODUCTION_MUTATION=0" in text
    assert "d1 export" not in text and "d1 execute" not in text
