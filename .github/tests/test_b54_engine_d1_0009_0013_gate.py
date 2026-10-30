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


FKFILE = P.parents[1] / "scripts/b54_engine_d1_0009_0013_foreign_keys.py"
fk_spec = importlib.util.spec_from_file_location("engine5359_fk", FKFILE)
fk = importlib.util.module_from_spec(fk_spec)
fk_spec.loader.exec_module(fk)

def test_fk_inventory_finds_quoted_and_case_variants():
    db=sqlite3.connect(":memory:")
    db.execute("CREATE TABLE padiem_engine_agent_runs_v1 (id TEXT PRIMARY KEY)")
    for i, name in enumerate(["padiem_engine_agent_runs_v1", '"PADIEM_ENGINE_AGENT_RUNS_V1"', "`padiem_engine_agent_runs_v1`", "[padiem_engine_agent_runs_v1]", "'padiem_engine_agent_runs_v1'"]):
        db.execute(f"CREATE TABLE child{i} (x TEXT REFERENCES {name}(id))")
    def query(sql):
        c=db.execute(sql)
        return {"success":True,"result":[{"success":True,"results":[dict(zip([d[0] for d in c.description],r)) for r in c]}]}
    assert len(fk.inventory(query)["inbound_foreign_keys"]) == 5
    assert fk.references("CREATE TABLE c(x TEXT REFERENCES /* comment */ PADIEM_ENGINE_AGENT_RUNS_V1(id))")

def test_fk_inventory_fails_closed_on_error_or_changed_tables():
    with pytest.raises(ValueError): fk.inventory(lambda _: {"success":False})
    calls=[]
    def changed(sql):
        calls.append(sql)
        name = "t" if len(calls)==1 else "other"
        return {"success":True,"result":[{"success":True,"results":[{"name":name,"sql":"CREATE TABLE t(x)"}]}]}
    with pytest.raises(ValueError): fk.inventory(changed)
    with pytest.raises(ValueError): fk.references("CREATE TABLE t(x REFERENCES ?)")

def test_generated_live_sql_is_read_only_under_sqlite_authorizer():
    db=make("0013")
    db.execute("CREATE TABLE child (run_id TEXT REFERENCES padiem_engine_agent_runs_v1(run_id))")
    states, grouped = m.classify(payload(db))
    actions=[]
    allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_PRAGMA}
    def authorizer(action, a, b, c, d):
        actions.append((action,a,b))
        if action not in allowed: return sqlite3.SQLITE_DENY
        if action==sqlite3.SQLITE_PRAGMA and (a!="foreign_key_list" or b is None): return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    db.set_authorizer(authorizer)
    db.execute(m.schema_sql()).fetchall()
    db.execute(m.count_sql(states, grouped)).fetchall()
    db.execute(fk.TABLES_QUERY).fetchall()
    assert all(action in allowed for action,_,_ in actions)
    with pytest.raises(sqlite3.DatabaseError): db.execute("DELETE FROM child")
    with pytest.raises(sqlite3.DatabaseError): db.execute("PRAGMA foreign_keys=OFF")


def test_reviewed_live_workflow_and_query_generators_are_pinned():
    # Any edit requires a fresh read-only audit and explicit digest update.
    # This catches shell additions, new SQL calls and mutable PRAGMA even if a
    # text-only "no DROP" search could be bypassed.
    import hashlib
    reviewed={
        P.parents[1]/"workflows/b54-engine-d1-0009-0013-readonly.yml":"a235e3eac281055143114cfd420d3e154f2c6db97dbbcb8ddaea376d3c90fadc",
        P:"3e50ee9431ab286063d0e1abaa08fa73203f2f9315ede820ebd7f18f5582abac",
        FKFILE:"bb4f0e41ef933bcd3cb813b8f3b72ff46a73ff45325e6806eb6c6231fecc4dcf",
    }
    for path, expected in reviewed.items():
        text=path.read_text(encoding="utf8")
        assert hashlib.sha256(text.encode("utf8")).hexdigest()==expected, f"re-audit read-only surface: {path.name}"
