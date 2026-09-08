from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    Evidence,
    ExecutionRequest,
    ExecutionResult,
    GroundedResearchRuntime,
    MockWebProvider,
    RunMetadata,
    RunStatus,
)

from app.web_research_activation import (
    CONFIRMATION_TOKEN,
    CURRENT_DEPLOYED_VERSION,
    DEPLOYMENT_TARGET,
    ROLLBACK_VERSION,
    ActivationError,
    ActivationEvidence,
    ReferenceParityResult,
    RollbackAnchor,
    SyntheticProbeResult,
    evaluate_activation,
    record_rollback_anchor,
    run_reference_parity_probe,
    run_synthetic_probe,
    verify_confirmation_token,
    verify_exact_main,
)
from app.web_research_service import WebResearchEngineService

APP_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MAIN = "e7453cfd10f162e2edd90dcc81309e17776a69fb"
FIXTURE_ACCEPTED_SOURCE_HEAD = "1457f201c27b21efdc86c38110048de825f53d82"


def run(coro):
    return asyncio.run(coro)


def _agent() -> dict[str, object]:
    return {
        "id": "a1-activation-agent",
        "title": "A1 activation fixture agent",
        "description": "Network-free Engine activation test agent.",
        "system_instruction": "Answer only from the grounded context.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 400,
        "model_policy": {"model": "test/route"},
    }


