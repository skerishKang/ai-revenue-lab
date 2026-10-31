import copy
import importlib.util
from pathlib import Path
import pytest

path=Path(__file__).parents[1]/"scripts/b54_engine_d1_0012_0013_apply_evidence.py"
spec=importlib.util.spec_from_file_location("apply_evidence",path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def schema(post=False):
    return {"migrations":{str(i).zfill(4):("EXACT" if post or i<12 else "MISSING") for i in range(9,14)},
            "rebuild_table":m.RUNS,"indexes":list(m.EXPECTED_INDEXES)}
def payload(values):
    return {"success":True,"result":[{"success":True,"results":[{"name":k,"n":v} for k,v in values.items()]}]}
def valid():
    return schema(),payload({m.XLSX:12,m.QUOTE:6,m.RUNS:0}),{"inbound_foreign_keys":[],"tables_inspected":4}

def test_before_accepts_reviewed_evidence():
    s,c,f=valid()
    assert m.before(s,c,f)=={m.XLSX:12,m.QUOTE:6,m.RUNS:0}

@pytest.mark.parametrize("change",["schema","runs","references","fk_unavailable","missing","duplicate","index"])
def test_before_rejects_uncertain_or_changed_evidence(change):
    s,c,f=valid()
    if change=="schema": s["migrations"]["0012"]="EXACT"
    if change=="runs": c["result"][0]["results"][2]["n"]=1
    if change=="references": f["inbound_foreign_keys"]=[{"table":"child"}]
    if change=="fk_unavailable": f={}
    if change=="missing": c["result"][0]["results"].pop()
    if change=="duplicate": c["result"][0]["results"].append(copy.deepcopy(c["result"][0]["results"][0]))
    if change=="index": s["indexes"].pop()
    with pytest.raises(ValueError): m.before(s,c,f)

def test_after_requires_exact_schema_and_preserved_counts():
    s,c,f=valid()
    baseline=m.before(s,c,f)
    post=payload({**baseline,m.RESULTS:0})
    assert m.after(schema(True),post,baseline)[m.XLSX]==12
    post["result"][0]["results"][0]["n"]=13
    with pytest.raises(ValueError): m.after(schema(True),post,baseline)
    with pytest.raises(ValueError): m.after(schema(),payload({**baseline,m.RESULTS:0}),baseline)
