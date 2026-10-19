"""#3933 B62 private one-shot WRITE owner decision D1 tests.

Separate from the earlier original READ decision and source-only edit claim.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3933_web_quote_write_gate import prepared
from test_3580_web_xlsx_selection_routes import RealSQLiteD1
from test_3580_web_xlsx_sources import OWNER
from app.claw_web_xlsx_quote_write_owner_decision import (
    D1WebQuoteWriteOwnerDecisionStore,
)

PAUSE="pause:"+"b"*32
CONT="cont_"+"c"*36
SCHOOL="Gwangju University"
AMOUNT=99_200_000


async def setup(monkeypatch):
    app,settings,meta,r2,db,h,sel,src,before,preview=await prepared(
        monkeypatch, enabled=False)
    schema=Path(__file__).resolve().parents[1]/"migrations"/"033_claw_web_xlsx_quote_write_decisions.sql"
    db.executescript(schema.read_text(encoding="utf-8"))
    editor=app.state.web_xlsx_quote_write_store
    copy=await app.state.workspace_document_store.find_approved_web_xlsx_workcopy(
        tenant_id="owner:"+OWNER,owner_id=OWNER,workspace_id="owner:"+OWNER,
        run_id="run_web_3580_actual",source_document_id=src["document_id"],
        expected_source_sha256=src["source_sha256"],
    )
    assert copy["workcopy_created"] is True
    row=dict(
        selection_ref=sel["selection_ref"],user_id=OWNER,
        workspace_id="owner:"+OWNER,run_id="run_web_3580_actual",
        source_document_id=src["document_id"],
        source_sha256=src["source_sha256"],
        workcopy_document_id=copy["workcopy_document_id"],
        edit_sha256=preview["edit_sha256"],
        school_name=SCHOOL,supply_amount=AMOUNT,
    )
    await editor.reserve(row)
    store=D1WebQuoteWriteOwnerDecisionStore(RealSQLiteD1(db))
    return db,store,row


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,state", [
    ("approve","confirmed"),("deny","denied"),
])
async def test_signed_owner_write_decision_is_exactly_once(monkeypatch,outcome,state):
    db,store,row=await setup(monkeypatch)
    waiting=await store.load_waiting(
        owner_id=row["user_id"],workspace_id=row["workspace_id"],
        selection_ref=row["selection_ref"])
    assert waiting is not None and waiting["edit_sha256"]==row["edit_sha256"]
    assert await store.load_waiting(
        owner_id="foreign",workspace_id=row["workspace_id"],
        selection_ref=row["selection_ref"]) is None
    await store.reserve(row=row,pause_id=PAUSE,
                        continuation_ref=CONT,outcome=outcome)
    with pytest.raises(Exception):
        await store.reserve(row=row,pause_id=PAUSE,
                            continuation_ref=CONT,outcome=outcome)
    receipt=db.execute(
        "SELECT state,outcome,edit_sha256,pause_id,continuation_ref "
        "FROM claw_web_xlsx_quote_write_decisions",
    ).fetchone()
    assert receipt["state"]=="dispatching"
    assert receipt["outcome"]==outcome
    assert receipt["edit_sha256"]==row["edit_sha256"]
    assert receipt["pause_id"]==PAUSE
    assert receipt["continuation_ref"]==CONT
    assert await store.finish(row=row,pause_id=PAUSE,
        continuation_ref=CONT,outcome=outcome,engine_status=state) is True
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_quote_write_decisions"
    ).fetchone()["state"]==state
    db.close()


@pytest.mark.asyncio
async def test_unknown_outcome_stays_consumed_and_cannot_auto_retry(monkeypatch):
    db,store,row=await setup(monkeypatch)
    await store.reserve(row=row,pause_id=PAUSE,
                        continuation_ref=CONT,outcome="approve")
    assert await store.finish(row=row,pause_id=PAUSE,
        continuation_ref=CONT,outcome="approve",engine_status="unavailable") is False
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_quote_write_decisions"
    ).fetchone()["state"]=="dispatching"
    with pytest.raises(Exception):
        await store.reserve(row=row,pause_id=PAUSE,
                            continuation_ref=CONT,outcome="deny")
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation",[
    {"user_id":"foreign"},
    {"source_sha256":"f"*64},
    {"edit_sha256":"f"*64},
    {"workcopy_document_id":"doc_"+"f"*32},
    {"supply_amount":100000000},
    {"school_name":"Other University"},
])
async def test_tampered_browser_or_engine_write_context_refused(monkeypatch,mutation):
    db,store,row=await setup(monkeypatch)
    altered=dict(row,**mutation)
    with pytest.raises((ValueError,Exception)):
        await store.reserve(row=altered,pause_id=PAUSE,
                            continuation_ref=CONT,outcome="approve")
    assert db.execute(
        "SELECT COUNT(*) AS cnt FROM claw_web_xlsx_quote_write_decisions"
    ).fetchone()["cnt"]==0
    db.close()


@pytest.mark.asyncio
async def test_invalid_pause_continuation_and_outcome_refused(monkeypatch):
    db,store,row=await setup(monkeypatch)
    for x in (
        dict(pause_id="browser_pause",continuation_ref=CONT,outcome="approve"),
        dict(pause_id=PAUSE,continuation_ref="arbitrary_url",outcome="approve"),
        dict(pause_id=PAUSE,continuation_ref=CONT,outcome="write_without_approval"),
    ):
        with pytest.raises(ValueError):
            await store.reserve(row=row,**x)
    assert db.execute(
        "SELECT COUNT(*) AS cnt FROM claw_web_xlsx_quote_write_decisions"
    ).fetchone()["cnt"]==0
    db.close()
