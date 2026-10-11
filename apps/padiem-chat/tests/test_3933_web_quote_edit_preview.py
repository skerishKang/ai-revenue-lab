"""Signed-in WEB-FIRST quote edit plan preview (read-only, no write/PDF)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_3580_web_xlsx_selection_routes as selections_fixture
from test_3580_web_xlsx_approved_copy_wire import enable_real_copy
from test_3580_web_xlsx_p01_owner_decision import ready, setup_pause, decide
from test_3580_web_xlsx_sources import request, OWNER, FOREIGN
from test_3933_web_quote_xlsx_editor import quote_fixture

PATH = "/api/claw/office/web-selections/{}/quote-edit/preview"
CHANGES = {"school_name": "Gwangju University", "supply_amount": 99_200_000}


async def preview(app, settings, ref, *, owner=OWNER, data=None):
    return await request(
        app, settings, owner=owner, method="POST",
        path=PATH.format(ref), payload=CHANGES if data is None else data,
    )


@pytest.mark.asyncio
async def test_real_approved_quote_preview_computes_exact_edit_digest_without_any_write(monkeypatch):
    monkeypatch.setattr(selections_fixture, "workbook", quote_fixture)
    app, settings, metadata, r2, db, history, engine = ready()
    src, selection = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    ref = selection["selection_ref"]
    assert (await preview(app, settings, ref)).status_code == 404
    engine.status = "confirmed"
    engine.verified_source_sha256 = src["source_sha256"]
    owner_ok = await decide(app, settings, selection, decision="approve")
    assert owner_ok.status_code == 200
    assert owner_ok.json()["workcopy_created"] is True
    keys_before = set(r2.objects)
    snap = dict(r2.objects)

    response = await preview(app, settings, ref)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["contract_version"] == "claw-web-xlsx-quote-edit-preview.v1"
    assert out["school_name"] == CHANGES["school_name"]
    assert out["supply_amount"] == 99_200_000
    assert out["vat_amount"] == 9_920_000
    assert out["total_amount"] == 109_120_000
    assert out["original_workcopy_sha256"] == src["source_sha256"]
    assert out["revision_preview_sha256"] != src["source_sha256"]
    canonical = json.dumps({
        "school_name": CHANGES["school_name"],
        "supply_amount": CHANGES["supply_amount"],
        "output_formats": ["xlsx"], "overwrite_original": False,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert out["edit_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert out["preview_only"] is True
    assert out["write_approved"] is False
    assert out["requires_independent_p01_write"] is True
    assert out["revised_xlsx_created"] is False
    assert out["pdf_exported"] is False and out["pdf_unsupported"] is True
    assert "no-store" in response.headers["cache-control"]
    assert (await preview(app, settings, ref, owner=FOREIGN)).status_code == 404
    assert (await preview(app, settings, ref, owner=None)).status_code == 401

    again = await preview(app, settings, ref)
    assert again.status_code == 200
    assert again.json()["edit_sha256"] == out["edit_sha256"]
    assert again.json()["revision_preview_sha256"] == out["revision_preview_sha256"]
    assert set(r2.objects) == keys_before
    assert r2.objects == snap
    assert len(metadata.rows) == 2
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"school_name": "School", "supply_amount": 100, "drive_write": True},
    {"school_name": "School", "supply_amount": True},
    {"school_name": "=SUM(A1)", "supply_amount": 100},
    {"school_name": "Test\nInjection", "supply_amount": 100},
    {"school_name": "School", "supply_amount": 91},
    {"school_name": "School", "supply_amount": 1_000_000_000_000},
    {"school_name": "School", "supply_amount": "100"},
])
async def test_bad_preview_never_mutates_source(monkeypatch, bad):
    monkeypatch.setattr(selections_fixture, "workbook", quote_fixture)
    app, settings, metadata, r2, db, history, engine = ready()
    source, sel = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    engine.status = "confirmed"
    engine.verified_source_sha256 = source["source_sha256"]
    assert (await decide(app, settings, sel, decision="approve")).status_code == 200
    before = dict(r2.objects)
    result = await preview(app, settings, sel["selection_ref"], data=bad)
    assert result.status_code in (400, 413, 422), result.text
    assert before == r2.objects
    assert len(metadata.rows) == 2
    db.close()


@pytest.mark.asyncio
async def test_denial_intent_only_and_unsupported_workbook_fail_closed():
    for case in ("denied", "intent_only", "unsupported"):
        app, settings, metadata, r2, db, history, engine = ready()
        src, sel = await setup_pause(app, settings)
        if case == "unsupported":
            enable_real_copy(app, metadata)
            engine.status = "confirmed"
            engine.verified_source_sha256 = src["source_sha256"]
            assert (await decide(app, settings, sel, decision="approve")).status_code == 200
            expected = 422
        elif case == "intent_only":
            engine.status = "confirmed"
            assert (await decide(app, settings, sel, decision="approve")).status_code == 200
            expected = 404
        else:
            assert (await decide(app, settings, sel, decision="deny")).status_code == 200
            expected = 404
        before = dict(r2.objects)
        result = await preview(app, settings, sel["selection_ref"])
        assert result.status_code == expected, result.text
        assert r2.objects == before
        db.close()


@pytest.mark.asyncio
async def test_tampered_approved_copy_cannot_be_previewed(monkeypatch):
    monkeypatch.setattr(selections_fixture, "workbook", quote_fixture)
    app, settings, metadata, r2, db, history, engine = ready()
    src, sel = await setup_pause(app, settings)
    enable_real_copy(app, metadata)
    engine.status = "confirmed"
    engine.verified_source_sha256 = src["source_sha256"]
    approved = await decide(app, settings, sel, decision="approve")
    copy_key = metadata.rows[approved.json()["workcopy_document_id"]].object_key
    r2.objects[copy_key] = b"changed"
    result = await preview(app, settings, sel["selection_ref"])
    assert result.status_code == 503
    db.close()
