"""공용 시험 준비 — 웹 견적 쓰기 게이트(합성 Engine 증명) 픽스처.

test_3933_web_quote_write_gate가 들고 있던 준비를 여기 옮겨
시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support import web_xlsx_selection_routes as selection_fixture
from _support.web_xlsx_p01_owner_decision import ready, setup_pause, decide
from _support.web_xlsx_sources import request, OWNER, FOREIGN
from _support.web_xlsx_selection_routes import RealSQLiteD1
from _support.web_quote_xlsx_editor import quote_fixture
from app.claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore
from test_3580_web_xlsx_approved_copy_wire import enable_real_copy

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
        Path(__file__).resolve().parents[2] / "migrations" /
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
