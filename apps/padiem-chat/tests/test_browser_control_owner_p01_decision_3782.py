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
from app.browser_control_owner_p01_tickets import D1BrowserControlOwnerTicketLoader
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
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SQL_CONTRACT.read_text(encoding="utf-8"))
        self.calls = []

    def prepare(self, sql):
        assert sql.startswith(("INSERT INTO padiem_browser_control_owner_p01_decisions",
                               "SELECT ticket_ref,session_user_id,workspace_ref,"))
        self.calls.append(sql)
        db = self

        class Statement:
            def bind(self, *args):
                self.params = args
                return self

            async def first(self):
                value = db.db.execute(sql, self.params).fetchone()
                return dict(value) if value is not None else None

            async def run(self):
                cursor = db.db.execute(sql, self.params)
                db.db.commit()
                return {"success": True, "meta": {"changes": cursor.rowcount}}
        return Statement()

    def seed_ticket(self, item, *, issued_at=None):
        issued = issued_at or datetime.now(timezone.utc) - timedelta(seconds=30)
        self.db.execute(
            "INSERT INTO padiem_browser_control_owner_p01_tickets "
            "(ticket_ref,session_user_id,workspace_ref,engine_owner_subject_id,"
            "app_id,continuation_ref,pause_id,engine_run_id,tool_id,approval_scope,"
            "invocation_sha256,original_request_fingerprint,"
            "original_admission_decision_id,expires_at,revoked_at,"
            "server_issued_at,server_issuer_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.ticket_ref, item.session_user_id, item.workspace_ref,
                item.engine_owner_subject_id, item.app_id, item.continuation_ref,
                item.pause_id, item.engine_run_id, item.tool_id,
                item.approval_scope[0], item.invocation_sha256,
                item.original_request_fingerprint, item.original_admission_decision_id,
                item.expires_at.isoformat(), None, issued.isoformat(),
                "issuer.engine.original.run.3782",
            )
        )
        self.db.commit()

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
        engine_owner_subject_id="subject_test",
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

    owner.seed_ticket(ticket_override or ticket())
    real_loader = D1BrowserControlOwnerTicketLoader(
        owner_binding=owner, engine_continuation_binding=object()
    )

    async def loader(*, user_id, workspace_ref, ticket_ref):
        requests.append((user_id, workspace_ref, ticket_ref))
        return await real_loader(
            user_id=user_id, workspace_ref=workspace_ref, ticket_ref=ticket_ref,
        )

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
    lambda x: replace(x, engine_owner_subject_id="foreign.engine.subject"),
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



def test_current_ticket_must_exist_in_independent_owner_d1_even_for_valid_dataclass():
    owner = OwnerDB()
    try:
        t = ticket()
        with pytest.raises(ValueError, match="exactly-once"):
            asyncio.run(record_first_party_browser_control_approval(
                ticket=t, authenticated_user_id=OWNER,
                authenticated_workspace_ref=WORKSPACE,
                owner_binding=owner, engine_continuation_binding=object(),
                now=datetime.now(timezone.utc),
            ))
        assert owner.rows() == []
    finally:
        owner.close()


