"""#3782 B54 source-only closed three-route owner P01 product composition.

Runs the REAL existing B54 signed-cookie/CP-session identity and independent
owner D1 INSERT/SELECT behind a closed, deliberately opt-in app factory bundle.
No real Engine, external P01, Broker, browser or Production route activation.
"""
from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from app.app_factory import create_app
from app.auth import create_session_token
from app.browser_control_owner_p01_composition import (
    BROWSER_CONTROL_OWNER_P01_DECISION_PATH,
    BROWSER_CONTROL_OWNER_P01_PRODUCT_COMPOSITION_WIRED,
    BrowserControlOwnerP01Composition,
)
from app.browser_control_owner_p01_finalize import (
    BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
)
from app.browser_control_owner_p01_tickets import D1BrowserControlOwnerTicketLoader
from app.browser_control_owner_ticket_request import (
    BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH,
)
from kagent.p01_adapter import P01_APP_ID
from padiem_ai_engine_client import (
    ENGINE_BROWSER_CONTROL_OWNER_RESUME_PATH,
    ENGINE_BROWSER_CONTROL_OWNER_TICKET_PATH,
    EngineTransportResponse,
    PadiemAiEngineClient,
)
from starlette.testclient import TestClient
from test_browser_control_owner_p01_decision_3782 import OwnerDB, ticket
from test_claw_approval_decision import (
    OWNER,
    SESSION_COOKIE,
    _authority,
    _google_settings,
    _HandoffStore,
    _identity_store,
)

CONT = "cont_3782canonical"
OWNER_TICKET = replace(
    ticket(), app_id=P01_APP_ID, continuation_ref=CONT,
)


class _Engine:
    def __init__(self, owner_db=None):
        self.requests = []
        self.owner_db = owner_db

    async def request(self, *, method, url, headers, body):
        data = json.loads(body)
        self.requests.append((method, url, data))
        if url.endswith(ENGINE_BROWSER_CONTROL_OWNER_TICKET_PATH):
            payload = {
                "ok": True, "ticket_ref": OWNER_TICKET.ticket_ref,
                "owner_approval_recorded": False, "browser_action_executed": False,
            }
        elif url.endswith(ENGINE_BROWSER_CONTROL_OWNER_RESUME_PATH):
            # Synthetic Engine adapter refuses until the independent owner D1
            # records a signed human click; no fixture supplies arbitrary
            # approval to the B54 HTTP request.
            if self.owner_db is not None and not self.owner_db.rows():
                return EngineTransportResponse(
                    status=503,
                    body=json.dumps({
                        "ok": False,
                        "error": {"code": "owner_p01_not_recorded"},
                    }).encode("utf-8"),
                    headers={},
                )
            payload = {
                "ok": True,
                "tool": {
                    "contract_version": "1.0",
                    "agent_id": "agent:padiem:browser_approval@1",
                    "canonical_tool_id": "tool:padiem:browser_control@1",
                    "run_id": OWNER_TICKET.engine_run_id,
                    "status": "approval_recorded",
                    "continuation_ref": CONT,
                    "browser_action_executed": False,
                    "broker_command_dispatched": False,
                },
            }
        else:
            raise AssertionError("unapproved Engine path")
        return EngineTransportResponse(
            status=200, body=json.dumps(payload).encode("utf-8"), headers={},
        )


def _setup(*, signed_in=True, injection=None):
    owner = OwnerDB()
    owner.seed_ticket(OWNER_TICKET)
    engine_d1 = MagicMock()
    loader = D1BrowserControlOwnerTicketLoader(
        owner_binding=owner, engine_continuation_binding=engine_d1,
    )
    transport = _Engine(owner)
    client = PadiemAiEngineClient(
        transport=transport, app_id=P01_APP_ID,
        caller_id="b54.browser.p01", credential="z" * 40,
    )
    bundle = BrowserControlOwnerP01Composition(
        owner_d1=owner, engine_continuation_d1=engine_d1,
        ticket_loader=loader, engine_client=client,
    )
    if injection is not None:
        bundle = injection(bundle)
    settings = _google_settings()
    chat_d1 = MagicMock()
    app = create_app(
        settings=settings,
        history_store=_HandoffStore(),
        control_plane_identity_authority=_authority(),
        identity_shadow_store=_identity_store(),
        d1_binding=chat_d1,
        r2_binding=MagicMock(),
        browser_control_owner_p01=bundle,
    )
    test_client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, OWNER),
            domain="chat.example.test", path="/",
        )
    return test_client, owner, transport, bundle


def test_default_product_has_no_owner_browser_routes_or_engine_client():
    assert BROWSER_CONTROL_OWNER_P01_PRODUCT_COMPOSITION_WIRED is False
    default = create_app(settings=_google_settings())
    paths = {getattr(p, "path", None) for p in default.router.routes}
    for path in (
        BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH,
        BROWSER_CONTROL_OWNER_P01_DECISION_PATH,
        BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
    ):
        assert path not in paths
    assert default.state.browser_control_owner_ticket_engine_client is None
    assert default.state.browser_control_owner_resume_engine_client is None
    assert default.state.browser_control_owner_p01_d1 is None


