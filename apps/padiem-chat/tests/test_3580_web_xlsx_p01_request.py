"""#3580: owner-scoped P01 request reservation; no fake browser approval."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from _support.web_xlsx_p01_request import (
    CapturingEngine, OwnerRunHistory, harness, prepare, projected_pause, submit)
from _support.web_xlsx_sources import OWNER, FOREIGN
from app.claw_web_xlsx_p01_request import TrustedWebXlsxP01Request

__all__ = [
    "CapturingEngine", "OwnerRunHistory", "harness", "prepare",
    "projected_pause", "submit",
]


@pytest.mark.asyncio
async def test_b62_dispatch_validated_owner_source_and_durable_one_shot_pause():
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    result = await submit(app, settings, selection["selection_ref"])
    assert result.status_code == 202, result.text
    record = result.json()["request"]
    assert record["status"] == "waiting_p01"
    assert record["owner_decision_enabled"] is False
    assert record["processing_started"] is False
    assert record["workcopy_created"] is False
    assert len(engine.calls) == 1
    trusted = engine.calls[0]
    assert trusted.source_sha256 == original["source_sha256"]
    assert trusted.workspace_id == "owner:" + OWNER
    assert trusted.document_id == original["document_id"]
    assert trusted.run_id == "run_web_3580_actual"
    row = db.execute("SELECT * FROM claw_web_xlsx_p01_requests").fetchone()
    assert row["status"] == "waiting_p01"
    assert row["selection_ref"] == selection["selection_ref"]
    assert row["source_sha256"] == original["source_sha256"]
    assert row["continuation_ref"] == "cont_" + "c" * 32
    replay = await submit(app, settings, selection["selection_ref"])
    assert replay.status_code in (409, 503)
    assert len(engine.calls) == 1
    assert len(list(db.execute("SELECT * FROM claw_web_xlsx_p01_requests"))) == 1
    db.close()


@pytest.mark.asyncio
async def test_cross_owner_and_wrong_workspace_or_run_fail_before_engine():
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    assert (await submit(app, settings, selection["selection_ref"], owner=FOREIGN)).status_code == 404
    assert (await submit(app, settings, selection["selection_ref"], owner=None)).status_code == 401
    history.foreign = True
    assert (await submit(app, settings, selection["selection_ref"])).status_code == 404
    history.foreign = False
    assert (await submit(app, settings, selection["selection_ref"],
                         payload={"run_id": "not_owned_run"})).status_code == 404
    assert engine.calls == []
    assert list(db.execute("SELECT * FROM claw_web_xlsx_p01_requests")) == []
    db.close()


@pytest.mark.asyncio
async def test_excess_caller_authority_and_unconfigured_client_fail_closed():
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    for extra in (
        {"decision": "approve"}, {"pause_id": "pause_bogus"},
        {"owner_id": OWNER}, {"workspace_id": "owner:foreign"},
        {"source_sha256": original["source_sha256"]},
        {"tool_arguments": {"drive_write": True}},
    ):
        result = await submit(app, settings, selection["selection_ref"], payload={
            "run_id": "run_web_3580_actual", **extra,
        })
        assert result.status_code == 400
    app.state.web_xlsx_p01_pause_client = None
    assert (await submit(app, settings, selection["selection_ref"])).status_code == 503
    assert engine.calls == []
    db.close()


@pytest.mark.asyncio
async def test_uncertain_engine_dispatch_never_auto_retries():
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    engine.mode = "raised"
    first = await submit(app, settings, selection["selection_ref"])
    assert first.status_code == 503
    assert db.execute(
        "SELECT status FROM claw_web_xlsx_p01_requests").fetchone()["status"] == "dispatching"
    second = await submit(app, settings, selection["selection_ref"])
    assert second.status_code in (409, 503)
    assert len(engine.calls) == 1
    db.close()


@pytest.mark.asyncio
async def test_only_engine_issued_matching_paused_projection_is_accepted():
    for mode in ("fake_approved", "wrong_source"):
        app, settings, meta, r2, db, history, engine = harness()
        original, selection = await prepare(app, settings)
        engine.mode = mode
        res = await submit(app, settings, selection["selection_ref"])
        assert res.status_code == 409
        assert db.execute(
            "SELECT status FROM claw_web_xlsx_p01_requests").fetchone()["status"] == "dispatching"
        db.close()


@pytest.mark.asyncio
async def test_replayed_concurrent_browser_dispatch_is_single_engine_call():
    import asyncio
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    results = await asyncio.gather(*(
        submit(app, settings, selection["selection_ref"]) for _ in range(3)
    ))
    assert sorted(res.status_code for res in results) == [202, 503, 503]
    assert len(engine.calls) == 1
    assert len(list(db.execute("SELECT * FROM claw_web_xlsx_p01_requests"))) == 1
    db.close()


@pytest.mark.asyncio
async def test_exact_original_digest_drift_never_issues_new_engine_request():
    from dataclasses import replace
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    doc = original["document_id"]
    row = meta.rows[doc]
    meta.rows[doc] = replace(
        row, object_key=row.object_key.replace(original["source_sha256"], "f" * 64),
    )
    resp = await submit(app, settings, selection["selection_ref"])
    assert resp.status_code == 404
    assert engine.calls == []
    assert list(db.execute("SELECT * FROM claw_web_xlsx_p01_requests")) == []
    db.close()


@pytest.mark.asyncio
async def test_missing_030_migration_fails_before_engine_dispatch():
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    db.execute("DROP TABLE claw_web_xlsx_p01_requests")
    result = await submit(app, settings, selection["selection_ref"])
    assert result.status_code == 503
    assert engine.calls == []
    db.close()


@pytest.mark.asyncio
async def test_pause_response_window_cannot_outlast_source_selection():
    app, settings, meta, r2, db, history, engine = harness()
    original, selection = await prepare(app, settings)
    class LongEngine:
        async def start_pause(self, req):
            body = projected_pause(req)
            body["tool"]["approval_pause"]["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            return body
    app.state.web_xlsx_p01_pause_client = LongEngine()
    response = await submit(app, settings, selection["selection_ref"])
    assert response.status_code == 409
    row = db.execute("SELECT status FROM claw_web_xlsx_p01_requests").fetchone()
    assert row["status"] == "dispatching"
    db.close()
