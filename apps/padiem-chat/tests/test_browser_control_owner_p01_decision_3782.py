"""#3782 actual signed-in B54 owner route + canonical per-command click record.

No Production route registration or P01 Engine grant. Uses the existing B54
signed-cookie, canonical B62 owner/workspace resolver and approved decision
submission vocabulary. The ticket store here is TEST ONLY; real owner ticket
issuance and authenticated Engine binding remain separate deployment gates.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.browser_control_owner_p01_decision import (
    BROWSER_CONTROL_OWNER_DECISION_ROUTE_WIRED,
    ServerAdmittedBrowserControlOwnerTicket,
    browser_control_owner_p01_decision,
    record_first_party_browser_control_approval,
)
from starlette.routing import Route
from test_claw_approval_decision import (
    FOREIGN_OWNER,
    OWNER,
    WORKSPACE,
    _client,
    _HandoffStore,
)

PATH = "/api/claw/browser-control/approvals/decision"
SQL_CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "padiem-ai-engine/contracts/browser_control_owner_p01_independent_d1.sql"
)


class OwnerDB:
    """D1 prepare/bind/run using the actual owner schema, no fake approval."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.executescript(SQL_CONTRACT.read_text(encoding="utf-8"))
        self.calls = []

    def prepare(self, sql):
        assert sql.startswith("INSERT INTO padiem_browser_control_owner_p01_decisions")
        self.calls.append(sql)
        db = self

        class Statement:
            def bind(self, *args):
                self.params = args
                return self

            async def run(self):
                cursor = db.db.execute(sql, self.params)
                db.db.commit()
                return {"success": True, "meta": {"changes": cursor.rowcount}}
        return Statement()

    def rows(self):
        return self.db.execute(
            "SELECT app_id,owner_subject_id,invocation_sha256,"
            "decision_id,evidence_ref,authenticated_owner_session_ref "
            "FROM padiem_browser_control_owner_p01_decisions"
        ).fetchall()

    def close(self):
        self.db.close()


def ticket(*, uid=OWNER, workspace=WORKSPACE):
    return ServerAdmittedBrowserControlOwnerTicket(
        ticket_ref="ticket.approved.browser.3782",
        session_user_id=uid,
        workspace_ref=workspace,
        engine_owner_subject_id="subject.owner.engine.3782",
        app_id="engine.owner.browser.3782",
        continuation_ref="cont.owner.browser.3782",
        pause_id="pause.owner.browser.3782",
        engine_run_id="torun.browser.3782",
        tool_id="browser.control",
        approval_scope=("browser.control",),
        invocation_sha256="b" * 64,
        original_request_fingerprint="d" * 64,
        original_admission_decision_id="decision.original.admission.3782",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=4),
    )


def setup_route(*, signed_in=True, ticket_override=None, loader_enabled=True):
    owner = OwnerDB()
    client = _client(_HandoffStore(), signed_in=signed_in)
    app = client.app
    # Test-only route must precede the app's catch-all page route.
    app.router.routes.insert(0, Route(PATH, browser_control_owner_p01_decision, methods=["POST"]))
    requests = []

    async def loader(*, user_id, workspace_ref, ticket_ref):
        requests.append((user_id, workspace_ref, ticket_ref))
        return ticket_override or ticket()

    if loader_enabled:
        app.state.browser_control_owner_ticket_loader = loader
    app.state.browser_control_owner_p01_d1 = owner
    app.state.browser_control_engine_d1 = object()
    return client, owner, requests


def test_route_stays_unregistered_in_production_app_factory():
    client = _client(_HandoffStore())
    assert BROWSER_CONTROL_OWNER_DECISION_ROUTE_WIRED is False
    assert all(getattr(r, "path", None) != PATH for r in client.app.router.routes)


