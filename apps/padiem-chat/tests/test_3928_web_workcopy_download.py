"""#3928/#3932: exact authenticated read-only original workcopy download.

This does not authorize XLSX revisions or produce an Office-fidelity PDF.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_approved_copy_wire import enable_real_copy
from test_3580_web_xlsx_p01_owner_decision import ready, setup_pause, decide
from test_3580_web_xlsx_sources import request, OWNER, FOREIGN

URL = "/api/claw/office/web-selections/{}/workcopy/download"


async def get(app, settings, ref, owner=OWNER):
    return await request(
        app, settings, owner=owner,
        method="GET", path=URL.format(ref),
    )


@pytest.mark.asyncio
async def test_approved_workcopy_download_returns_actual_verified_r2_bytes_to_owner_only():
    app, settings, db_meta, r2, db, history, engine = ready()
    source, selection = await setup_pause(app, settings)
    enable_real_copy(app, db_meta)
    engine.status = "confirmed"
    engine.verified_source_sha256 = source["source_sha256"]
    document_id = source["document_id"]
    original_bytes = r2.objects[db_meta.rows[document_id].object_key]
    ref = selection["selection_ref"]
    assert (await get(app, settings, ref)).status_code == 404
    approved = await decide(app, settings, selection, decision="approve")
    assert approved.status_code == 200 and approved.json()["workcopy_created"] is True
    authorized = await get(app, settings, ref)
    assert authorized.status_code == 200, authorized.text[:200] if authorized.status_code != 200 else ""
    assert authorized.content == original_bytes
    assert "spreadsheetml.sheet" in authorized.headers["content-type"]
    assert "attachment" in authorized.headers["content-disposition"]
    assert "no-store" in authorized.headers["cache-control"]
    assert authorized.headers["cross-origin-resource-policy"] == "same-origin"
    assert len(r2.objects) == 2
    assert (await get(app, settings, ref, owner=None)).status_code == 401
    assert (await get(app, settings, ref, owner=FOREIGN)).status_code == 404
    assert (await get(app, settings, "sel_" + "f" * 32)).status_code == 404
    db.close()


@pytest.mark.asyncio
async def test_denied_or_intent_only_cannot_download_processing_copy():
    for action in ("deny", "approve_without_copy"):
        app, settings, meta, r2, db, history, engine = ready()
        src, selection = await setup_pause(app, settings)
        ref = selection["selection_ref"]
        if action == "deny":
            assert (await decide(app, settings, selection, decision="deny")).status_code == 200
        else:
            engine.status = "confirmed"
            assert (await decide(app, settings, selection, decision="approve")).status_code == 200
        assert (await get(app, settings, ref)).status_code == 404
        assert len(r2.objects) == 1
        db.close()


@pytest.mark.asyncio
async def test_tampered_r2_workcopy_never_leaks_bytes_as_authentic_download():
    app, settings, meta, r2, db, history, engine = ready()
    src, selection = await setup_pause(app, settings)
    enable_real_copy(app, meta)
    engine.status = "confirmed"
    engine.verified_source_sha256 = src["source_sha256"]
    authorized = await decide(app, settings, selection, decision="approve")
    assert authorized.status_code == 200
    copy_id = authorized.json()["workcopy_document_id"]
    key = meta.rows[copy_id].object_key
    r2.objects[key] = b"corrupt"
    response = await get(app, settings, selection["selection_ref"])
    assert response.status_code == 503
    assert b"corrupt" not in response.content
    db.close()
