"""#3580: owner-scoped P01 request 준비 — 다른 시험이 가져오던 헬퍼.

test_3580_web_xlsx_p01_request가 들고 있던 준비(harness·prepare·submit·
projected_pause)를 여기 옮겨 시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from _support.web_xlsx_selection_routes import setup, upload, selected, RealSQLiteD1
from _support.web_xlsx_sources import request, OWNER
from app.claw_web_xlsx_p01_request import (
    D1WebXlsxP01RequestStore, TrustedWebXlsxP01Request,
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
        "ok": True,
        "tool": {
            "contract_version": "padiem.engine.tools/1.0",
            "agent_id": "agent:padiem:web-xlsx-confirm@1",
            "canonical_tool_id": "tool:padiem:web-xlsx-confirm@1",
            "run_id": "torun:" + "f"*24,
            "status": "paused",
            "approval_pause": {
                "status": "paused", "run_id": "torun:" + "f"*24,
                "tool_id": "workspace.xlsx.confirm_original_read",
                "requirement": "user_confirmation",
                "approval_scope": [],
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
            body["tool"]["status"] = "completed"
        elif self.mode == "wrong_source":
            body["tool"]["canonical_tool_id"] = "tool:padiem:other-source@1"
        return body


def harness():
    app, settings, meta, r2, storage, selections_db = setup()
    selections_db.executescript((
        Path(__file__).resolve().parents[2] / "migrations"
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
