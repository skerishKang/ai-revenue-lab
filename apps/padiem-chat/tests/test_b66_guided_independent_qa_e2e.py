"""Isolated real-SQL Guided draft QA across two independently authenticated owners.

This uses actual B66 Starlette routes and the real 028 D1 SQL schema on a
transactional SQLite test DB, never production D1. Browser/PDF output is covered
separately by protected CGI production browser run 38070751613.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

from test_b66_guided_draft import A, B, _client, sample, source

STEPS=(
    "recipientCompany","recipientPerson","itemName","qty","price",
    "moreItems","tax","memo","senderChoice","summary",
)


def test_isolated_two_accounts_full_ten_step_real_sql_draft(source):
    db, store=source
    owner_first=_client(store,user=A)
    owner_reopened=_client(store,user=A)
    foreign=_client(store,user=B)
    absent={"ok":True,"state":None}
    assert owner_first.get("/api/b66/guided-draft").json()==absent
    assert owner_reopened.get("/api/b66/guided-draft").json()==absent
    assert foreign.get("/api/b66/guided-draft").json()==absent

    state=sample()
    state["savedSkillId"]="b66skill_"+"b"*32
    state["draft"]["meta"]["quoteNo"]="B66-QA-INDEPENDENT-ONLY"
    state["draft"]["recipient"]["company"]="SYNTHETIC QA CONSTRUCTION"
    state["draft"]["sender"]["company"]="SYNTHETIC QA SUPPLIER"
    snapshots=[]
    for index,step in enumerate(STEPS):
        state["step"]=step
        if index < 2:
            state["currentItem"]=-1
            state["draft"]["items"]=[]
        elif index < 3:
            state["currentItem"]=0
            state["draft"]["items"]=[{"id":"item-1","name":"Test piping",
                                       "qty":None,"unitPrice":None,"unit":""}]
        elif index < 4:
            state["draft"]["items"][0]["qty"]=2
        elif index >= 5:
            state["draft"]["items"][0]["unitPrice"]=10000
        request=copy.deepcopy(state)
        write=owner_first.put("/api/b66/guided-draft",json=request)
        assert write.status_code==200,(index,write.status_code)
        read=owner_reopened.get("/api/b66/guided-draft")
        assert read.status_code==200
        stored=read.json()["state"]
        assert stored is not None and stored["step"]==step
        assert stored["draft"]["meta"]["quoteNo"]=="B66-QA-INDEPENDENT-ONLY"
        assert foreign.get("/api/b66/guided-draft").json()==absent
        snapshots.append(stored)
    assert len(snapshots)==10
    assert snapshots[-1]["draft"]["items"]==[
        {"id":"item-1","name":"Test piping","unit":"",
         "qty":2,"unitPrice":10000}
    ]
    # QuoteCore is the final amount calculation authority. Verify via source,
    # not an invented Python duplicate of its rounding rules.
    core=Path(__file__).resolve().parents[3]/"reference"/"business-66-padiem-quote-v1"/"quote-core.js"
    js=("const Core=require(process.argv[1]);"
        "const draft=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "const value=Core.computeDraftTotals(draft);"
        "if(!value||value.subtotal!==20000||value.vat!==2000||value.grand!==22000)"
        "process.exit(9);console.log('QUOTECORE_TOTAL=PASS');")
    last=copy.deepcopy(snapshots[-1]["draft"])
    last["schemaVersion"]=1
    last["meta"]["source"]="guided"
    output=subprocess.run(
        ["node","-e",js,str(core)],input=json.dumps(last),
        text=True,capture_output=True,encoding="utf-8",check=False)
    assert output.returncode==0,"QuoteCore rejected migrated Guided draft"
    assert "QUOTECORE_TOTAL=PASS" in output.stdout

    # Only this synthetic owner's scoped row may be removed; foreign account's
    # independent slot remains inaccessible and untouched.
    assert owner_reopened.delete("/api/b66/guided-draft").status_code==200
    assert owner_first.get("/api/b66/guided-draft").json()==absent
    assert foreign.get("/api/b66/guided-draft").json()==absent
    assert db.execute("SELECT COUNT(*) FROM b66_guided_draft").fetchone()[0]==0
