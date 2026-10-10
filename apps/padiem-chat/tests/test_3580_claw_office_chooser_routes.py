"""Owner-bound Office candidate presentation and canonical Engine pause handoff.

No fake decision verifier or cloud/Drive mutation. Existing P01 decision route
is checked by its dedicated suite; this surface cannot authorize file reading.
"""
from __future__ import annotations

import asyncio
import httpx

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_office_chooser_routes import LIST_PATH, SELECT_PATH
from app.config import Settings

OWNER = "usr_3580_chooser_owner"
OTHER = "usr_3580_chooser_other"
RUN = "run_3580_owner_quote"
TOKEN = "a"*64
ORIGIN = "https://chat.example.test"


class ReadyStore:
    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []


class OwnerSource:
    configured = True

    def __init__(self):
        self.calls = []
        self.broken = False

    def candidates(self, *, owner_id, run_id):
        self.calls.append(("candidates", owner_id, run_id))
        if owner_id != OWNER or run_id != RUN:
            return None
        if self.broken:
            return {"run_id": RUN, "metadata_only": True, "read_authorized": True,
                    "candidates": []}
        return {
            "run_id": RUN, "metadata_only": True, "read_authorized": False,
            "limited": False, "candidates": [
                {"filename": "quote.xls", "kind": "xls", "size_bytes": 770560,
                 "candidate_ref": TOKEN, "absolute_path": "PRIVATE_WINDOWS_PATH",
                 "content": "PRIVATE_WORKBOOK_BYTES"},
            ],
        }

    def select(self, *, owner_id, run_id, candidate_ref):
        self.calls.append(("select", owner_id, run_id, candidate_ref))
        if owner_id != OWNER or run_id != RUN or candidate_ref != TOKEN:
            return None
        if self.broken:
            return {"run_id": RUN, "candidate_ref": TOKEN,
                    "status": "approved", "approval_required": False,
                    "engine_run_id": "fake_approved"}
        return {
            "run_id": RUN, "candidate_ref": TOKEN,
            "status": "awaiting_approval", "approval_required": True,
            "engine_run_id": "p01_pending_3580",
            "approval_secret": "UNTRUSTED_PRIVATE_EVIDENCE",
        }


async def exchange(*, source=None, owner=OWNER, method="GET", body=None, content_type=True):
    settings = Settings(
        session_secret="hark-chooser-tests-secret", auth_mode="mock",
        public_base_url=ORIGIN,
    )
    app = create_app(settings, history_store=ReadyStore(), claw_office_chooser_source=source)
    headers = {"Origin": ORIGIN}
    if owner is not None:
        headers["Cookie"] = SESSION_COOKIE + "=" + create_session_token(settings, owner)
    if method == "POST" and content_type:
        headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url=ORIGIN) as client:
        if method == "GET":
            return await client.get(LIST_PATH, headers=headers, params={"run_id": RUN})
        return await client.post(SELECT_PATH, headers=headers,
                                 json=body if content_type else None,
                                 content=None if content_type else b"{}")


def run(**kwargs):
    return asyncio.run(exchange(**kwargs))


def test_absent_owner_or_source_refuses_without_file_access():
    source = OwnerSource()
    assert run(source=source, owner=None).status_code == 401
    assert not source.calls
    assert run().status_code == 503
    assert run(method="POST", body={"run_id": RUN, "candidate_ref": TOKEN}).status_code == 503
    assert not source.calls


def test_selected_root_candidate_projection_strips_local_path_and_bytes():
    source = OwnerSource()
    response = run(source=source)
    assert response.status_code == 200
    content = response.json()
    assert content["contract_version"] == "hark-office-owner-chooser.v1"
    assert content["requires_engine_approval"] is True
    assert content["read_authorized"] is False
    assert content["candidates"] == [{
        "filename": "quote.xls", "kind": "xls",
        "size_bytes": 770560, "candidate_ref": TOKEN,
    }]
    assert "PRIVATE" not in response.text
    assert source.calls == [("candidates", OWNER, RUN)]


def test_foreign_owner_and_malformed_trusted_result_are_bounded_refusals():
    source = OwnerSource()
    assert run(source=source, owner=OTHER).status_code == 404
    source.broken = True
    bad = run(source=source)
    assert bad.status_code == 503
    assert "PRIVATE" not in bad.text


def test_selection_can_return_only_engine_pause_not_file_authority():
    source = OwnerSource()
    selected = run(source=source, method="POST", body={
        "run_id": RUN, "candidate_ref": TOKEN,
    })
    assert selected.status_code == 200
    body = selected.json()
    assert body["status"] == "awaiting_approval"
    assert body["engine_run_id"] == "p01_pending_3580"
    assert body["file_read_authorized"] is False
    assert body["processing_started"] is False
    assert "UNTRUSTED" not in selected.text
    assert source.calls == [("select", OWNER, RUN, TOKEN)]


def test_browser_cannot_supply_approval_workspace_root_device_or_filename():
    source = OwnerSource()
    for field, value in (
        ("decision", "approve"), ("workspace_id", "other"),
        ("root_ref", "C:/"), ("filename", "secret.xlsx"),
        ("approval_decision", {"outcome": "approved"}),
        ("p01_approval_payload", True), ("user_id", OWNER),
    ):
        data = {"run_id": RUN, "candidate_ref": TOKEN, field: value}
        assert run(source=source, method="POST", body=data).status_code == 400
    assert not source.calls


def test_unapproved_source_cannot_claim_approved_or_executed():
    source = OwnerSource()
    source.broken = True
    resp = run(source=source, method="POST", body={
        "run_id": RUN, "candidate_ref": TOKEN,
    })
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "p01_engine_pause_not_verified"


def test_wrong_candidate_and_foreign_owner_do_not_resume_p01():
    source = OwnerSource()
    for owner, token in ((OTHER, TOKEN), (OWNER, "b"*64)):
        resp = run(source=source, owner=owner, method="POST", body={
            "run_id": RUN, "candidate_ref": token,
        })
        assert resp.status_code == 409
    assert "secret" not in str(source.calls)


def test_invalid_content_type_and_no_owner_refused():
    source = OwnerSource()
    assert run(source=source, method="POST", content_type=False).status_code == 415
    assert run(source=source, method="POST", owner=None, body={
        "run_id": RUN, "candidate_ref": TOKEN,
    }).status_code == 401
    assert source.calls == []
