"""#3580: owner-scoped P01 request reservation; no fake browser approval."""
from __future__ import annotations

import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_selection_routes import setup, upload, selected, RealSQLiteD1
from test_3580_web_xlsx_sources import request, OWNER, FOREIGN
from app.claw_web_xlsx_p01_request import (
    D1WebXlsxP01RequestStore, TrustedWebXlsxP01Request,
    WebXlsxP01RequestError, dispatch_owner_web_xlsx_p01,
    parse_engine_pause,
)

PATH = "/api/claw/office/web-selections/{}/request-p01"
NOW = datetime.now(timezone.utc)


class OwnerRunHistory:
    def __init__(self, workspace):
        self.workspace = workspace
        self.foreign = False
        self.calls = []

    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []

    async def get_claw_run(self, owner, run):
        self.calls.append((owner, run))
        if owner != OWNER or run != "run_web_3580_actual":
            return None
        return {
            "run_id": run, "workspace_id": (
                "owner:foreign" if self.foreign else self.workspace),
            "status": "running", "conversation_id": "conv_real_web",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def projected_pause(source: TrustedWebXlsxP01Request):
    expiry = min(
        datetime.now(timezone.utc) + timedelta(minutes=10),
        datetime.fromisoformat(source.selection_expires_at),
    ).isoformat()
    return {
        "orchestration": {
            "app_id": "padiem-web-xlsx-p01",
            "execution": {"metadata": {
                "status": "paused",
                "tool_events": [{
                    "tool_id": "workspace.xlsx.confirm_original_read",
                    "status": "policy_blocked",
                }],
            }},
            "approval_pause": {
                "status": "paused",
                "run_id": "bridge_run_8f3a", "tool_id": "workspace.xlsx.confirm_original_read",
                "requirement": "user_confirmation",
                "approval_scope": ["workspace.xlsx.original.read.intent"],
                "trace_id": "web_xlsx_" + source.selection_ref,
                "continuation_id": "pause:" + "b" * 32,
                "expires_at": expiry,
            },
            "continuation_ref": "cont_" + "c" * 32,
        },
    }


class CapturingEngine:
    def __init__(self, *, mode="good"):
        self.mode = mode
        self.calls = []

    async def start_pause(self, req):
        assert isinstance(req, TrustedWebXlsxP01Request)
        self.calls.append(req)
        if self.mode == "raised":
            raise RuntimeError("uncertain internal Engine call")
        body = projected_pause(req)
        if self.mode == "fake_approved":
            body["orchestration"]["execution"]["metadata"]["status"] = "completed"
        elif self.mode == "wrong_source":
            body["orchestration"]["approval_pause"]["trace_id"] = "not_this_source"
        return body


def harness():
    app, settings, meta, r2, storage, selections_db = setup()
    selections_db.executescript((
        Path(__file__).resolve().parents[1] / "migrations"
        / "030_claw_web_xlsx_p01_requests.sql").read_text(encoding="utf-8"))
    app.state.web_xlsx_p01_request_store = D1WebXlsxP01RequestStore(
        RealSQLiteD1(selections_db))
    history = OwnerRunHistory("owner:" + OWNER)
    app.state.history_store = history
    engine = CapturingEngine()
    app.state.web_xlsx_p01_pause_client = engine
    return app, settings, meta, r2, selections_db, history, engine


async def prepare(app, settings):
    original = await upload(app, settings)
    response = await selected(app, settings, original["document_id"])
    assert response.status_code == 201
    return original, response.json()["selection"]


async def submit(app, settings, selection_ref, owner=OWNER, payload=None):
    return await request(
        app, settings, path=PATH.format(selection_ref), method="POST",
        owner=owner, payload=payload if payload is not None
        else {"run_id": "run_web_3580_actual"},
    )


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
            body["orchestration"]["approval_pause"]["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            return body
    app.state.web_xlsx_p01_pause_client = LongEngine()
    response = await submit(app, settings, selection["selection_ref"])
    assert response.status_code == 409
    row = db.execute("SELECT status FROM claw_web_xlsx_p01_requests").fetchone()
    assert row["status"] == "dispatching"
    db.close()
