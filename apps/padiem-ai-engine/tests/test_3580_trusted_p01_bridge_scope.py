"""#3580 Core/Engine exact run/scope P01 boundary: no browser run override."""
from __future__ import annotations

from dataclasses import replace

import pytest

from padiem_ai_core import OrchestrationRunner
from app.approval_smoke_binding import (
    APPROVAL_SMOKE_APP_ID, APPROVAL_SMOKE_AUTH_SCOPE,
    build_approval_smoke_binding,
)
from test_approval_smoke_binding import (
    _ProviderBombRuntime, _run_payload, _service,
)


@pytest.mark.asyncio
async def test_server_trusted_run_identity_and_registered_scope_reach_core_pause():
    binding = build_approval_smoke_binding()
    service, _store = _service(binding)
    payload = _run_payload(binding)
    built = service._orchestrate_request_from_payload(payload)
    assert not hasattr(built, "status_code")
    _, internal_request, _, _ = built
    assert internal_request.trusted_agent_bridge_run_id is None
    trusted = replace(
        internal_request, trusted_agent_bridge_run_id="run_exact_broker_3580"
    )
    result = await OrchestrationRunner(runtime=_ProviderBombRuntime()).run(trusted)
    pause = result.approval_pause
    assert pause is not None
    assert pause.run_id == "run_exact_broker_3580"
    assert pause.approval_scope == (APPROVAL_SMOKE_AUTH_SCOPE,)
    assert pause.tool_id


@pytest.mark.asyncio
async def test_browser_payload_cannot_supply_trusted_broker_run_id():
    binding = build_approval_smoke_binding()
    service, store = _service(binding)
    payload = _run_payload(binding)
    payload["trusted_agent_bridge_run_id"] = "run_attacker_controls"
    denied = await service.orchestrate_payload(payload)
    assert denied.status_code == 400
    assert denied.body["error"]["code"] == "invalid_request"
    # Ordinary public requests still get server-generated run ids.
    payload.pop("trusted_agent_bridge_run_id")
    paused = await service.orchestrate_payload(payload)
    assert paused.status_code == 200
    continuation_ref = paused.body["orchestration"]["continuation_ref"]
    record = store.resolve(
        app_id=APPROVAL_SMOKE_APP_ID, continuation_ref=continuation_ref,
    )
    assert record.pause.run_id != "run_attacker_controls"
    assert record.pause.run_id.startswith("bridge_run_")
    assert record.pause.approval_scope == (APPROVAL_SMOKE_AUTH_SCOPE,)
