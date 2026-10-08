"""#3782: B54 signed human click -> exact private Engine owner D1 reread/CAS.

These are hermetic transport fixtures, NOT production user approval.
The source route stays absent from app_factory and Production.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from app.browser_control_owner_p01_finalize import (
    BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
    BROWSER_CONTROL_OWNER_P01_FINALIZE_ROUTE_WIRED,
    browser_control_owner_p01_finalize,
)
from kagent.p01_adapter import P01_APP_ID
from padiem_ai_engine_client import (
    ENGINE_BROWSER_CONTROL_OWNER_RESUME_PATH,
    ENGINE_INTERNAL_ORIGIN,
    EngineTransportResponse,
    PadiemAiEngineClient,
)
from starlette.routing import Route
from test_browser_control_owner_p01_decision_3782 import (
    PATH,
    setup_route,
    ticket,
)

REF = "cont_3782canonical"


class _EngineTransport:
    def __init__(self, *, response=None, status=200):
        self.requests = []
        self.status = status
        self.response = response if response is not None else {
            "ok": True,
            "tool": {
                "contract_version": "1.0",
                "agent_id": "agent:padiem:browser_approval@1",
                "canonical_tool_id": "tool:padiem:browser_control@1",
                "run_id": "torun.browser.3782",
                "status": "approval_recorded",
                "continuation_ref": REF,
                "browser_action_executed": False,
                "broker_command_dispatched": False,
            },
        }

    async def request(self, *, method, url, headers, body):
        self.requests.append((method, url, headers, json.loads(body)))
        return EngineTransportResponse(
            status=self.status, body=json.dumps(self.response).encode(), headers={},
        )


def _app(*, engine_app=P01_APP_ID, response=None, status=200, signed_in=True):
    original = replace(ticket(), app_id=P01_APP_ID, continuation_ref=REF)
    client, owner, reads = setup_route(signed_in=signed_in, ticket_override=original)
    transport = _EngineTransport(response=response, status=status)
    client.app.state.browser_control_owner_resume_engine_client = PadiemAiEngineClient(
        transport=transport,
        app_id=engine_app,
        caller_id="b54.browser.p01",
        credential="z" * 40,
    )
    return client, owner, reads, transport


def _click(client):
    return client.post(PATH, json={
        "ticket_ref": ticket().ticket_ref, "decision": "approve",
    })


def test_signed_owner_click_records_before_private_engine_resume():
    client, owner, _reads, transport = _app()
    try:
        result = _click(client)
        assert result.status_code == 200, result.json()
        assert result.json() == {
            "ok": True,
            "status": "owner_approval_evidence_recorded",
            "browser_action_executed": False,
            "engine_approval_completed": True,
        }
        assert len(owner.rows()) == 1
        assert len(transport.requests) == 1
        method, url, headers, wire = transport.requests[0]
        assert method == "POST"
        assert url == ENGINE_INTERNAL_ORIGIN + ENGINE_BROWSER_CONTROL_OWNER_RESUME_PATH
        assert wire == {"app_id": P01_APP_ID, "continuation_ref": REF}
        assert headers["X-Padiem-Engine-Caller"] == "b54.browser.p01"
        assert "decision" not in wire and "owner_subject_id" not in wire
        assert "z" * 40 not in result.text
        assert result.headers["cache-control"].startswith("no-store")
        repeat = _click(client)
        assert repeat.status_code == 404
        assert len(transport.requests) == 1
        assert len(owner.rows()) == 1
    finally:
        owner.close()


@pytest.mark.parametrize("bad", [
    {"ok": True, "tool": {
        "contract_version": "1.0",
        "agent_id": "agent:padiem:browser_approval@1",
        "canonical_tool_id": "tool:padiem:browser_control@1",
        "run_id": "torun.browser.3782",
        "status": "approval_recorded",
        "continuation_ref": REF,
        "browser_action_executed": True,
        "broker_command_dispatched": False,
    }},
    {"ok": True, "tool": {"status": "approval_recorded"}},
    {"ok": True, "tool": {
        "contract_version": "1.0",
        "agent_id": "agent:padiem:browser_approval@1",
        "canonical_tool_id": "tool:padiem:browser_control@1",
        "run_id": "torun.browser.3782",
        "status": "approval_recorded",
        "continuation_ref": "cont_other_validref",
        "browser_action_executed": False,
        "broker_command_dispatched": False,
    }},
    {"ok": True, "tool": {"browser_action_executed": False}},
])
def test_malformed_engine_success_never_masquerades_as_completed(bad):
    client, owner, _reads, transport = _app(response=bad)
    try:
        result = _click(client)
        assert result.status_code == 200
        assert result.json()["engine_approval_completed"] is False
        assert result.json()["browser_action_executed"] is False
        assert len(owner.rows()) == 1
        assert len(transport.requests) == 1
    finally:
        owner.close()


def test_private_engine_outage_preserves_recorded_only_state():
    client, owner, _reads, transport = _app(
        status=503,
        response={"ok": False, "error": {"code": "browser_control_owner_resume_unavailable"}},
    )
    try:
        result = _click(client)
        assert result.status_code == 200
        assert result.json()["engine_approval_completed"] is False
        assert len(owner.rows()) == 1
        assert len(transport.requests) == 1
        assert _click(client).status_code == 404  # no second human approval
        assert len(transport.requests) == 1
    finally:
        owner.close()


def test_mismatched_engine_app_or_anonymous_owner_never_calls_transport():
    client, owner, _reads, transport = _app(engine_app="foreign.engine.app")
    try:
        result = _click(client)
        assert result.status_code == 200
        assert result.json()["engine_approval_completed"] is False
        assert len(owner.rows()) == 1
        assert transport.requests == []
    finally:
        owner.close()
    client, owner, _reads, transport = _app(signed_in=False)
    try:
        assert _click(client).status_code == 401
        assert transport.requests == []
        assert owner.rows() == []
    finally:
        owner.close()


@pytest.mark.parametrize("extra", [
    {"decision": "approve", "ticket_ref": ticket().ticket_ref, "app_id": P01_APP_ID},
    {"decision": "approve", "ticket_ref": ticket().ticket_ref, "engine_approval_completed": True},
    {"decision": "approve", "ticket_ref": ticket().ticket_ref, "resume": True},
    {"decision": "deny", "ticket_ref": ticket().ticket_ref},
])
def test_browser_cannot_mint_resumption_or_override_owner_decision(extra):
    client, owner, _reads, transport = _app()
    try:
        response = client.post(PATH, json=extra)
        assert response.status_code == 422
        assert owner.rows() == []
        assert transport.requests == []
    finally:
        owner.close()



def _finalize_route(client):
    client.app.router.routes.insert(
        0,
        Route(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            browser_control_owner_p01_finalize,
            methods=["POST"],
        ),
    )


def test_engine_outage_after_click_can_retry_without_second_user_approval():
    client, owner, _reads, transport = _app(
        status=503,
        response={"ok": False, "error": {"code": "browser_control_owner_resume_unavailable"}},
    )
    try:
        assert BROWSER_CONTROL_OWNER_P01_FINALIZE_ROUTE_WIRED is False
        assert all(
            getattr(route, "path", None) != BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH
            for route in client.app.router.routes
        )
        _finalize_route(client)
        first = _click(client)
        assert first.status_code == 200
        assert first.json()["engine_approval_completed"] is False
        assert len(owner.rows()) == 1
        # Transport test double now represents an Engine that has recovered
        # and INDEPENDENTLY checked the owner record. This is not a live test.
        transport.status = 200
        transport.response = _EngineTransport().response
        retry = client.post(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            json={"ticket_ref": ticket().ticket_ref},
        )
        assert retry.status_code == 200, retry.json()
        assert retry.json() == {
            "ok": True,
            "engine_approval_completed": True,
            "browser_action_executed": False,
            "broker_command_dispatched": False,
        }
        assert len(transport.requests) == 2
        assert transport.requests[0][3] == transport.requests[1][3]
        assert len(owner.rows()) == 1
        assert retry.headers["cache-control"].startswith("no-store")
    finally:
        owner.close()


@pytest.mark.parametrize("wire", [
    {"ticket_ref": ticket().ticket_ref, "decision": "approve"},
    {"ticket_ref": ticket().ticket_ref, "owner_id": "foreign"},
    {"ticket_ref": ticket().ticket_ref, "approved": True},
    {"ticket_ref": ticket().ticket_ref, "app_id": P01_APP_ID},
    {"ticket_ref": "bad ticket"},
    [],
    {},
])
def test_finalize_never_accepts_user_supplied_approval_or_invalid_ticket(wire):
    client, owner, _reads, transport = _app()
    try:
        _finalize_route(client)
        r = client.post(BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH, json=wire)
        assert r.status_code == 422
        assert owner.rows() == []
        assert transport.requests == []
    finally:
        owner.close()


def test_finalize_refuses_foreign_or_revoked_ticket_and_missing_authorities():
    client, owner, _reads, transport = _app()
    try:
        _finalize_route(client)
        assert client.post(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            json={"ticket_ref": "foreign.ticket"},
        ).status_code == 404
        assert transport.requests == []
        owner.db.execute(
            "UPDATE padiem_browser_control_owner_p01_tickets SET revoked_at=?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        owner.db.commit()
        assert client.post(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            json={"ticket_ref": ticket().ticket_ref},
        ).status_code == 404
        assert transport.requests == []
    finally:
        owner.close()

    client, owner, _reads, transport = _app(engine_app="foreign.engine.app")
    try:
        _finalize_route(client)
        assert client.post(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            json={"ticket_ref": ticket().ticket_ref},
        ).status_code == 404
        assert transport.requests == []
    finally:
        owner.close()

    client, owner, _reads, transport = _app()
    try:
        _finalize_route(client)
        client.app.state.control_plane_identity_authority = None
        assert client.post(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            json={"ticket_ref": ticket().ticket_ref},
        ).status_code == 503
        assert transport.requests == []
    finally:
        owner.close()


def test_finalize_anonymous_or_unbound_engine_never_calls_service():
    client, owner, _reads, transport = _app(signed_in=False)
    try:
        _finalize_route(client)
        result = client.post(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            json={"ticket_ref": ticket().ticket_ref},
        )
        assert result.status_code == 401
        assert transport.requests == [] and owner.rows() == []
    finally:
        owner.close()
    client, owner, _reads, transport = _app()
    try:
        _finalize_route(client)
        client.app.state.browser_control_owner_resume_engine_client = None
        assert client.post(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            json={"ticket_ref": ticket().ticket_ref},
        ).status_code == 503
        assert transport.requests == []
    finally:
        owner.close()
