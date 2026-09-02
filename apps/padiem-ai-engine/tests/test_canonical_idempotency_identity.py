"""Regression coverage for canonical logical-execution idempotency identity."""

from __future__ import annotations

from copy import deepcopy

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
)

from app.idempotency_identity import (
    CanonicalFingerprintIdempotencyAdapter,
    reset_canonical_idempotency_fingerprint,
    set_canonical_idempotency_fingerprint,
)
from app.orchestration_idempotency_service import CanonicalIdempotencyOrchestrationEngineService


class RecordingDelegate:
    def __init__(self) -> None:
        self.begin_fingerprints: list[str] = []
        self.complete_fingerprints: list[str] = []

    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str):
        self.begin_fingerprints.append(request_fingerprint)
        return None

    async def complete(self, *, app_id: str, idempotency_key: str, request_fingerprint: str, result):
        self.complete_fingerprints.append(request_fingerprint)


async def test_adapter_replaces_legacy_partial_fingerprint_only_inside_canonical_scope() -> None:
    delegate = RecordingDelegate()
    adapter = CanonicalFingerprintIdempotencyAdapter(delegate)
    legacy = "1" * 64
    canonical = "a" * 64

    await adapter.begin(app_id="b62", idempotency_key="idem_scope", request_fingerprint=legacy)
    assert delegate.begin_fingerprints == [legacy]

    token = set_canonical_idempotency_fingerprint(canonical)
    try:
        await adapter.begin(app_id="b62", idempotency_key="idem_scope", request_fingerprint=legacy)
        await adapter.complete(
            app_id="b62",
            idempotency_key="idem_scope",
            request_fingerprint=legacy,
            result={"ok": True},
        )
    finally:
        reset_canonical_idempotency_fingerprint(token)

    assert delegate.begin_fingerprints[-1] == canonical
    assert delegate.complete_fingerprints[-1] == canonical


class CountingRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="canonical answer",
            route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_canonical_idem",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class ReplayAdapter:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], tuple[str, ExecutionResult | None]] = {}

    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str):
        key = (app_id, idempotency_key)
        record = self.records.get(key)
        if record is None:
            self.records[key] = (request_fingerprint, None)
            return None
        existing_fingerprint, result = record
        if existing_fingerprint != request_fingerprint:
            raise IdempotencyConflictError("conflicting logical execution")
        return result

    async def complete(self, *, app_id: str, idempotency_key: str, request_fingerprint: str, result):
        assert isinstance(result, ExecutionResult)
        self.records[(app_id, idempotency_key)] = (request_fingerprint, result)

    async def commit(self, **kwargs):
        await self.complete(**kwargs)

    async def abort(self, *, app_id: str, idempotency_key: str, reason: str | None = None):
        self.records.pop((app_id, idempotency_key), None)


def _payload() -> dict:
    return {
        "app_id": "b62",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks safely",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
            "required_capabilities": ["chat"],
            "model_policy": {"mode": "balanced"},
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "session_id": "session:canonical_1",
        "additional_system_context": "Project alpha context",
        "trace_id": "tr_canonical_idem",
        "execution_context": {
            "trace_id": "tr_canonical_idem",
            "idempotency_key": "idem_canonical_1",
            "timeout_seconds": 15.0,
        },
        "subject_id": "subject:alpha",
        "max_retries": 2,
        "require_evidence": False,
        "require_verification": False,
    }


def _service() -> tuple[CanonicalIdempotencyOrchestrationEngineService, CountingRuntime]:
    runtime = CountingRuntime()
    service = CanonicalIdempotencyOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=ReplayAdapter(),
    )
    return service, runtime


async def test_exact_logical_request_replays_without_second_runtime_call() -> None:
    service, runtime = _service()
    payload = _payload()

    first = await service.orchestrate_payload(payload)
    second = await service.orchestrate_payload(deepcopy(payload))

    assert first.status_code == 200
    assert second.status_code == 200
    assert runtime.call_count == 1
    assert second.body["orchestration"]["events"][-1]["metadata"]["replay"] is True


async def test_same_logical_request_with_new_trace_still_replays() -> None:
    service, runtime = _service()
    original = _payload()
    retry = deepcopy(original)
    retry["trace_id"] = "tr_canonical_retry"
    retry["execution_context"]["trace_id"] = "tr_canonical_retry"

    first = await service.orchestrate_payload(original)
    second = await service.orchestrate_payload(retry)

    assert first.status_code == 200
    assert second.status_code == 200
    assert runtime.call_count == 1
    assert second.body["orchestration"]["events"][-1]["metadata"]["replay"] is True


async def test_same_key_rejects_material_logical_execution_changes_before_rerun() -> None:
    mutations = [
        lambda value: value.__setitem__("subject_id", "subject:beta"),
        lambda value: value.__setitem__("session_id", "session:canonical_2"),
        lambda value: value.__setitem__("additional_system_context", "Project beta context"),
        lambda value: value["agent"].__setitem__("system_instruction", "Execute a different policy"),
        lambda value: value["agent"].__setitem__("required_capabilities", ["chat", "tools"]),
        lambda value: value["agent"].__setitem__("model_policy", {"mode": "deep"}),
        lambda value: value["execution_context"].__setitem__("timeout_seconds", 20.0),
        lambda value: value.__setitem__(
            "agent_plan",
            {
                "agent_id": "agent:padiem:orchestrator_1@1",
                "steps": [
                    {
                        "step_id": "step_1",
                        "objective": "Use a materially different plan",
                        "tool_id": None,
                        "depends_on": [],
                    }
                ],
            },
        ),
        lambda value: value.__setitem__(
            "recovery_policy",
            {
                "retryable_driver_codes": ["upstream_timeout"],
                "max_retries_per_step": 2,
            },
        ),
        lambda value: value.__setitem__("max_retries", 3),
        lambda value: value.__setitem__("require_evidence", True),
        lambda value: value.__setitem__("require_verification", True),
    ]

    for mutate in mutations:
        service, runtime = _service()
        original = _payload()
        changed = deepcopy(original)
        mutate(changed)

        first = await service.orchestrate_payload(original)
        conflict = await service.orchestrate_payload(changed)

        assert first.status_code == 200
        assert conflict.status_code == 409
        assert conflict.body["error"]["code"] == "idempotency_conflict"
        assert runtime.call_count == 1