def test_explicit_closed_bundle_mounts_only_three_existing_post_routes():
    test_client, owner, engine, bundle = _setup()
    try:
        registered = {
            getattr(p, "path", None): p
            for p in test_client.app.router.routes
        }
        assert all(path in registered for path in (
            BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH,
            BROWSER_CONTROL_OWNER_P01_DECISION_PATH,
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
        ))
        for path in (
            BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH,
            BROWSER_CONTROL_OWNER_P01_DECISION_PATH,
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
        ):
            assert registered[path].methods == {"POST"}
        assert test_client.app.state.browser_control_owner_p01_d1 is owner
        assert test_client.app.state.browser_control_owner_ticket_loader is bundle.ticket_loader
        assert test_client.app.state.browser_control_owner_resume_engine_client is bundle.engine_client
        assert engine.requests == []
    finally:
        owner.close()


def test_b54_signed_in_ticket_then_actual_owner_d1_click_then_engine_resume():
    client, owner, engine, _ = _setup()
    try:
        requested = client.post(
            BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH,
            json={"continuation_ref": CONT},
        )
        assert requested.status_code == 200, requested.text
        assert requested.json() == {
            "ok": True, "ticket_ref": OWNER_TICKET.ticket_ref,
            "owner_approval_recorded": False, "browser_action_executed": False,
        }
        assert owner.rows() == []
        assert len(engine.requests) == 1
        method, url, payload = engine.requests[0]
        assert method == "POST"
        assert url.endswith(ENGINE_BROWSER_CONTROL_OWNER_TICKET_PATH)
        assert payload["product_user_id"] == OWNER
        assert payload["auth_session_ref"] == "session_test123"
        assert "owner_ref" not in payload
        assert "decision" not in payload

        decision = client.post(BROWSER_CONTROL_OWNER_P01_DECISION_PATH, json={
            "ticket_ref": OWNER_TICKET.ticket_ref, "decision": "approve",
        })
        assert decision.status_code == 200, decision.text
        assert decision.json() == {
            "ok": True, "status": "owner_approval_evidence_recorded",
            "browser_action_executed": False, "engine_approval_completed": True,
        }
        assert len(owner.rows()) == 1
        assert len(engine.requests) == 2
        assert engine.requests[1][1].endswith(
            ENGINE_BROWSER_CONTROL_OWNER_RESUME_PATH
        )
        assert engine.requests[1][2] == {
            "app_id": P01_APP_ID, "continuation_ref": CONT,
        }
        assert "z" * 40 not in decision.text
        assert decision.headers["cache-control"].startswith("no-store")
        assert client.post(BROWSER_CONTROL_OWNER_P01_DECISION_PATH, json={
            "ticket_ref": OWNER_TICKET.ticket_ref, "decision": "approve",
        }).status_code == 404
        assert len(owner.rows()) == 1
        assert len(engine.requests) == 2
    finally:
        owner.close()


def test_signed_out_owner_cannot_request_ticket_click_or_finalize():
    client, owner, engine, _ = _setup(signed_in=False)
    try:
        for path, payload in (
            (BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH, {"continuation_ref": CONT}),
            (BROWSER_CONTROL_OWNER_P01_DECISION_PATH, {
                "ticket_ref": OWNER_TICKET.ticket_ref, "decision": "approve",
            }),
            (BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH, {
                "ticket_ref": OWNER_TICKET.ticket_ref,
            }),
        ):
            response = client.post(path, json=payload)
            assert response.status_code == 401
        assert owner.rows() == []
        assert engine.requests == []
    finally:
        owner.close()


def test_finalize_without_human_click_refused_even_with_current_signed_owner():
    client, owner, engine, _ = _setup()
    try:
        refused = client.post(BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH, json={
            "ticket_ref": OWNER_TICKET.ticket_ref,
        })
        assert refused.status_code == 503
        assert refused.json()["browser_action_executed"] is False
        assert owner.rows() == []
        assert len(engine.requests) == 1
        assert engine.requests[0][1].endswith(
            ENGINE_BROWSER_CONTROL_OWNER_RESUME_PATH
        )
    finally:
        owner.close()


@pytest.mark.parametrize("invalid", [
    lambda b: replace(b, owner_d1=b.engine_continuation_d1),
    lambda b: replace(b, ticket_loader=object()),
    lambda b: replace(b, engine_client=object()),
    lambda b: replace(b, owner_d1=object()),
    lambda b: replace(b, engine_continuation_d1=None),
])
def test_missing_or_mismatched_owner_d1_binding_is_rejected_before_routes(invalid):
    owner = OwnerDB()
    try:
        engine_d1 = MagicMock()
        loader = D1BrowserControlOwnerTicketLoader(
            owner_binding=owner, engine_continuation_binding=engine_d1,
        )
        real = PadiemAiEngineClient(
            transport=_Engine(), app_id=P01_APP_ID,
            caller_id="b54.browser.p01", credential="z" * 40,
        )
        bundle = BrowserControlOwnerP01Composition(
            owner_d1=owner, engine_continuation_d1=engine_d1,
            ticket_loader=loader, engine_client=real,
        )
        with pytest.raises((TypeError, ValueError)):
            create_app(
                settings=_google_settings(), d1_binding=MagicMock(),
                control_plane_identity_authority=_authority(),
                identity_shadow_store=_identity_store(),
                browser_control_owner_p01=invalid(bundle),
            )
    finally:
        owner.close()


def test_product_worker_has_no_browser_owner_p01_bundle_or_route_activation():
    from pathlib import Path

    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text(
        encoding="utf-8",
    )
    assert "browser_control_owner_p01=" not in worker
    assert "BROWSER_CONTROL_OWNER_P01_PRODUCT_COMPOSITION_WIRED = False" in (
        Path(__file__).resolve().parents[1]
        / "app/browser_control_owner_p01_composition.py"
    ).read_text(encoding="utf-8")
