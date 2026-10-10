"""#3580: browser P01 start must mint the owner run only on trusted B62."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_p01_owner_decision import ready
from test_3580_web_xlsx_p01_request import prepare
from test_3580_web_xlsx_sources import request, OWNER, FOREIGN

PATH = "/api/claw/office/web-selections/{}/start-p01"
STATUS = "/api/claw/office/web-selections/{}/p01-status"


def install_owner_run(history):
    history.started = []
    async def create_web_xlsx_p01_run(*, user_id, workspace_id, filename):
        history.started.append((user_id, workspace_id, filename))
        return "run_web_3580_actual"
    history.create_web_xlsx_p01_run = create_web_xlsx_p01_run


async def start(app, settings, selection_ref, *, owner=OWNER, payload=None):
    return await request(
        app, settings, method="POST", owner=owner,
        path=PATH.format(selection_ref), payload={} if payload is None else payload,
    )


async def status(app, settings, ref, owner=OWNER):
    return await request(app, settings, method="GET", owner=owner, path=STATUS.format(ref))


@pytest.mark.asyncio
async def test_browser_start_is_owner_minted_and_one_shot_with_real_d1():
    app, settings, meta, r2, db, history, decision = ready()
    install_owner_run(history)
    original, selected = await prepare(app, settings)
    ref = selected["selection_ref"]
    first = await status(app, settings, ref)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "not_requested"
    assert first.json()["owner_request_enabled"] is True
    assert first.json()["owner_decision_enabled"] is False

    result = await start(app, settings, ref)
    assert result.status_code == 202, result.text
    assert result.json()["status"] == "waiting_p01"
    assert result.json()["processing_started"] is False
    assert result.json()["workcopy_created"] is False
    assert "run_id" not in result.json()
    assert history.started == [(OWNER, "owner:" + OWNER, original["filename"])]
    assert db.execute("SELECT COUNT(*) FROM claw_web_xlsx_p01_requests").fetchone()[0] == 1
    waiting = await status(app, settings, ref)
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "waiting_p01"
    assert waiting.json()["owner_request_enabled"] is False
    assert waiting.json()["owner_decision_enabled"] is True

    replay = await start(app, settings, ref)
    assert replay.status_code == 409
    assert len(history.started) == 1
    assert db.execute("SELECT COUNT(*) FROM claw_web_xlsx_p01_requests").fetchone()[0] == 1
    db.close()


@pytest.mark.asyncio
async def test_browser_start_foreign_and_untrusted_body_never_mint_run():
    app, settings, meta, r2, db, history, decision = ready()
    install_owner_run(history)
    original, selected = await prepare(app, settings)
    ref = selected["selection_ref"]
    assert (await start(app, settings, ref, owner=None)).status_code == 401
    assert (await start(app, settings, ref, owner=FOREIGN)).status_code == 404
    for extra in (
        {"run_id": "browser_fake"}, {"decision": "approve"},
        {"owner_id": OWNER}, {"tool_arguments": {"read": True}},
        {"conversation_id": "client_injected"}, {"source_sha256": original["source_sha256"]},
    ):
        assert (await start(app, settings, ref, payload=extra)).status_code in (400, 413)
    assert not history.started
    assert db.execute("SELECT COUNT(*) FROM claw_web_xlsx_p01_requests").fetchone()[0] == 0
    db.close()


@pytest.mark.asyncio
async def test_missing_schema_expiry_and_original_drift_do_not_mint_run():
    for problem in ("schema", "expiry", "drift"):
        app, settings, meta, r2, db, history, decision = ready()
        install_owner_run(history)
        original, selected = await prepare(app, settings)
        ref = selected["selection_ref"]
        if problem == "schema":
            db.execute("DROP TABLE claw_web_xlsx_p01_requests")
        elif problem == "expiry":
            db.execute(
                "UPDATE claw_web_xlsx_selections SET expires_at='2000-01-01T00:00:00+00:00'"
            )
        else:
            row = meta.rows[original["document_id"]]
            meta.rows[original["document_id"]] = replace(
                row, object_key=row.object_key.replace(original["source_sha256"], "f" * 64),
            )
        result = await start(app, settings, ref)
        assert result.status_code in (404, 503), (problem, result.text)
        assert history.started == []
        db.close()


@pytest.mark.asyncio
async def test_uncertain_engine_dispatch_stays_reserved_no_retry():
    app, settings, meta, r2, db, history, decision = ready()
    install_owner_run(history)
    original, selected = await prepare(app, settings)
    engine = app.state.web_xlsx_p01_pause_client
    engine.mode = "raised"
    ref = selected["selection_ref"]
    result = await start(app, settings, ref)
    assert result.status_code == 503
    assert db.execute(
        "SELECT status FROM claw_web_xlsx_p01_requests"
    ).fetchone()[0] == "dispatching"
    assert (await status(app, settings, ref)).json()["status"] == "request_unknown"
    assert (await start(app, settings, ref)).status_code == 409
    assert len(history.started) == 1
    assert len(engine.calls) == 1
    db.close()

@pytest.mark.asyncio
async def test_actual_history_store_mints_owner_conversation_and_run_without_fake_message():
    import sqlite3
    from test_3580_web_xlsx_selection_routes import RealSQLiteD1
    from app.history import D1HistoryStore
    folder = Path(__file__).resolve().parents[1] / "migrations"
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for filename in (
        "001_auth_history.sql", "002_projects.sql", "009_claw_run_history.sql",
        "014_claw_run_history_conversation.sql",
        "015_claw_run_history_workspace.sql",
    ):
        conn.executescript((folder / filename).read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (id,auth_provider,provider_subject,email,"
        "display_name,picture_url,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (OWNER, "google", "owner@example", "owner@example.test", "Owner", "", now, now),
    )
    history = D1HistoryStore(RealSQLiteD1(conn))
    name = "원본-" + "가" * 120 + ".xlsx"
    run_id = await history.create_web_xlsx_p01_run(
        user_id=OWNER, workspace_id="owner:" + OWNER, filename=name,
    )
    row = await history.get_claw_run(OWNER, run_id)
    assert row["run_id"] == run_id
    assert row["status"] == "running"
    assert row["workspace_id"] == "owner:" + OWNER
    conv = await history.get_conversation(OWNER, row["conversation_id"])
    assert conv is not None
    assert len(conv["title"]) <= 80
    assert conv["messages"] == []
    assert await history.get_claw_run(FOREIGN, run_id) is None
    assert await history.get_conversation(FOREIGN, row["conversation_id"]) is None
    conn.close()
