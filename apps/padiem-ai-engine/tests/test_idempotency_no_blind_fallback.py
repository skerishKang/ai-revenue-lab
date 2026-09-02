"""Regression tests for idempotency adapter failure handling.

These tests intentionally do not provision a D1 binding or mutate Worker config.
They lock the Engine invariant that adapter failures must surface as safe
Engine errors and must never fall back to blind execution or rerun.
"""

from __future__ import annotations

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionRequest,
    ExecutionResult,
    RunMetadata,
    RunStatus,
)

from app.orchestration_service import OrchestrationEngineService


class CountingRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="runtime answer",
            route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_idem_failure",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class BeginFailureAdapter:
    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str):
        raise RuntimeError("durable idempotency begin unavailable")

    async def complete(self, **kwargs) -> None:
        raise AssertionError("complete must not be called when begin fails")


class CompleteFailureAdapter:
    def __init__(self) -> None:
        self.begin_count = 0
        self.complete_count = 0

    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str):
        self.begin_count += 1
        return None

    async def complete(self, **kwargs) -> None:
        self.complete_count += 1
        raise RuntimeError("durable idempotency complete unavailable")


def _payload(idempotency_key: str = "idem_fail_safe") -> dict:
    return {
        "app_id": "b62",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "trace_id": "tr_idem_failure",
        "execution_context": {
            "trace_id": "tr_idem_failure",
            "idempotency_key": idempotency_key,
            "timeout_seconds": 15.0,
        },
    }


async def test_begin_adapter_failure_fails_closed_without_runtime_fallback() -> None:
    runtime = CountingRuntime()
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=BeginFailureAdapter(),
    )

    response = await service.orchestrate_payload(_payload())

    assert response.status_code == 500
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "engine_internal_error"
    assert runtime.call_count == 0


async def test_complete_adapter_failure_returns_safe_error_without_rerun() -> None:
    runtime = CountingRuntime()
    adapter = CompleteFailureAdapter()
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    response = await service.orchestrate_payload(_payload("idem_complete_failure"))

    assert response.status_code == 500
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "engine_internal_error"
    assert adapter.begin_count == 1
    assert adapter.complete_count == 1
    assert runtime.call_count == 1


def test_no_blind_fallback_slice_does_not_mutate_production_config() -> None:
    from pathlib import Path

    engine_root = Path(__file__).resolve().parents[1]
    wrangler_source = (engine_root / "wrangler.toml").read_text(encoding="utf-8")

    assert "ENGINE_IDEMPOTENCY" not in wrangler_source
    assert "[[d1_databases]]" not in wrangler_source
