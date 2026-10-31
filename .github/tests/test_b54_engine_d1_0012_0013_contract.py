import importlib.util
from pathlib import Path
import pytest
import yaml

ROOT=Path(__file__).parents[2]
SCRIPTS=ROOT/".github/scripts"

def load(name):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/(name+".py"))
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

binding=load("b54_engine_d1_0012_0013_verify_binding")
response=load("b54_engine_d1_0012_0013_verify_response")
payload=load("b54_engine_d1_0012_0013_payload")

def test_binding_is_unique_and_expected():
    good={"success":True,"result":{"bindings":[{"type":"d1","name":"ENGINE_IDEMPOTENCY","id":binding.DB}]}}
    binding.verify(good)
    for bad in ({"success":False}, {"success":True,"result":{"bindings":[]}}, {"success":True,"result":{"bindings":good["result"]["bindings"]*2}}):
        with pytest.raises(ValueError): binding.verify(bad)

def test_batch_must_report_each_statement_success():
    for number in ("0012","0013"):
        sql=payload.payload(number)["sql"]
        n=response.count_statements(sql)
        assert n>1
        response.verify({"success":True,"result":[{"success":True} for _ in range(n)]},sql)
        with pytest.raises(ValueError): response.verify({"success":True,"result":[{"success":True}]},sql)
        with pytest.raises(ValueError): response.verify({"success":True,"result":[{"success":False} for _ in range(n)]},sql)

def test_dispatch_order_and_scope():
    path=ROOT/".github/workflows/b54-engine-d1-0012-0013-apply.yml"
    text=path.read_text(encoding="utf8")
    parsed=yaml.safe_load(text)
    # PyYAML 1.1 interprets 'on' as True.
    assert list(parsed.get("on",parsed.get(True)).keys())==["workflow_dispatch"]
    for token in ("refs/heads/main","^[0-9a-f]{40}$","APPLY_ENGINE_D1_0012_0013_", "9be14bb7b8974e65d0afba647ab16932",binding.DB,"retention-days: 7","if-no-files-found: error"):
        assert token in text
    phases=["Verify main and binding before export","Export entire database","Store full export for 7 days","Reconfirm main and binding then inspect immediately before apply","Apply 0012 then guarded 0013","Verify exact schema, indexes and preserved row counts"]
    assert [text.index(p) for p in phases]==sorted(text.index(p) for p in phases)
    assert "for migration in 0012 0013" in text
    assert 'inspect.py before' in text and 'inspect.py after' in text

def test_count_query_is_bounded_to_existing_migration_tables(monkeypatch):
    import sys, sqlite3
    sys.path.insert(0,str(SCRIPTS))
    try: mod=load("b54_engine_d1_0012_0013_inspect")
    finally: sys.path.pop(0)
    db=sqlite3.connect(":memory:")
    names=list(mod.schema.TABLES.values())
    for name in names[:3]:
        db.execute('CREATE TABLE "'+name+'" (x)')
        db.execute('INSERT INTO "'+name+'" VALUES (1)')
    db.execute('CREATE TABLE unrelated (x)')
    states={k:("EXACT" if i<3 else "MISSING") for i,k in enumerate(mod.schema.TABLES)}
    grouped={name:([("table",name,name,"")] if i<3 else []) for i,name in enumerate(names)}
    queries=[]
    def q(sql):
        queries.append(sql)
        cur=db.execute(sql)
        rows=[dict(zip([c[0] for c in cur.description],r)) for r in cur]
        return {"success":True,"result":[{"success":True,"results":rows}]}
    monkeypatch.setattr(mod,"query",q)
    assert mod.table_counts(states,grouped)=={name:1 for name in names[:3]}
    assert len(queries)==1 and queries[0]==mod.schema.count_sql(states,grouped)
    assert "unrelated" not in queries[0] and "_cf_KV" not in queries[0]
    assert queries[0].count("UNION ALL") == 2


def test_http_error_logs_status_and_safe_cloudflare_errors(monkeypatch,capsys):
    import sys, io, json, urllib.error
    sys.path.insert(0,str(SCRIPTS))
    try: mod=load("b54_engine_d1_0012_0013_inspect")
    finally: sys.path.pop(0)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID",mod.ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN","sensitive-token")
    body=json.dumps({"errors":[{"code":7500,"message":"not authorized sensitive-token"}]}).encode()
    def fail(*a,**k):
        raise urllib.error.HTTPError("https://example.invalid",400,"bad",{},io.BytesIO(body))
    monkeypatch.setattr(mod.urllib.request,"urlopen",fail)
    with pytest.raises(urllib.error.HTTPError): mod.query("SELECT 1")
    output=capsys.readouterr().err
    assert '"status": 400' in output and '"code": 7500' in output
    assert "sensitive-token" not in output and "[REDACTED]" in output