@pytest.mark.parametrize("column,value", [
    ("session_user_id", FOREIGN_OWNER),
    ("workspace_ref", "foreign.workspace"),
    ("engine_owner_subject_id", "foreign.engine.subject"),
    ("app_id", "foreign.engine.app"),
    ("continuation_ref", "cont.foreign"),
    ("pause_id", "pause.foreign"),
    ("engine_run_id", "torun.foreign"),
    ("invocation_sha256", "f" * 64),
    ("original_request_fingerprint", "f" * 64),
    ("original_admission_decision_id", "decision.other"),
    ("expires_at", (datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat()),
    ("revoked_at", datetime.now(timezone.utc).isoformat()),
])
def test_loaded_ticket_changed_or_revoked_before_atomic_write_never_approves(column, value):
    owner = OwnerDB()
    try:
        original = ticket()
        owner.seed_ticket(original)
        loader = D1BrowserControlOwnerTicketLoader(
            owner_binding=owner, engine_continuation_binding=object()
        )
        loaded = asyncio.run(loader(
            user_id=OWNER, workspace_ref=WORKSPACE, ticket_ref=original.ticket_ref
        ))
        assert loaded == original
        owner.db.execute(
            f"UPDATE padiem_browser_control_owner_p01_tickets SET {column}=?",
            (value,),
        )
        owner.db.commit()
        with pytest.raises(ValueError):
            asyncio.run(record_first_party_browser_control_approval(
                ticket=loaded, authenticated_user_id=OWNER,
                authenticated_workspace_ref=WORKSPACE, owner_binding=owner,
                engine_continuation_binding=object(), now=datetime.now(timezone.utc),
            ))
        assert owner.rows() == []
    finally:
        owner.close()


def test_missing_stale_or_foreign_ticket_does_not_reach_owner_writer():
    owner = OwnerDB()
    try:
        item = ticket()
        owner.seed_ticket(item)
        loader = D1BrowserControlOwnerTicketLoader(
            owner_binding=owner, engine_continuation_binding=object()
        )
        async def fetch(**kwargs):
            return await loader(**kwargs)
        for who, ws, ref in [
            (FOREIGN_OWNER, WORKSPACE, item.ticket_ref),
            (OWNER, "workspace.foreign", item.ticket_ref),
            (OWNER, WORKSPACE, "ticket.nonexistent"),
        ]:
            assert asyncio.run(fetch(
                user_id=who, workspace_ref=ws, ticket_ref=ref,
            )) is None
        owner.db.execute(
            "UPDATE padiem_browser_control_owner_p01_tickets SET revoked_at=?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        owner.db.commit()
        assert asyncio.run(fetch(
            user_id=OWNER, workspace_ref=WORKSPACE, ticket_ref=item.ticket_ref
        )) is None
        assert owner.rows() == []
    finally:
        owner.close()


def test_future_issued_ticket_is_not_current_human_approval_authority():
    owner = OwnerDB()
    try:
        item = ticket()
        owner.seed_ticket(
            item, issued_at=datetime.now(timezone.utc) + timedelta(minutes=1)
        )
    except sqlite3.IntegrityError:
        # The DB CHECK expires > issued_at may refuse future-issued rows; both
        # outcomes must remain closed and the owner has no approval record.
        assert owner.rows() == []
    else:
        loader = D1BrowserControlOwnerTicketLoader(
            owner_binding=owner, engine_continuation_binding=object()
        )
        assert asyncio.run(loader(
            user_id=OWNER, workspace_ref=WORKSPACE, ticket_ref=item.ticket_ref,
        )) is None
        with pytest.raises(ValueError):
            asyncio.run(record_first_party_browser_control_approval(
                ticket=item, authenticated_user_id=OWNER,
                authenticated_workspace_ref=WORKSPACE, owner_binding=owner,
                engine_continuation_binding=object(), now=datetime.now(timezone.utc),
            ))
        assert owner.rows() == []
    finally:
        owner.close()


def test_owner_ticket_loader_same_engine_binding_is_never_accepted():
    owner = OwnerDB()
    try:
        with pytest.raises(ValueError, match="independent"):
            D1BrowserControlOwnerTicketLoader(
                owner_binding=owner, engine_continuation_binding=owner,
            )
    finally:
        owner.close()


@pytest.mark.parametrize("missing", [
    "identity_shadow_store",
    "control_plane_identity_authority",
])
def test_signed_cookie_without_active_control_plane_auth_never_approves(missing):
    client, owner, calls = setup_route()
    try:
        setattr(client.app.state, missing, None)
        response = client.post(
            PATH, json={"ticket_ref": ticket().ticket_ref, "decision": "approve"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "browser_p01_canonical_identity_unavailable"
        assert calls == [] and owner.rows() == []
    finally:
        owner.close()
