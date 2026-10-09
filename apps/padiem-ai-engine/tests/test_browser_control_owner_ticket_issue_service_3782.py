"""#3782 real Engine pending-owner-ticket request service: no browser grant."""
from __future__ import annotations

import asyncio
import json

import pytest
from app.browser_control_owner_p01_ticket_issuer import (
    AuthenticatedEngineBrowserP01TicketIssuer,
)
from app.browser_control_owner_ticket_issue_service import (
    BROWSER_P01_TICKET_ISSUE_PATH,
    BROWSER_P01_TICKET_ISSUE_ROUTE_WIRED,
    BrowserControlOwnerTicketIssueEngineService,
)
from test_browser_control_owner_p01_ticket_issuer_3782 import (
    _OwnerD1,
    _SessionAuthority,
)
from test_browser_control_p01_receipt_3782 import APP_ID, CONT_REF, setup

NORMAL = {
    "app_id": APP_ID,
    "continuation_ref": CONT_REF,
    "product_user_id": "usr.real.test",
    "auth_session_ref": "live.session.3782",
}


def _setup():
    engine, service, _receipts, _request = setup(with_human_source=False)
    owner = _OwnerD1()
    issuer = AuthenticatedEngineBrowserP01TicketIssuer(
        engine_store=service._continuation_store,
        owner_binding=owner,
        session_authority=_SessionAuthority(),
    )
    return engine, owner, BrowserControlOwnerTicketIssueEngineService(issuer=issuer)


def _call(service, body=None, *, method="POST", path=BROWSER_P01_TICKET_ISSUE_PATH,
          content_type="application/json"):
    return asyncio.run(service.handle(
        method=method, path=path, content_type=content_type,
        body=json.dumps(NORMAL if body is None else body).encode("utf-8"),
    ))


def test_live_service_issues_only_pending_ticket_from_active_engine_record():
    engine, owner, service = _setup()
    try:
        assert BROWSER_P01_TICKET_ISSUE_ROUTE_WIRED is False
        result = _call(service)
        assert result.status_code == 200
        assert result.body == {
            "ok": True,
            "ticket_ref": result.body["ticket_ref"],
            "owner_approval_recorded": False,
            "browser_action_executed": False,
        }
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_decisions"
        ).fetchone()[0] == 0
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 1
        replay = _call(service)
        assert replay.status_code == 503
    finally:
        owner.db.close()
        engine.db.close()


@pytest.mark.parametrize("body", [
    {**NORMAL, "tool_id": "process.execute"},
    {**NORMAL, "approved": True},
    {**NORMAL, "browser_action": {"action": "click"}},
    {**NORMAL, "subject_id": "other.user"},
    {**NORMAL, "original_admission_decision_id": "fake"},
    {**NORMAL, "invocation_sha256": "a" * 64},
    {**NORMAL, "product_user_id": "some other user"},
    {**NORMAL, "continuation_ref": "none"},
    {k: v for k, v in NORMAL.items() if k != "auth_session_ref"},
    {},
    [],
])
def test_client_cannot_assert_tool_scope_owner_approval_or_original_run(body):
    engine, owner, service = _setup()
    try:
        result = _call(service, body)
        assert result.status_code in (422, 503)
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


@pytest.mark.parametrize("kwargs,expected", [
    ({"method": "GET"}, 405),
    ({"path": "/internal/v1/execute"}, 405),
    ({"content_type": "text/plain"}, 415),
])
def test_private_service_exact_method_path_and_media_type(kwargs, expected):
    engine, owner, service = _setup()
    try:
        result = _call(service, **kwargs)
        assert result.status_code == expected
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


def test_worker_composition_remains_unwired_and_existing_auth_gate_is_reused():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "worker_identity.py").read_text(encoding="utf-8")
    assert "if path == BROWSER_P01_TICKET_ISSUE_PATH:" in source
    assert "legacy_worker._authenticate_non_health_request(" in source
    assert "if services.browser_p01_ticket_issue is None:" in source
    assert "browser_ticket_issuer_unavailable" in source
    assert "browser_p01_ticket_issue=" not in source
    assert "BROWSER_P01_TICKET_ISSUE_ROUTE_WIRED = False" in (
        (repo_root / "app/browser_control_owner_ticket_issue_service.py")
        .read_text(encoding="utf-8")
    )
