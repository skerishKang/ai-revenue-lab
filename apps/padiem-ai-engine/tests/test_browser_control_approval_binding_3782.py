"""#3782: real Core browser P01 pause, inert handler, no Worker activation."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.browser_control_approval_binding import (
    BROWSER_CONTROL_BROWSER_ACTION_PROVIDER_WIRED,
    BROWSER_CONTROL_TOOL_BINDING_WIRED,
    BROWSER_P01_AGENT_ID,
    BROWSER_P01_APP_ID,
    BROWSER_P01_CANONICAL_TOOL_ID,
    build_inert_browser_control_approval_binding,
)
from app.orchestration_service import InMemoryContinuationStore
from app.tool_execution_service import ToolExecutionEngineService
from padiem_ai_core import ApprovalPolicy
from padiem_ai_core.agent_approval import tool_invocation_digest
from padiem_ai_core.tool_runtime import ToolInvocation, ToolRuntimeError

ARGS = {
    "browser_session_ref": "browser.3782",
    "run_ref": "run.3782",
    "workspace_ref": "workspace.3782",
    "owner_ref": "owner.3782",
    "device_id": "device.3782",
    "origin_scope": "https://example.org",
    "allowed_action_classes": ["click", "focus"],
    "ttl_seconds": 60,
    "max_actions": 1,
}


def tool_binding():
    return build_inert_browser_control_approval_binding()


def execute_request(**arguments):
    return {
        "app_id": BROWSER_P01_APP_ID,
        "agent_id": BROWSER_P01_AGENT_ID,
        "tool_id": BROWSER_P01_CANONICAL_TOOL_ID,
        "arguments": {**ARGS, **arguments},
    }


def build_engine():
    binding = tool_binding()
    store = InMemoryContinuationStore()
    engine = ToolExecutionEngineService(
        tool_binding_resolver=lambda app_id: binding if app_id == BROWSER_P01_APP_ID else None,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=store,
    )
    return binding, store, engine


def test_canonical_core_runtime_raises_real_approval_block_and_never_executes():
    binding = tool_binding()
    auth = binding.resolve_authority(BROWSER_P01_AGENT_ID)
    entry = binding.resolve_tool(BROWSER_P01_CANONICAL_TOOL_ID)
    assert entry.runtime_tool_id == "browser.control"
    assert entry.runtime_spec.approval_policy is ApprovalPolicy.USER_CONFIRMATION
    inv = ToolInvocation(tool_id="browser.control", arguments=ARGS)
    with pytest.raises(ToolRuntimeError) as error:
        asyncio.run(binding.tool_runtime.execute(
            inv, auth.compiled.runtime_profile, auth.authorization,
        ))
    assert error.value.code == "tool_user_confirmation_required"


def test_actual_engine_core_execution_issues_browser_scoped_pause():
    _, store, engine = build_engine()
    response = asyncio.run(engine.execute_payload(execute_request()))
    assert response.status_code == 202, response.body
    pause_wire = response.body["tool"]["approval_pause"]
    assert pause_wire["approval_scope"] == ["browser.control"]
    assert pause_wire["tool_id"] == "browser.control"
    # Core deliberately keeps the invocation digest server-side.
    assert "invocation_sha256" not in pause_wire
    assert tool_invocation_digest(next(iter(engine._pending.values())).invocation) == (
        tool_invocation_digest(ToolInvocation(tool_id="browser.control", arguments=ARGS))
    )
    assert response.body["tool"]["status"] == "paused"
    assert len(engine._pending) == 1
    assert store is not None


def test_approved_response_fails_closed_with_no_d1_receipts_or_execution():
    _, _store, engine = build_engine()
    paused = asyncio.run(engine.execute_payload(execute_request()))
    assert paused.status_code == 202
    p = paused.body["tool"]["approval_pause"]
    submit = {
        "app_id": BROWSER_P01_APP_ID,
        "continuation_ref": paused.body["tool"]["continuation_ref"],
        "decision": {
            "decision_id": "dec.browser.3782",
            "pause_id": p["continuation_id"],
            "outcome": "approved",
            "authority_ref": "test.firstparty",
            "evidence_ref": "test.p01",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    response = asyncio.run(engine.resume_payload(submit))
    assert response.status_code == 503, response.body
    assert response.body["error"]["code"] == "browser_control_p01_receipt_unavailable"
    assert len(engine._pending) == 1


@pytest.mark.parametrize("drift", [
    {"allowed_action_classes": ["navigate"]},
    {"allowed_action_classes": ["click", "click"]},
    {"allowed_action_classes": ["focus", "click"]},
    {"origin_scope": "http://example.org"},
    {"origin_scope": "https://example.org/path"},
    {"origin_scope": "https://user:pass@example.org"},
    {"origin_scope": "https://example.org?token=secret"},
    {"origin_scope": "https://example.org#fragment"},
    {"ttl_seconds": 901},
    {"ttl_seconds": True},
    {"max_actions": 0},
    {"max_actions": False},
    {"device_id": ""},
    {"browser_session_ref": "invalid space"},
    {"extra_parameter": "not permitted"},
])
def test_canonical_core_schema_refuses_widened_browser_request(drift):
    _, _store, engine = build_engine()
    response = asyncio.run(engine.execute_payload(execute_request(**drift)))
    assert response.status_code != 202
    assert engine._pending == {}


def test_even_if_core_authorization_was_bypassed_handler_cannot_execute_browser():
    binding = tool_binding()
    authority = binding.resolve_authority(BROWSER_P01_AGENT_ID)
    granted = replace(
        authority.authorization,
        user_confirmed_tools=("browser.control",),
    )
    inv = ToolInvocation(tool_id="browser.control", arguments=ARGS)
    with pytest.raises(ToolRuntimeError):
        asyncio.run(binding.tool_runtime.execute(
            inv, authority.compiled.runtime_profile, granted,
        ))


def test_no_product_registration_or_browser_action_authority():
    assert BROWSER_CONTROL_TOOL_BINDING_WIRED is False
    assert BROWSER_CONTROL_BROWSER_ACTION_PROVIDER_WIRED is False


def test_kagent_core_tool_invocation_digest_parity_on_windows_when_available():
    try:
        from kagent.browser_control_lease_authority import BrowserControlLeaseRequest
    except ImportError:
        pytest.skip("KAgent is not installed in standalone Engine runtime")
    req = BrowserControlLeaseRequest(
        browser_session_ref=ARGS["browser_session_ref"], run_ref=ARGS["run_ref"],
        workspace_ref=ARGS["workspace_ref"], owner_ref=ARGS["owner_ref"],
        device_id=ARGS["device_id"], origin_scope=ARGS["origin_scope"],
        allowed_action_classes=tuple(ARGS["allowed_action_classes"]),
        ttl_seconds=ARGS["ttl_seconds"], max_actions=ARGS["max_actions"],
    )
    assert req.approval_invocation_sha256() == tool_invocation_digest(
        ToolInvocation(tool_id="browser.control", arguments=ARGS)
    )


@pytest.mark.parametrize("missing_field", [
    "browser_session_ref", "run_ref", "workspace_ref", "owner_ref",
    "device_id", "origin_scope", "allowed_action_classes",
    "ttl_seconds", "max_actions",
])
def test_missing_session_dimension_refuses_before_any_approval_prompt(missing_field):
    _, _, engine = build_engine()
    wire = execute_request()
    wire["arguments"].pop(missing_field)
    response = asyncio.run(engine.execute_payload(wire))
    assert response.status_code != 202
    assert engine._pending == {}


def test_browser_approval_preflight_does_not_change_other_engine_tool_authorization():
    """No product capability or authority grant is created by this fixture."""
    assert BROWSER_CONTROL_TOOL_BINDING_WIRED is False
    assert BROWSER_CONTROL_BROWSER_ACTION_PROVIDER_WIRED is False
    _, _, engine = build_engine()
    unknown = asyncio.run(engine.execute_payload({
        "app_id": "other.app",
        "agent_id": BROWSER_P01_AGENT_ID,
        "tool_id": BROWSER_P01_CANONICAL_TOOL_ID,
        "arguments": ARGS,
    }))
    assert unknown.status_code != 202
    assert engine._pending == {}
