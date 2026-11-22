"""#8061 22차: shared setup for the web XLSX P01 owner-decision tests.

The owner-decision app (decision receipt store plus one-shot engine binding)
and the pause/decide request helpers are what eight test files share. The
selection/request layers below them stay in their own _support modules and
test hubs; this module only composes them.
"""
from __future__ import annotations

from pathlib import Path

from _support.web_xlsx_selection_routes import RealSQLiteD1
from _support.web_xlsx_sources import request, OWNER
from app.claw_web_xlsx_p01_owner_decision import D1WebXlsxP01OwnerDecisionStore
from test_3580_web_xlsx_p01_request import harness, prepare, submit

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
        result = {"ok": True, "status": self.status}
        if self.status == "confirmed" and getattr(self, "verified_source_sha256", None):
            result["verified_source_sha256"] = self.verified_source_sha256
        return result


def ready():
    app, settings, meta, r2, db, history, engine = harness()
    db.executescript((
        Path(__file__).resolve().parents[2] / "migrations" /
        "031_claw_web_xlsx_p01_decision_receipts.sql").read_text(encoding="utf-8"))
    # #3936 release column: a retry-safe Engine rejection must be able to
    # release the one-shot reservation (additive only).
    db.executescript((
        Path(__file__).resolve().parents[2] / "migrations" /
        "040_claw_web_xlsx_p01_decision_release.sql").read_text(encoding="utf-8"))
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
