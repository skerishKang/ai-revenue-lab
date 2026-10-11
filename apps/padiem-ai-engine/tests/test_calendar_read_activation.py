from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.calendar_capability import CalendarCapability
from app.calendar_read_activation import (
    CALENDAR_ACTIVATION_CALLER_APP_ID,
    CalendarReadActivationService,
    CloudflareCalendarBindingClient,
    CloudflareConnectorWorkspaceClient,
    parse_calendar_activation_request,
)
from app.connector_bindings import (
    CALENDAR_AGENT_ID,
    CALENDAR_REFERENCE_APP_ID,
    CalendarGrant,
)
from app.service import ServiceContractError


SESSION = "sess_calendar_activation_1"
WORKSPACE = "workspace:calendar:1"
BINDING = "binding:calendar:1"
ACTOR = "actor:calendar:1"


def run(coro):
    return asyncio.run(coro)


class WorkspaceBinding:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def resolve_connector_workspace(self, payload):
        self.calls.append(payload)
        return self.result


class OAuthBinding:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def select_calendar_binding(self, payload):
        self.calls.append(payload)
        return self.result


class GrantStore:
    def __init__(self):
        self.calls = []

    async def activate_calendar_read_grant(self, *, binding_ref, actor_ref):
        self.calls.append((binding_ref, actor_ref))
        return CalendarGrant(
            app_id=CALENDAR_REFERENCE_APP_ID,
            canonical_agent_id=CALENDAR_AGENT_ID,
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            granted_capabilities=(CalendarCapability.READ,),
        )


def test_request_accepts_only_server_contract_fields() -> None:
    body = json.dumps({
        "app_id": CALENDAR_ACTIVATION_CALLER_APP_ID,
        "session_id": SESSION,
    }).encode()
    assert parse_calendar_activation_request(body) == SESSION

    for payload in (
        {},
        {"app_id": CALENDAR_ACTIVATION_CALLER_APP_ID},
        {"app_id": CALENDAR_ACTIVATION_CALLER_APP_ID, "session_id": SESSION, "workspace_ref": WORKSPACE},
        {"app_id": CALENDAR_ACTIVATION_CALLER_APP_ID, "session_id": SESSION, "binding_ref": BINDING},
        {"app_id": CALENDAR_ACTIVATION_CALLER_APP_ID, "session_id": SESSION, "capabilities": ["read"]},
    ):
        with pytest.raises(ServiceContractError):
            parse_calendar_activation_request(json.dumps(payload).encode())


def test_workspace_is_resolved_from_session_only() -> None:
    binding = WorkspaceBinding({
        "ok": True,
        "workspace": {"present": True, "workspace_ref": WORKSPACE},
    })
    client = CloudflareConnectorWorkspaceClient(binding)

    assert run(client.resolve_connector_workspace(session_id=SESSION)) == WORKSPACE
    assert binding.calls == [{"session_id": SESSION}]


def test_missing_workspace_fails_closed() -> None:
    client = CloudflareConnectorWorkspaceClient(
        WorkspaceBinding({"ok": True, "workspace": {"present": False}})
    )
    with pytest.raises(ServiceContractError) as exc:
        run(client.resolve_connector_workspace(session_id=SESSION))
    assert exc.value.code == "calendar_activation_workspace_unavailable"


def test_calendar_binding_selection_is_workspace_bound_and_narrow() -> None:
    binding = OAuthBinding({
        "ok": True,
        "selection": {
            "status": "resolved",
            "connector_id": "google-calendar",
            "workspace_ref": WORKSPACE,
            "binding_ref": BINDING,
            "actor_ref": ACTOR,
        },
    })
    client = CloudflareCalendarBindingClient(binding)

    assert run(client.select_calendar_binding(workspace_ref=WORKSPACE)) == (BINDING, ACTOR)
    assert binding.calls == [{"workspace_ref": WORKSPACE}]


def test_binding_selector_rejects_identity_widening() -> None:
    client = CloudflareCalendarBindingClient(OAuthBinding({
        "ok": True,
        "selection": {
            "status": "resolved",
            "connector_id": "google-calendar",
            "workspace_ref": WORKSPACE,
            "binding_ref": BINDING,
            "actor_ref": ACTOR,
            "account_ref": "account:must-not-cross",
        },
    }))
    with pytest.raises(ServiceContractError) as exc:
        run(client.select_calendar_binding(workspace_ref=WORKSPACE))
    assert exc.value.code == "calendar_binding_selection_unavailable"


def test_not_connected_calendar_fails_before_grant_write() -> None:
    client = CloudflareCalendarBindingClient(OAuthBinding({
        "ok": True,
        "selection": {
            "status": "not_connected",
            "connector_id": "google-calendar",
            "workspace_ref": WORKSPACE,
        },
    }))
    with pytest.raises(ServiceContractError) as exc:
        run(client.select_calendar_binding(workspace_ref=WORKSPACE))
    assert exc.value.code == "calendar_not_connected"


def test_activation_returns_bounded_status_without_private_identity() -> None:
    workspace = CloudflareConnectorWorkspaceClient(WorkspaceBinding({
        "ok": True,
        "workspace": {"present": True, "workspace_ref": WORKSPACE},
    }))
    oauth = CloudflareCalendarBindingClient(OAuthBinding({
        "ok": True,
        "selection": {
            "status": "resolved",
            "connector_id": "google-calendar",
            "workspace_ref": WORKSPACE,
            "binding_ref": BINDING,
            "actor_ref": ACTOR,
        },
    }))
    store = GrantStore()
    service = CalendarReadActivationService(
        workspace_client=workspace,
        binding_client=oauth,
        grant_store=store,
    )

    response = run(service.activate(session_id=SESSION))

    assert response.status_code == 200
    assert response.body["calendar_read_grant"] == "active"
    assert response.body["calendar_write_authorized"] is False
    rendered = json.dumps(response.body, sort_keys=True)
    for secretish in (SESSION, WORKSPACE, BINDING, ACTOR):
        assert secretish not in rendered
    assert store.calls == [(BINDING, ACTOR)]
