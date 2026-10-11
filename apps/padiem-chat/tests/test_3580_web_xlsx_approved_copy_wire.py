"""WEB-FIRST #3580: authenticated owner approval -> real private R2 workcopy.

Only synthetic XLSX and test Engine binding. Production must explicitly opt in;
this does not claim an operational live P01/Engine release.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_p01_owner_decision import ready, setup_pause, decide
from test_3580_web_xlsx_p01_owner_status import status
from test_3580_web_xlsx_sources import OWNER, FOREIGN, request


def enable_real_copy(app, metadata):
    app.state.web_xlsx_p01_workcopy_after_grant_enabled = True

    async def scoped_rows(*, tenant_id, key_prefix, now, limit=40):
        return [
            item for item in metadata.rows.values()
            if item.tenant_id == tenant_id
            and item.object_key.startswith(key_prefix)
            and item.expires_at > now
        ][:limit]

    metadata.list_web_xlsx = scoped_rows


@pytest.mark.asyncio
async def test_real_owner_signed_approve_creates_distinct_r2_workcopy_once_and_get_readback():
    app, settings, metadata, r2, db, history, engine = ready()
    original, selection = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    engine.status = "confirmed"
    engine.verified_source_sha256 = original["source_sha256"]
    source_key = metadata.rows[original["document_id"]].object_key
    source_bytes = r2.objects[source_key]

    approved = await decide(app, settings, selection, decision="approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "confirmed"
    assert approved.json()["workcopy_created"] is True
    copy_id = approved.json()["workcopy_document_id"]
    assert copy_id != original["document_id"]
    assert len(r2.objects) == 2
    assert r2.objects[source_key] == source_bytes
    assert metadata.rows[copy_id].object_key != source_key
    assert r2.objects[metadata.rows[copy_id].object_key] == source_bytes
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_p01_decision_receipts"
    ).fetchone()[0] == "confirmed"

    refreshed = await status(app, settings, selection["selection_ref"])
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["workcopy_created"] is True
    assert refreshed.json()["workcopy_document_id"] == copy_id
    assert "run_id" not in refreshed.json()
    assert "grant" not in str(refreshed.json())

    # The workcopy is not silently exposed as an original upload.
    originals = await request(app, settings)
    assert all(row["document_id"] != copy_id for row in originals.json()["files"])
    assert (await status(app, settings, selection["selection_ref"], owner=FOREIGN)).status_code == 404
    second = await decide(app, settings, selection, decision="approve")
    assert second.status_code in (409, 503)
    assert len(engine.calls) == 1
    assert len(metadata.rows) == len(r2.objects) == 2
    db.close()


@pytest.mark.asyncio
async def test_confirmed_workcopy_exposes_only_the_verified_owner_work_conversation():
    app, settings, metadata, r2, db, history, engine = ready()
    original, selection = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    engine.status = "confirmed"
    engine.verified_source_sha256 = original["source_sha256"]
    chat = "chat_" + "a" * 32

    async def owner_run(owner, run):
        if owner != OWNER or run != "run_web_3580_actual":
            return None
        return {
            "run_id": run, "workspace_id": history.workspace,
            "status": "running", "conversation_id": chat,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def verified_owner(user_id, conversation_id):
        return user_id == OWNER and conversation_id == chat

    before = await status(app, settings, selection["selection_ref"])
    assert before.json()["workcopy_created"] is False
    assert before.json()["work_conversation"] is None

    approved = await decide(app, settings, selection, decision="approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["workcopy_created"] is True

    # A workcopy alone is not a conversation handle: the owner run and the
    # conversation ownership must both verify independently.
    unverified = await status(app, settings, selection["selection_ref"])
    assert unverified.json()["workcopy_created"] is True
    assert unverified.json()["work_conversation"] is None

    history.get_claw_run = owner_run
    history.verify_owner_conversation_artifacts = verified_owner
    refreshed = await status(app, settings, selection["selection_ref"])
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["work_conversation"] == {"conversation_id": chat}
    # Still an owner status projection: no run id, pause or grant evidence.
    assert "run_id" not in refreshed.json()
    assert not any(item in refreshed.json() for item in (
        "pause_id", "continuation_ref", "engine_run_id", "grant", "credential",
    ))

    # A foreign/non-owned conversation, a malformed id or a foreign workspace
    # run never becomes a navigation handle.
    async def foreign_owner(user_id, conversation_id):
        return False

    history.verify_owner_conversation_artifacts = foreign_owner
    assert (await status(app, settings, selection["selection_ref"])).json()[
        "work_conversation"] is None
    history.verify_owner_conversation_artifacts = verified_owner

    async def malformed_run(owner, run):
        row = await owner_run(owner, run)
        if row is not None:
            row["conversation_id"] = "conv_real_web"
        return row

    history.get_claw_run = malformed_run
    assert (await status(app, settings, selection["selection_ref"])).json()[
        "work_conversation"] is None

    async def foreign_workspace_run(owner, run):
        row = await owner_run(owner, run)
        if row is not None:
            row["workspace_id"] = "owner:foreign"
        return row

    history.get_claw_run = foreign_workspace_run
    assert (await status(app, settings, selection["selection_ref"])).json()[
        "work_conversation"] is None

    history.get_claw_run = owner_run
    assert (await status(app, settings, selection["selection_ref"], owner=FOREIGN)).status_code == 404
    db.close()


@pytest.mark.asyncio
async def test_denied_has_no_workcopy_even_when_operator_flag_enabled():
    app, settings, metadata, r2, db, history, engine = ready()
    original, selection = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    denied = await decide(app, settings, selection, decision="deny")
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"
    assert denied.json()["workcopy_created"] is False
    assert len(r2.objects) == 1
    assert (await status(app, settings, selection["selection_ref"])).json()["workcopy_created"] is False
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("spoof_sha", [None, "f" * 64])
async def test_confirmed_engine_missing_or_wrong_source_scope_must_not_read_r2(spoof_sha):
    app, settings, metadata, r2, db, history, engine = ready()
    original, selection = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    engine.status = "confirmed"
    if spoof_sha:
        engine.verified_source_sha256 = spoof_sha
    source_key = metadata.rows[original["document_id"]].object_key
    response = await decide(app, settings, selection, decision="approve")
    assert response.status_code in (409, 503), response.text
    assert len(r2.objects) == 1 and source_key in r2.objects
    assert (await status(app, settings, selection["selection_ref"])).json()["workcopy_created"] is False
    # A consumed decision may not be auto-replayed.
    assert len(engine.calls) == 1
    assert (await decide(app, settings, selection, decision="approve")).status_code in (409, 503)
    assert len(engine.calls) == 1
    db.close()


@pytest.mark.asyncio
async def test_r2_byte_tamper_after_engine_confirmation_does_not_create_workcopy():
    app, settings, metadata, r2, db, history, engine = ready()
    original, selection = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    engine.status = "confirmed"
    engine.verified_source_sha256 = original["source_sha256"]
    source_key = metadata.rows[original["document_id"]].object_key
    r2.objects[source_key] = b"tampered"
    response = await decide(app, settings, selection, decision="approve")
    assert response.status_code == 503, response.text
    assert len(r2.objects) == 1
    assert (await status(app, settings, selection["selection_ref"])).json()["workcopy_created"] is False
    db.close()