def test_genuine_b54_session_owner_approves_only_one_exact_ticket():
    client, owner, calls = setup_route()
    try:
        result = client.post(
            PATH, json={"ticket_ref": ticket().ticket_ref, "decision": "approve"},
        )
        assert result.status_code == 200, result.json()
        payload = result.json()
        assert payload == {
            "ok": True,
            "status": "owner_approval_evidence_recorded",
            "browser_action_executed": False,
            "engine_approval_completed": False,
        }
        assert calls == [(OWNER, WORKSPACE, ticket().ticket_ref)]
        rows = owner.rows()
        assert len(rows) == 1
        assert rows[0][0:3] == (
            ticket().app_id, ticket().engine_owner_subject_id, ticket().invocation_sha256,
        )
        assert rows[0][3].startswith("decision_b54_")
        assert rows[0][4].startswith("b54_decision:")
        assert rows[0][5].startswith("owner_confirmation_")
        # No second approval can overwrite the first user confirmation.
        repeat = client.post(
            PATH, json={"ticket_ref": ticket().ticket_ref, "decision": "approve"},
        )
        assert repeat.status_code == 404
        assert len(owner.rows()) == 1
    finally:
        owner.close()


def test_anonymous_login_never_reads_canonical_ticket_or_writes_approval():
    client, owner, calls = setup_route(signed_in=False)
    try:
        result = client.post(
            PATH, json={"ticket_ref": ticket().ticket_ref, "decision": "approve"},
        )
        assert result.status_code == 401
        assert calls == [] and owner.rows() == []
    finally:
        owner.close()


@pytest.mark.parametrize("body", [
    {"ticket_ref": "ticket.approved.browser.3782", "decision": "deny"},
    {"ticket_ref": "ticket.approved.browser.3782", "decision": "approved"},
    {"ticket_ref": "ticket.approved.browser.3782", "decision": "approve", "owner_id": OWNER},
    {"ticket_ref": "ticket.approved.browser.3782", "decision": "approve", "origin_scope": "https://attacker.example"},
    {"ticket_ref": "ticket.approved.browser.3782", "decision": "approve", "tool_id": "process.execute"},
    {"ticket_ref": "ticket.approved.browser.3782", "decision": "approve", "invocation_sha256": "f"*64},
    {"ticket_ref": "bad ticket", "decision": "approve"},
    {"decision": "approve"},
])
def test_client_cannot_control_scope_or_engine_decision_evidence(body):
    client, owner, calls = setup_route()
    try:
        result = client.post(PATH, json=body)
        assert result.status_code == 422
        assert calls == [] and owner.rows() == []
    finally:
        owner.close()


@pytest.mark.parametrize("bad_ticket", [
    lambda x: replace(x, session_user_id=FOREIGN_OWNER),
    lambda x: replace(x, workspace_ref="other.workspace"),
    lambda x: replace(x, ticket_ref="another.ticket.3782"),
    lambda x: replace(x, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
])
def test_foreign_owner_workspace_or_expired_ticket_never_writes(bad_ticket):
    client, owner, calls = setup_route(ticket_override=bad_ticket(ticket()))
    try:
        result = client.post(
            PATH, json={"ticket_ref": ticket().ticket_ref, "decision": "approve"},
        )
        assert result.status_code == 404
        assert calls == [(OWNER, WORKSPACE, ticket().ticket_ref)]
        assert owner.rows() == []
    finally:
        owner.close()


def test_missing_canonical_ticket_loader_fails_503():
    client, owner, calls = setup_route(loader_enabled=False)
    try:
        result = client.post(
            PATH, json={"ticket_ref": ticket().ticket_ref, "decision": "approve"},
        )
        assert result.status_code == 503
        assert calls == [] and owner.rows() == []
    finally:
        owner.close()


def test_missing_engine_identity_d1_or_same_binding_refuses():
    owner = OwnerDB()
    try:
        t = ticket()
        with pytest.raises(ValueError):
            asyncio.run(record_first_party_browser_control_approval(
                ticket=t, authenticated_user_id=OWNER,
                authenticated_workspace_ref=WORKSPACE,
                owner_binding=owner, engine_continuation_binding=owner,
                now=datetime.now(timezone.utc),
            ))
        assert owner.rows() == []
    finally:
        owner.close()
