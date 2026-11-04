"""답변 시간 예산: the Engine enforces the caller's execution budget.

Chat now sends the time left inside the front door's 60s answer window as
``execution_context.timeout_seconds``. The Engine must stop the run at that
budget (which cancels the B14 chain inside it) and answer with the bounded
``upstream_timeout`` code, not keep the browser waiting until an edge page wins.
"""
from __future__ import annotations

import asyncio

import app.orchestration_identity_service as identity_mod
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from tests.test_5015_chat_pc_wire_admission import (
    AllowingAdapter,
    CHAT_APP_ID,
    DRIVES_PAYLOAD,
    _binding,
)


class _SlowRunner:
    """A run that never finishes before the budget."""

    def __init__(self, *, runtime, idempotency=None) -> None:
        self._runtime = runtime

    async def run(self, request):
        await asyncio.sleep(60)
        raise AssertionError("the execution budget must cancel this run")


def _service() -> AdmissionBoundOrchestrationEngineService:
    return AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: object(),
        b14_service_bound=True,
        admission_adapter=AllowingAdapter(),
        tool_binding_resolver=lambda app_id: _binding() if app_id == CHAT_APP_ID else None,
        pc_query_step_driver_factory=lambda *args, **kwargs: "owner_pc_step_driver",
    )


def test_the_engine_stops_at_the_execution_budget(monkeypatch):
    monkeypatch.setattr(identity_mod, "OrchestrationRunner", _SlowRunner)
    payload = dict(DRIVES_PAYLOAD)
    payload["execution_context"] = {
        "trace_id": payload.get("trace_id") or "tr_6818_execution_budget",
        "timeout_seconds": 1.0,
    }
    response = asyncio.run(_service().orchestrate_payload(payload))
    assert response.status_code == 504
    assert response.body["error"]["code"] == "upstream_timeout"
