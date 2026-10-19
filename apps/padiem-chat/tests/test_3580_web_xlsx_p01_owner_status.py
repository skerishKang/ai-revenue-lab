"""#3580: browser-visible P01 status is strictly authenticated server D1 truth."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_3580_web_xlsx_p01_owner_decision import ready, setup_pause, decide
from test_3580_web_xlsx_p01_request import prepare
from test_3580_web_xlsx_sources import request, OWNER, FOREIGN

PATH = "/api/claw/office/web-selections/{}/p01-status"


async def status(app, settings, selection_ref, *, owner=OWNER):
    return await request(
        app, settings, method="GET", owner=owner,
        path=PATH.format(selection_ref),
    )


@pytest.mark.asyncio
async def test_selected_without_engine_pause_is_never_actionable():
    app, settings, meta, r2, db, history, engine = ready()
    original, selected = await prepare(app, settings)
    result = await status(app, settings, selected["selection_ref"])
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "not_requested"
    assert data["owner_decision_enabled"] is False
    assert data["document_id"] == original["document_id"]
    assert data["source_sha256"] == original["source_sha256"]
    assert data["processing_started"] is False
    assert data["workcopy_created"] is False
    assert not any(x in data for x in (
        "pause_id", "continuation_ref", "engine_run_id", "authority_ref",
        "evidence_ref", "tool_arguments", "grant", "credential", "run_id",
    ))
    db.close()


@pytest.mark.asyncio
async def test_real_owner_waiting_pause_is_actionable_with_valid_run_only():
    app, settings, meta, r2, db, history, engine = ready()
    original, selected = await setup_pause(app, settings)
    result = await status(app, settings, selected["selection_ref"])
    assert result.status_code == 200, result.text
    assert "no-store" in result.headers["cache-control"]
    state = result.json()
    assert state["status"] == "waiting_p01"
    assert state["owner_decision_enabled"] is True
    assert state["source_sha256"] == original["source_sha256"]
    assert "continuation_ref" not in state and "pause_id" not in state

    history.foreign = True
    foreign_run = await status(app, settings, selected["selection_ref"])
    assert foreign_run.status_code == 200
    assert foreign_run.json()["status"] == "manual_review"
    assert foreign_run.json()["owner_decision_enabled"] is False
    history.foreign = False

    app.state.web_xlsx_p01_owner_decision_client = None
    disabled = await status(app, settings, selected["selection_ref"])
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "waiting_p01"
    assert disabled.json()["owner_decision_enabled"] is False
    db.close()


@pytest.mark.asyncio
async def test_foreign_or_anonymous_cannot_read_pause_or_decision():
    app, settings, meta, r2, db, history, engine = ready()
    original, selected = await setup_pause(app, settings)
    ref = selected["selection_ref"]
    assert (await status(app, settings, ref, owner=None)).status_code == 401
    assert (await status(app, settings, ref, owner=FOREIGN)).status_code == 404
    assert (await status(app, settings, "sel_" + "a"*32)).status_code == 404
    db.close()


@pytest.mark.asyncio
async def test_durable_owner_receipt_after_approve_or_deny_survives_refresh():
    for decision, expected in (("approve", "confirmed"), ("deny", "denied")):
        app, settings, meta, r2, db, history, client = ready()
        original, selected = await setup_pause(app, settings)
        client.status = expected
        posted = await decide(app, settings, selected, decision=decision)
        assert posted.status_code == 200, posted.text
        readback = await status(app, settings, selected["selection_ref"])
        assert readback.status_code == 200
        assert readback.json()["status"] == expected
        assert readback.json()["owner_decision_enabled"] is False
        assert len(client.calls) == 1
        assert (await status(app, settings, selected["selection_ref"])).json()["status"] == expected
        assert len(client.calls) == 1
        db.close()


@pytest.mark.asyncio
async def test_uncertain_pause_and_decision_are_never_reenabled():
    app, settings, meta, r2, db, history, client = ready()
    original, selected = await setup_pause(app, settings)
    client.raise_ = True
    failed = await decide(app, settings, selected)
    assert failed.status_code == 503
    stage = await status(app, settings, selected["selection_ref"])
    assert stage.status_code == 200
    assert stage.json()["status"] == "decision_unknown"
    assert stage.json()["owner_decision_enabled"] is False
    db.close()


@pytest.mark.asyncio
async def test_expired_or_corrupt_source_never_enables_owner_buttons():
    for change in ("expiry", "source_sha", "pause_expiry", "request_unknown", "deleted_original"):
        app, settings, meta, r2, db, history, engine = ready()
        original, selected = await setup_pause(app, settings)
        if change == "expiry":
            db.execute("UPDATE claw_web_xlsx_selections SET expires_at='2000-01-01T00:00:00+00:00'")
        elif change == "source_sha":
            db.execute("UPDATE claw_web_xlsx_p01_requests SET source_sha256=?", ("f"*64,))
        elif change == "pause_expiry":
            db.execute("UPDATE claw_web_xlsx_p01_requests SET pause_expires_at='2000-01-01T00:00:00+00:00'")
        elif change == "request_unknown":
            db.execute("UPDATE claw_web_xlsx_p01_requests SET status='dispatching'")
        else:
            meta.rows.pop(original["document_id"])
        view = await status(app, settings, selected["selection_ref"])
        if change == "source_sha":
            assert view.status_code == 503
        else:
            assert view.status_code == 200
            assert view.json()["status"] in (
                "expired", "request_unknown", "manual_review",
            )
            assert view.json()["owner_decision_enabled"] is False
        db.close()


@pytest.mark.asyncio
async def test_missing_receipts_schema_or_status_store_fails_closed():
    app, settings, meta, r2, db, history, engine = ready()
    original, selected = await setup_pause(app, settings)
    app.state.web_xlsx_p01_owner_decision_store = None
    assert (await status(app, settings, selected["selection_ref"])).status_code == 503
    db.close()


@pytest.mark.asyncio
async def test_corrupt_decision_receipt_never_mints_a_new_approval_button():
    for column, value in (
        ("user_id", "foreign_owner"),
        ("workspace_id", "owner:foreign"),
        ("selection_ref", "sel_" + "f"*32),
        ("source_sha256", "f"*64),
        ("pause_id", "pause:" + "f"*32),
    ):
        app, settings, meta, r2, db, history, client = ready()
        original, selected = await setup_pause(app, settings)
        client.raise_ = True
        assert (await decide(app, settings, selected)).status_code == 503
        db.execute(
            f"UPDATE claw_web_xlsx_p01_decision_receipts SET {column}=?",
            (value,),
        )
        state = await status(app, settings, selected["selection_ref"])
        assert state.status_code == 200, (column, state.text)
        assert state.json()["status"] == "manual_review", (column, state.text)
        assert state.json()["owner_decision_enabled"] is False
        db.close()
