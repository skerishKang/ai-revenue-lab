"""#3580 B62 exact owner/session XLSX approval decisions and one-shot D1 receipts."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_p01_request import harness, prepare, submit
from test_3580_web_xlsx_selection_routes import RealSQLiteD1
from test_3580_web_xlsx_sources import request, OWNER, FOREIGN
from app.claw_web_xlsx_p01_owner_decision import D1WebXlsxP01OwnerDecisionStore

PATH = "/api/claw/office/web-selections/{}/p01-decision"


class DecisionEngine:
    def __init__(self):
        self.calls = []
        self.status = "denied"
        self.raise_ = False

    async def resume_owner_decision(self, *, continuation_ref, submission):
        self.calls.append((continuation_ref, submission))
        if self.raise_:
            raise RuntimeError("unknown Engine outcome")
        return {"ok": True, "status": self.status}


def ready():
    app, settings, meta, r2, db, history, engine = harness()
    db.executescript((
        Path(__file__).resolve().parents[1] / "migrations" /
        "031_claw_web_xlsx_p01_decision_receipts.sql").read_text(encoding="utf-8"))
    app.state.web_xlsx_p01_owner_decision_store = D1WebXlsxP01OwnerDecisionStore(RealSQLiteD1(db))
    decision_engine = DecisionEngine()
    app.state.web_xlsx_p01_owner_decision_client = decision_engine
    return app, settings, meta, r2, db, history, decision_engine


async def setup_pause(app, settings):
    original, selection = await prepare(app, settings)
    paused = await submit(app, settings, selection["selection_ref"])
    assert paused.status_code == 202, paused.text
    return original, selection


async def decide(app, settings, selection, *, owner=OWNER, decision="deny", data=None):
    return await request(
        app, settings, owner=owner, method="POST",
        path=PATH.format(selection["selection_ref"]),
        payload=data if data is not None else {"decision": decision},
    )


@pytest.mark.asyncio
async def test_real_signed_in_owner_denial_consumed_exact_once():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    result = await decide(app, settings, selection)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "denied"
    assert result.json()["workcopy_created"] is False
    assert len(client.calls) == 1
    continuation, evidence = client.calls[0]
    assert continuation == db.execute(
        "SELECT continuation_ref FROM claw_web_xlsx_p01_requests").fetchone()[0]
    assert evidence["outcome"] == "denied"
    assert evidence["pause_id"] == db.execute(
        "SELECT pause_id FROM claw_web_xlsx_p01_requests").fetchone()[0]
    assert evidence["authority_ref"].endswith(OWNER)
    assert not any(s in evidence for s in ("tool_id", "arguments", "model", "credential"))
    record = db.execute(
        "SELECT * FROM claw_web_xlsx_p01_decision_receipts").fetchone()
    assert record["state"] == "denied"
    assert record["run_id"] == "run_web_3580_actual"
    assert record["source_sha256"] == original["source_sha256"]
    replay = await decide(app, settings, selection)
    assert replay.status_code in (409, 503)
    assert len(client.calls) == 1
    db.close()


@pytest.mark.asyncio
async def test_cross_owner_cross_workspace_wrong_run_blocked_without_engine():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    assert (await decide(app, settings, selection, owner=None)).status_code == 401
    assert (await decide(app, settings, selection, owner=FOREIGN)).status_code == 404
    history.foreign = True
    assert (await decide(app, settings, selection)).status_code == 404
    history.foreign = False
    db.execute("UPDATE claw_web_xlsx_p01_requests SET run_id='different_owner_run'")
    assert (await decide(app, settings, selection)).status_code == 404
    assert not client.calls
    assert not list(db.execute("SELECT * FROM claw_web_xlsx_p01_decision_receipts"))
    db.close()


@pytest.mark.asyncio
async def test_original_sha_mutation_expiry_and_closed_run_block_before_receipt():
    from dataclasses import replace
    for drift in ("sha", "run", "expiry"):
        app, settings, meta, r2, db, history, client = ready()
        original, selection = await setup_pause(app, settings)
        if drift == "sha":
            doc = original["document_id"]
            row = meta.rows[doc]
            meta.rows[doc] = replace(
                row, object_key=row.object_key.replace(
                    original["source_sha256"], "f"*64),
            )
        elif drift == "run":
            history.foreign = True
        else:
            db.execute(
                "UPDATE claw_web_xlsx_p01_requests SET pause_expires_at=?",
                ("2000-01-01T00:00:00+00:00",),
            )
        rejected = await decide(app, settings, selection)
        assert rejected.status_code == 404
        assert not client.calls
        assert not list(db.execute(
            "SELECT * FROM claw_web_xlsx_p01_decision_receipts"))
        db.close()


@pytest.mark.asyncio
async def test_browser_cannot_inject_engine_continuation_or_tool_grants():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    for authority in (
        {"continuation_ref": "cont_attacker"},
        {"pause_id": "pause:attacker"},
        {"owner_id": OWNER},
        {"workspace_id": "owner:foreign"},
        {"tool_id": "tool:padiem:other@1"},
        {"tool_arguments": {"drive_write": True}},
        {"decision_id": "forged"},
        {"run_id": "wrong_run"},
    ):
        res = await decide(
            app, settings, selection,
            data={"decision": "approve", **authority},
        )
        assert res.status_code == 400, res.text
    assert not client.calls
    assert not list(db.execute(
        "SELECT * FROM claw_web_xlsx_p01_decision_receipts"))
    db.close()


@pytest.mark.asyncio
async def test_uncertain_engine_decision_cannot_be_replayed_or_changed():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    client.raise_ = True
    first = await decide(app, settings, selection)
    assert first.status_code == 503
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_p01_decision_receipts"
    ).fetchone()[0] == "dispatching"
    second = await decide(app, settings, selection, decision="approve")
    assert second.status_code in (409, 503)
    assert len(client.calls) == 1
    db.close()


@pytest.mark.asyncio
async def test_engine_approval_failure_not_falsely_reported_success():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    client.status = "not_authorized"
    response = await decide(app, settings, selection, decision="approve")
    assert response.status_code == 409
    assert len(client.calls) == 1
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_p01_decision_receipts"
    ).fetchone()[0] == "dispatching"
    db.close()


@pytest.mark.asyncio
async def test_approved_confirmation_proves_intent_only_not_xlsx_processing():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    client.status = "confirmed"
    response = await decide(app, settings, selection, decision="approve")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"
    assert response.json()["processing_started"] is False
    assert response.json()["workcopy_created"] is False
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_p01_decision_receipts"
    ).fetchone()[0] == "confirmed"
    db.close()


@pytest.mark.asyncio
async def test_concurrent_owner_decision_dispatch_single_engine_attempt():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    results = await asyncio.gather(*(
        decide(app, settings, selection) for _ in range(3)
    ))
    assert sorted(x.status_code for x in results) == [200, 503, 503]
    assert len(client.calls) == 1
    assert len(list(db.execute(
        "SELECT * FROM claw_web_xlsx_p01_decision_receipts"
    ))) == 1
    db.close()


@pytest.mark.asyncio
async def test_missing_migration_or_unconfigured_engine_never_dispatches():
    app, settings, meta, r2, db, history, client = ready()
    original, selection = await setup_pause(app, settings)
    app.state.web_xlsx_p01_owner_decision_client = None
    assert (await decide(app, settings, selection)).status_code == 503
    app.state.web_xlsx_p01_owner_decision_client = client
    db.execute("DROP TABLE claw_web_xlsx_p01_decision_receipts")
    assert (await decide(app, settings, selection)).status_code == 503
    assert not client.calls
    db.close()
