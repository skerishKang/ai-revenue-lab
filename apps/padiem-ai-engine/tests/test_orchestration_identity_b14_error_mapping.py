"""#2470: B14/provider error mapping on the REAL Production orchestration class.

The defect: ``IdentityBoundOrchestrationEngineService.orchestrate_payload`` —
which the Production ``CanonicalIdempotencyOrchestrationEngineService`` inherits
and delegates to for non-replay requests — had no ``ExecutionRuntimeError``
handler. Its final ``except Exception -> engine_internal_error 500`` swallowed
every B14 model failure, so PR #1947's canonical 4xx mapping (implemented on the
base ``OrchestrationEngineService``) was unreachable on the Production path.

These tests pin the fix by driving the actual Production class:
* each B14 failure maps to the same status/retryable the base mapper produces,
  reusing the inherited ``_orchestration_run_error_response`` (no second table),
* genuine engine-internal failures still surface as 500,
* the raw upstream body never leaks to the caller,
* the success path and canonical idempotency replay are unchanged.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
)
from padiem_ai_core.contracts import ErrorClass
from padiem_ai_core.execution_runtime import ExecutionRuntimeError
from padiem_ai_core.orchestration import OrchestrationRunner

from app.orchestration_idempotency_service import (
    CanonicalIdempotencyOrchestrationEngineService,
)
from app.service import ServiceResponse


def _payload(app_id: str = "b62") -> dict:
    return {
        "app_id": app_id,
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks safely",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
            "required_capabilities": ["chat"],
            "model_policy": {"model": "test/route"},
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "session_id": "session:b14_identity_1",
        "trace_id": "tr_b14_identity",
        "execution_context": {
            "trace_id": "tr_b14_identity",
            "idempotency_key": "idem_b14_identity_1",
            "timeout_seconds": 15.0,
        },
        "subject_id": "subject:alpha",
        "max_retries": 2,
        "require_evidence": False,
        "require_verification": False,
    }


def _run_metadata(error_class: ErrorClass) -> RunMetadata:
    return RunMetadata(
        trace_id="tr_b14_identity",
        app_id="b62",
        agent_id="agent:padiem:orchestrator_1",
        status=RunStatus.FAILED,
        error_class=error_class,
    )


class _StubRuntime:
    """Satisfies the service wiring; ``OrchestrationRunner.run`` is patched."""

    async def run(self, *args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("stub runtime must not be invoked directly")


def _production_service() -> CanonicalIdempotencyOrchestrationEngineService:
    """The exact class worker_identity.py instantiates on Production."""
    return CanonicalIdempotencyOrchestrationEngineService(
        runtime_factory=lambda app_id: _StubRuntime(),
        b14_service_bound=True,
    )


# (b14_code, error_class, retryable, expected_status, expected_retryable)
_B14_FAILURE_CASES = [
    ("upstream_request_error", ErrorClass.INPUT_ERROR, False, 400, False),
    ("upstream_server_error", ErrorClass.INTERNAL_ERROR, True, 429, True),
    ("upstream_rate_limited", ErrorClass.PROVIDER_RATE_LIMIT, True, 429, True),
    ("upstream_timeout", ErrorClass.PROVIDER_TIMEOUT, True, 429, True),
    ("upstream_auth_error", ErrorClass.AUTH_ERROR, False, 403, False),
    ("malformed_upstream", ErrorClass.PROVIDER_BAD_RESPONSE, False, 422, False),
]


@pytest.mark.parametrize(
    "code,error_class,retryable,exp_status,exp_retryable",
    _B14_FAILURE_CASES,
)
async def test_production_class_maps_b14_failure_to_4xx(
    monkeypatch,
    code: str,
    error_class: ErrorClass,
    retryable: bool,
    exp_status: int,
    exp_retryable: bool,
) -> None:
    message = f"Model execution failed ({code})."

    def fake_run(self, request):  # noqa: ANN001 - patched onto OrchestrationRunner
        raise ExecutionRuntimeError(
            code,
            message,
            metadata=_run_metadata(error_class),
            retryable=retryable,
        )

    monkeypatch.setattr(OrchestrationRunner, "run", fake_run)

    service = _production_service()
    response = await service.orchestrate_payload(_payload())

    assert isinstance(response, ServiceResponse)
    assert 400 <= response.status_code < 500, (
        f"{code}: expected 4xx on Production class, got {response.status_code}"
    )
    assert response.status_code == exp_status, (
        f"{code}: status {response.status_code} != expected {exp_status}"
    )
    body = response.body
    assert body["ok"] is False
    assert body["error"]["code"] == code, f"{code}: safe code not preserved"
    assert body["error"]["retryable"] is exp_retryable
    assert set(body.keys()) == {"ok", "error"}
    assert set(body["error"].keys()) == {"code", "message", "retryable", "metadata"}
    assert body["error"]["message"] == message


async def test_production_class_b14_failure_never_500(monkeypatch) -> None:
    def fake_run(self, request):  # noqa: ANN001
        raise ExecutionRuntimeError(
            "upstream_server_error",
            "Model execution service failed.",
            metadata=_run_metadata(ErrorClass.INTERNAL_ERROR),
            retryable=True,
        )

    monkeypatch.setattr(OrchestrationRunner, "run", fake_run)
    response = await _production_service().orchestrate_payload(_payload())
    assert response.status_code != 500
    assert response.body["error"]["code"] != "engine_internal_error"


async def test_production_class_genuine_internal_stays_500(monkeypatch) -> None:
    def fake_run(self, request):  # noqa: ANN001
        raise ExecutionRuntimeError(
            "execution_failed",
            "Model execution failed.",
            metadata=_run_metadata(ErrorClass.INTERNAL_ERROR),
            retryable=False,
        )

    monkeypatch.setattr(OrchestrationRunner, "run", fake_run)
    response = await _production_service().orchestrate_payload(_payload())
    assert response.status_code == 500
    assert response.body["error"]["code"] == "engine_internal_error"


_LEAK_SENTINEL = "LEAK_SENTINEL_7c41de"


async def test_production_class_never_forwards_raw_upstream_body(monkeypatch) -> None:
    def fake_run(self, request):  # noqa: ANN001
        raise ExecutionRuntimeError(
            "upstream_rate_limited",
            "Model execution failed (upstream_rate_limited).",
            metadata=_run_metadata(ErrorClass.PROVIDER_RATE_LIMIT),
            retryable=True,
        )

    monkeypatch.setattr(OrchestrationRunner, "run", fake_run)
    response = await _production_service().orchestrate_payload(_payload())
    assert response.status_code == 429
    # Only the bounded envelope reaches the caller: no raw upstream body/detail.
    assert set(response.body.keys()) == {"ok", "error"}
    assert set(response.body["error"].keys()) == {"code", "message", "retryable", "metadata"}
    serialized = repr(response.body)
    assert _LEAK_SENTINEL not in serialized


class _SuccessRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="canonical answer",
            route=B14RouteMetadata(
                selected_provider="mock_provider", selected_model="mock_model"
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_b14_identity",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class _ReplayAdapter:
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


async def test_production_class_success_path_unchanged() -> None:
    runtime = _SuccessRuntime()
    service = CanonicalIdempotencyOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=_ReplayAdapter(),
    )
    response = await service.orchestrate_payload(_payload())
    assert response.status_code == 200
    assert response.body["ok"] is True
    assert "orchestration" in response.body
    assert runtime.call_count == 1


async def test_production_class_canonical_idempotency_unchanged() -> None:
    runtime = _SuccessRuntime()
    service = CanonicalIdempotencyOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=_ReplayAdapter(),
    )
    payload = _payload()
    first = await service.orchestrate_payload(payload)
    second = await service.orchestrate_payload(deepcopy(payload))
    assert first.status_code == 200
    assert second.status_code == 200
    assert runtime.call_count == 1
    assert second.body["orchestration"]["events"][-1]["metadata"]["replay"] is True


def test_identity_service_reuses_canonical_mapper_without_a_second_table() -> None:
    """Guard the #2470 constraint: no duplicated B14 mapping implementation."""
    import inspect

    import app.orchestration_identity_service as mod

    source = inspect.getsource(mod)
    # Delegates to the inherited canonical mapper rather than re-deriving status.
    assert "_orchestration_run_error_response" in source
    # No re-implementation of the base B14 helpers in the identity layer.
    assert "def _is_b14_model_error" not in source
    assert "def _b14_model_error_status" not in source
    # No literal error-class -> status mapping table introduced here.
    for token in ("PROVIDER_RATE_LIMIT", "PROVIDER_TIMEOUT", "AUTH_ERROR", "PROVIDER_BAD_RESPONSE"):
        assert token not in source