class RecordingExecutionRuntime:
    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        if request.agent.id == "engine-research-planner":
            answer = '{"queries":["query one","query two"]}'
        else:
            assert request.additional_system_context is not None
            answer = "grounded answer"
        return ExecutionResult(
            answer=answer,
            route=B14RouteMetadata(
                request_id="b14-request",
                selected_provider="fake-provider",
                selected_model="fake-model",
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "generated-trace",
                app_id="engine-fixture-app",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


def _service() -> tuple[WebResearchEngineService, RecordingExecutionRuntime]:
    execution = RecordingExecutionRuntime()
    web_provider = MockWebProvider()
    return (
        WebResearchEngineService(
            research_runtime_factory=lambda _app_id: GroundedResearchRuntime(web_provider),
            execution_runtime_factory=lambda _app_id: execution,
            b14_service_bound=True,
        ),
        execution,
    )


# --- activation gate ---------------------------------------------------------


def test_confirmation_token_is_owner_phrase() -> None:
    assert CONFIRMATION_TOKEN == "ACTIVATE_ENGINE_A1_WEB_RESEARCH"


def test_verify_confirmation_token_accepts_exact_token() -> None:
    verify_confirmation_token(CONFIRMATION_TOKEN)


def test_verify_confirmation_token_fails_closed_on_other_token() -> None:
    with pytest.raises(ActivationError) as excinfo:
        verify_confirmation_token("ACTIVATE_ENGINE_A2_TOOL_RUNTIME")
    assert excinfo.value.code == "activation_not_authorized"


def test_verify_confirmation_token_fails_closed_on_non_string() -> None:
    with pytest.raises(ActivationError) as excinfo:
        verify_confirmation_token(None)  # type: ignore[arg-type]
    assert excinfo.value.code == "activation_not_authorized"


def test_verify_exact_main_accepts_sha_shape() -> None:
    verify_exact_main(FIXTURE_MAIN)


def test_verify_exact_main_fails_closed_on_bad_shape() -> None:
    for bad in ("not-a-sha", "ABCD" * 16, ""):
        with pytest.raises(ActivationError) as excinfo:
            verify_exact_main(bad)
        assert excinfo.value.code == "invalid_sha"


def test_rollback_anchor_records_audited_versions() -> None:
    anchor = record_rollback_anchor()
    assert anchor.deployment_target == DEPLOYMENT_TARGET
    assert anchor.current_deployed_version == CURRENT_DEPLOYED_VERSION
    assert anchor.rollback_version == ROLLBACK_VERSION
    assert anchor.config_binding_diff == "none"
    assert anchor.secret_name_diff == "none"
    public = anchor.to_public_dict()
    assert public["current_deployed_version"] == CURRENT_DEPLOYED_VERSION
    assert public["rollback_version"] == ROLLBACK_VERSION
    serialized = json.dumps(public)
    assert "PRIVATE" not in serialized


# --- synthetic probe ---------------------------------------------------------


def test_synthetic_probe_search_returns_valid_structure() -> None:
    svc, execution = _service()
    result = run(run_synthetic_probe(svc, operation="search"))
    assert result.ok is True
    assert result.operation == "search"
    assert result.error_code is None
    assert len(execution.requests) == 1


def test_synthetic_probe_fetch_returns_valid_structure() -> None:
    svc, execution = _service()
    result = run(run_synthetic_probe(svc, operation="fetch"))
    assert result.ok is True
    assert result.operation == "fetch"
    assert result.error_code is None
    assert len(execution.requests) == 1


def test_synthetic_probe_deep_research_returns_valid_structure() -> None:
    svc, execution = _service()
    result = run(run_synthetic_probe(svc, operation="deep_research"))
    assert result.ok is True
    assert result.operation == "deep_research"
    assert result.error_code is None
    assert len(execution.requests) == 2


def test_synthetic_probe_fails_closed_on_unknown_operation() -> None:
    svc, _execution = _service()
    with pytest.raises(ActivationError) as excinfo:
        run(run_synthetic_probe(svc, operation="scrape"))
    assert excinfo.value.code == "invalid_probe_operation"


def test_synthetic_probe_fail_closed_when_b14_unbound() -> None:
    svc = WebResearchEngineService(
        research_runtime_factory=lambda _app_id: None,  # type: ignore[arg-type]
        execution_runtime_factory=lambda _app_id: None,  # type: ignore[arg-type]
        b14_service_bound=False,
    )
    result = run(run_synthetic_probe(svc, operation="search"))
    assert result.ok is False
    assert result.error_code == "b14_service_unavailable"


# --- reference parity probe --------------------------------------------------


def test_reference_parity_probe_passes_for_reference_consumers() -> None:
    svc, execution = _service()
    results = run(run_reference_parity_probe(svc))
    assert len(results) == 2
    assert all(result.ok for result in results)
    assert len(execution.requests) == 2
    serialized = json.dumps([result.to_public_dict() for result in results])
    assert "route" not in serialized
    assert "metadata" not in serialized


def test_reference_parity_probe_uses_bounded_consumer_ids() -> None:
    svc, _execution = _service()
    results = run(run_reference_parity_probe(svc))
    assert {result.consumer for result in results} == {"lovebud-scout", "400-ai-finder"}


def test_reference_parity_probe_fails_closed_when_b14_unbound() -> None:
    svc = WebResearchEngineService(
        research_runtime_factory=lambda _app_id: None,  # type: ignore[arg-type]
        execution_runtime_factory=lambda _app_id: None,  # type: ignore[arg-type]
        b14_service_bound=False,
    )
    results = run(run_reference_parity_probe(svc))
    assert len(results) == 2
    assert all(result.ok is False for result in results)


# --- full activation evaluation ----------------------------------------------


def test_evaluate_activation_records_complete_secret_free_evidence() -> None:
    svc, _execution = _service()
    evidence = run(
        evaluate_activation(
            svc,
            confirmation_token=CONFIRMATION_TOKEN,
            current_main=FIXTURE_MAIN,
            accepted_source_head=FIXTURE_ACCEPTED_SOURCE_HEAD,
        )
    )
    assert isinstance(evidence, ActivationEvidence)
    assert evidence.current_main == FIXTURE_MAIN
    assert evidence.accepted_source_head == FIXTURE_ACCEPTED_SOURCE_HEAD
    assert evidence.deployment_target == DEPLOYMENT_TARGET
    assert evidence.current_deployed_version == CURRENT_DEPLOYED_VERSION
    assert evidence.rollback_version == ROLLBACK_VERSION
    assert evidence.config_binding_diff == "none"
    assert evidence.secret_name_diff == "none"
    assert evidence.reference_consumers == ("lovebud-scout", "400-ai-finder")
    assert len(evidence.synthetic_probes) == 3
    assert all(isinstance(probe, SyntheticProbeResult) and probe.ok for probe in evidence.synthetic_probes)
    assert len(evidence.reference_parity) == 2
    assert all(isinstance(result, ReferenceParityResult) and result.ok for result in evidence.reference_parity)
    assert evidence.real_provider_call_count == 0
    assert evidence.real_user_data == 0
    assert evidence.mutation_scope == "A1 Web/Research activation only"
    assert evidence.final_disposition == "PENDING_PRODUCTION_AUTHORIZATION"

    public = evidence.to_public_dict()
    serialized = json.dumps(public)
    assert serialized.count("real_provider_call_count") == 1
    assert public["real_provider_call_count"] == 0
    assert public["real_user_data"] == 0
    assert "PRIVATE" not in serialized
    assert "metadata" not in serialized
    assert "route" not in serialized


def test_evaluate_activation_fails_closed_without_confirmation_token() -> None:
    svc, _execution = _service()
    with pytest.raises(ActivationError) as excinfo:
        run(
            evaluate_activation(
                svc,
                confirmation_token="wrong-token",
                current_main=FIXTURE_MAIN,
                accepted_source_head=FIXTURE_ACCEPTED_SOURCE_HEAD,
            )
        )
    assert excinfo.value.code == "activation_not_authorized"


def test_evaluate_activation_fails_closed_on_bad_exact_main() -> None:
    svc, _execution = _service()
    with pytest.raises(ActivationError) as excinfo:
        run(
            evaluate_activation(
                svc,
                confirmation_token=CONFIRMATION_TOKEN,
                current_main="not-a-real-sha",
                accepted_source_head=FIXTURE_ACCEPTED_SOURCE_HEAD,
            )
        )
    assert excinfo.value.code == "invalid_sha"


def test_evaluate_activation_fails_closed_when_b14_unbound() -> None:
    svc = WebResearchEngineService(
        research_runtime_factory=lambda _app_id: None,  # type: ignore[arg-type]
        execution_runtime_factory=lambda _app_id: None,  # type: ignore[arg-type]
        b14_service_bound=False,
    )
    with pytest.raises(ActivationError) as excinfo:
        run(
            evaluate_activation(
                svc,
                confirmation_token=CONFIRMATION_TOKEN,
                current_main=FIXTURE_MAIN,
                accepted_source_head=FIXTURE_ACCEPTED_SOURCE_HEAD,
            )
        )
    assert excinfo.value.code == "synthetic_probe_failed"
