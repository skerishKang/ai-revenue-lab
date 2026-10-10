"""#3580 genuine Core/Engine approval + trusted, server-only run correlation."""
from __future__ import annotations

from dataclasses import replace

import pytest

from padiem_ai_core import OrchestrationRunner
from app.approval_smoke_binding import (
    APPROVAL_SMOKE_AGENT_ID, APPROVAL_SMOKE_APP_ID,
    APPROVAL_SMOKE_AUTH_SCOPE, APPROVAL_SMOKE_RUNTIME_TOOL_ID,
    build_approval_smoke_binding,
)
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.orchestration_continuation import InMemoryContinuationStore
from app.orchestration_service import OrchestrationEngineService


class _ProviderBombRuntime:
    async def run(self, _request):
        raise AssertionError("provider/fallback runtime is forbidden in P01 smoke")


def _service(binding):
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda _app_id: _ProviderBombRuntime(),
        b14_service_bound=True, continuation_store=store,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        tool_binding_resolver=lambda app_id: (
            binding if app_id == APPROVAL_SMOKE_APP_ID else None
        ),
    )
    return service, store


def _payload(binding):
    authority = binding.resolve_authority(APPROVAL_SMOKE_AGENT_ID)
    profile = authority.compiled.runtime_profile
    return {
        "app_id": APPROVAL_SMOKE_APP_ID,
        "agent": {
            "id": profile.id,
            "title": profile.title,
            "description": profile.description,
            "system_instruction": profile.system_instruction,
            "task_type": profile.task_type,
            "optimize_for": profile.optimize_for,
            "max_tokens": profile.max_tokens,
            "model_policy": {"model": "test/provider-free"},
        },
        "messages": [{"role": "user", "content": "P01 user confirmation"}],
        "trace_id": "trace_hark_3580_bridge",
        "execution_context": {
            "trace_id": "trace_hark_3580_bridge", "timeout_seconds": 5.0,
        },
        "agent_plan": {
            "agent_id": APPROVAL_SMOKE_AGENT_ID,
            "steps": [{
                "step_id": "step_1",
                "objective": "Confirm canonical scoped ToolRuntime step",
                "tool_id": APPROVAL_SMOKE_RUNTIME_TOOL_ID,
            }],
        },
        "tool_arguments": {"step_1": {"nonce": "hark-test-3580"}},
        "subject_id": "subject:approval-smoke",
        "require_evidence": False, "require_verification": False,
    }


@pytest.mark.asyncio
async def test_server_trusted_run_identity_and_registered_scope_reach_core_pause():
    binding = build_approval_smoke_binding()
    service, _store = _service(binding)
    built = service._orchestrate_request_from_payload(_payload(binding))
    assert not hasattr(built, "status_code")
    _, internal_request, _, _ = built
    assert internal_request.trusted_agent_bridge_run_id is None
    trusted = replace(internal_request, trusted_agent_bridge_run_id="run_exact_broker_3580")
    result = await OrchestrationRunner(runtime=_ProviderBombRuntime()).run(trusted)
    pause = result.approval_pause
    assert pause is not None
    assert pause.run_id == "run_exact_broker_3580"
    assert pause.approval_scope == (APPROVAL_SMOKE_AUTH_SCOPE,)
    assert pause.tool_id == APPROVAL_SMOKE_RUNTIME_TOOL_ID


@pytest.mark.asyncio
async def test_browser_payload_cannot_supply_trusted_broker_run_id():
    binding = build_approval_smoke_binding()
    service, store = _service(binding)
    payload = _payload(binding)
    payload["trusted_agent_bridge_run_id"] = "run_attacker_controls"
    denied = await service.orchestrate_payload(payload)
    assert denied.status_code == 400
    assert denied.body["error"]["code"] == "invalid_request"

    # Ordinary public request still gets a new server-selected bridge run id.
    payload.pop("trusted_agent_bridge_run_id")
    paused = await service.orchestrate_payload(payload)
    assert paused.status_code == 200
    continuation_ref = paused.body["orchestration"]["continuation_ref"]
    record = store.resolve(app_id=APPROVAL_SMOKE_APP_ID,
                           continuation_ref=continuation_ref)
    assert record.pause.run_id != "run_attacker_controls"
    assert record.pause.run_id.startswith("bridge_run_")
    assert record.pause.approval_scope == (APPROVAL_SMOKE_AUTH_SCOPE,)
