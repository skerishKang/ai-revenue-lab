"""#3933 bounded separate Engine WRITE confirmation -> actual private XLSX revision.

Synthetic in-memory Engine proof only, NOT real Production Core P01 WRITE.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_3580_web_xlsx_selection_routes as selection_fixture
from test_3580_web_xlsx_approved_copy_wire import enable_real_copy
from test_3580_web_xlsx_p01_owner_decision import ready, setup_pause, decide
from test_3580_web_xlsx_sources import request, OWNER, FOREIGN
from test_3580_web_xlsx_selection_routes import RealSQLiteD1
from test_3933_web_quote_xlsx_editor import quote_fixture
from app.claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore

PREFIX = "/api/claw/office/web-selections/{}/quote-edit/"
VALUES = {"school_name": "Gwangju University", "supply_amount": 99_200_000}


class SyntheticIndependentCoreWriteProof:
    def __init__(self, db, mode="valid"):
        self.db, self.mode = db, mode
        self.calls = []

    async def confirm_exact_write(self, row):
        self.calls.append(row.copy())
        durable = self.db.execute(
            "SELECT state,edit_sha256,user_id,workspace_id,run_id,"
            "source_sha256,workcopy_document_id "
            "FROM claw_web_xlsx_quote_edit_receipts WHERE selection_ref=?",
            (row["selection_ref"],),
        ).fetchone()
        assert durable and durable["state"] == "dispatching"
        assert durable["edit_sha256"] == row["edit_sha256"]
        assert durable["user_id"] == row["user_id"]
        if self.mode == "exception":
            raise RuntimeError("synthetic Engine timeout unknown")
        proof = {
            "ok": True, "core_tool_completed": True,
            "operation": "xlsx.quote.revise_workcopy",
            "owner_id": row["owner_id"],
            "workspace_id": row["workspace_id"],
            "run_id": row["run_id"],
            "source_document_id": row["source_document_id"],
            "source_sha256": row["source_sha256"],
            "workcopy_document_id": row["workcopy_document_id"],
            "workcopy_sha256": row["source_sha256"],
            "edit_sha256": row["edit_sha256"], "pdf_exported": False,
        }
        if self.mode == "forged":
            proof["edit_sha256"] = "f" * 64
        if self.mode == "read_only":
            proof["operation"] = "read_for_workcopy"
        if self.mode == "not_core":
            proof["core_tool_completed"] = False
        return proof


async def api(app, settings, ref, suffix, *, method="GET", data=None, owner=OWNER):
    return await request(
        app, settings, owner=owner, method=method,
        path=PREFIX.format(ref) + suffix, payload=data,
    )


async def prepared(monkeypatch, mode="valid", enabled=True):
    monkeypatch.setattr(selection_fixture, "workbook", quote_fixture)
    app, settings, meta, r2, db, history, read_engine = ready()
    db.executescript((
        Path(__file__).resolve().parents[1] / "migrations" /
        "032_claw_web_xlsx_quote_edit_receipts.sql").read_text(encoding="utf-8"))
    app.state.web_xlsx_quote_write_store = D1WebQuoteWriteReceiptStore(RealSQLiteD1(db))
    app.state.web_xlsx_quote_write_client = SyntheticIndependentCoreWriteProof(db, mode)
    app.state.web_xlsx_quote_write_enabled = enabled
    src, sel = await setup_pause(app, settings)
    enable_real_copy(app, meta)
    read_engine.status = "confirmed"
    read_engine.verified_source_sha256 = src["source_sha256"]
    accepted = await decide(app, settings, sel, decision="approve")
    assert accepted.status_code == 200 and accepted.json()["workcopy_created"]
    before = dict(r2.objects)
    preview = await api(app, settings, sel["selection_ref"], "preview",
                        method="POST", data=VALUES)
    assert preview.status_code == 200, preview.text
    return app, settings, meta, r2, db, history, sel, src, before, preview.json()


@pytest.mark.asyncio
async def test_exact_engine_write_receipt_generates_original_preserving_distinct_revision(monkeypatch):
    app, settings, meta, r2, db, history, sel, src, before, preview = await prepared(monkeypatch)
    ref = sel["selection_ref"]
    payload = {**VALUES, "edit_sha256": preview["edit_sha256"]}
    assert (await api(app, settings, ref, "status")).status_code == 404
    written = await api(app, settings, ref, "commit", method="POST", data=payload)
    assert written.status_code == 201, written.text
    result = written.json()
    assert result["state"] == "confirmed"
    assert result["revised_xlsx_created"] is True
    assert result["pdf_exported"] is False
    assert result["original_overwritten"] is False
    assert result["revision_sha256"] == preview["revision_preview_sha256"]
    assert result["edit_sha256"] == preview["edit_sha256"]
    assert len(r2.objects) == 3
    assert all(r2.objects[k] == old for k, old in before.items())
    receipt = db.execute(
        "SELECT state,revision_document_id,revision_sha256,edit_sha256 "
        "FROM claw_web_xlsx_quote_edit_receipts WHERE selection_ref=?",
        (ref,),
    ).fetchone()
    assert receipt["state"] == "confirmed"
    assert receipt["revision_document_id"] == result["revision_document_id"]
    status = await api(app, settings, ref, "status")
    assert status.status_code == 200
    assert status.json()["revised_xlsx_created"] is True
    assert status.json()["revision_sha256"] == result["revision_sha256"]
    downloaded = await api(app, settings, ref, "download")
    assert downloaded.status_code == 200, downloaded.text
    assert hashlib.sha256(downloaded.content).hexdigest() == result["revision_sha256"]
    assert "attachment" in downloaded.headers["content-disposition"]
    assert "no-store" in downloaded.headers["cache-control"]
    assert (await api(app, settings, ref, "download", owner=FOREIGN)).status_code == 404
    assert (await api(app, settings, ref, "download", owner=None)).status_code == 401
    assert (await api(app, settings, ref, "commit", method="POST", data=payload)).status_code == 409
    assert len(app.state.web_xlsx_quote_write_client.calls) == 1
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["forged", "read_only", "not_core", "exception"])
async def test_unverified_engine_write_result_is_one_shot_and_never_saves(monkeypatch, mode):
    app, settings, meta, r2, db, history, sel, src, before, preview = await prepared(monkeypatch, mode)
    ref = sel["selection_ref"]
    payload = {**VALUES, "edit_sha256": preview["edit_sha256"]}
    blocked = await api(app, settings, ref, "commit", method="POST", data=payload)
    assert blocked.status_code in (409, 503), blocked.text
    assert r2.objects == before
    assert (await api(app, settings, ref, "status")).json()["state"] == "unknown"
    assert (await api(app, settings, ref, "download")).status_code == 404
    assert (await api(app, settings, ref, "commit", method="POST", data=payload)).status_code == 409
    assert len(app.state.web_xlsx_quote_write_client.calls) == 1
    db.close()


@pytest.mark.asyncio
async def test_disabled_write_never_reserves_or_calls_engine(monkeypatch):
    app, settings, meta, r2, db, history, sel, src, before, preview = await prepared(
        monkeypatch, enabled=False)
    result = await api(app, settings, sel["selection_ref"], "commit",
                       method="POST", data={**VALUES, "edit_sha256": preview["edit_sha256"]})
    assert result.status_code == 503
    assert len(app.state.web_xlsx_quote_write_client.calls) == 0
    assert list(db.execute("SELECT * FROM claw_web_xlsx_quote_edit_receipts")) == []
    assert r2.objects == before
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"school_name": "Gwangju University", "supply_amount": 99_200_000, "edit_sha256": "f"*64},
    {"school_name": "Gwangju University", "supply_amount": True, "edit_sha256": "a"*64},
    {"school_name": "Gwangju University", "supply_amount": 99_200_000, "edit_sha256": "x"*64},
    {"school_name": "Gwangju University", "supply_amount": 99_200_000, "edit_sha256": "a"*64, "grant": True},
])
async def test_browser_cannot_mint_exact_edit_grant(monkeypatch, invalid):
    app, settings, meta, r2, db, history, sel, src, before, preview = await prepared(monkeypatch)
    ref = sel["selection_ref"]
    result = await api(app, settings, ref, "commit", method="POST", data=invalid)
    assert result.status_code == 400
    assert not app.state.web_xlsx_quote_write_client.calls
    assert r2.objects == before
    db.close()


@pytest.mark.asyncio
async def test_revised_r2_mutation_refused_without_any_bytes_leak(monkeypatch):
    app, settings, meta, r2, db, history, sel, src, before, preview = await prepared(monkeypatch)
    ref = sel["selection_ref"]
    response = await api(app, settings, ref, "commit", method="POST",
                         data={**VALUES, "edit_sha256": preview["edit_sha256"]})
    assert response.status_code == 201
    revision_id = response.json()["revision_document_id"]
    key = meta.rows[revision_id].object_key
    r2.objects[key] = b"forged"
    downloaded = await api(app, settings, ref, "download")
    assert downloaded.status_code == 503
    assert b"forged" not in downloaded.content
    db.close()
