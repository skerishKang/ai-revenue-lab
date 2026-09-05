"""Core-owned reconstruction of `OrchestrationResult` from its public-dict shape.

The public projection is deliberately lossy (no evidence graph, no approval
pause identity, no idempotency key, no subject id). These tests pin the two
halves of the #1916 contract:

* everything the wire carries is reconstructed into its Core value type;
* anything the wire cannot carry losslessly is *rejected*, never dropped.
"""

from __future__ import annotations

import copy

import pytest

from padiem_ai_core import (
    AgentProfile,
    B14RouteMetadata,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
    OrchestrationError,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationRunner,
    RunMetadata,
    RunStatus,
    orchestration_result_from_public,
)


class FakeRuntime:
    def __init__(self, answer: str = "public answer") -> None:
        self.answer = answer

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            answer=self.answer,
            route=B14RouteMetadata(
                selected_provider="test_prov",
                selected_model="test_model",
                attempt_count=1,
                fallback_used=False,
                reason_codes=("ok",),
                estimated_krw=1.5,
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "trace_1",
                app_id="b54-padiem-claw",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
                session_id=request.session_id,
                duration_ms=12,
            ),
        )


def _agent_profile() -> AgentProfile:
    return AgentProfile(
        id="b54-padiem-claw",
        title="Padiem Claw",
        description="B54 repository task execution consumer",
        system_instruction=None,
        task_type="coding",
        optimize_for="balanced",
        max_tokens=None,
        allowed_tools=(),
        required_capabilities=(),
        context_policy={},
        model_policy={},
        max_steps=1,
        output_contract={},
    )


async def _public_result() -> dict[str, object]:
    """Return the exact wire shape the Engine returns for a Claw-style run."""

    runner = OrchestrationRunner(runtime=FakeRuntime())
    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=_agent_profile(),
            messages=({"role": "user", "content": "hello"},),
            session_id="run_claw_1",
            trace_id="trace_claw_1",
        ),
        context=ExecutionContext(trace_id="trace_claw_1"),
        app_id="b54-padiem-claw",
        subject_id=None,
    )
    result = await runner.run(request)
    return result.to_public_dict()


async def test_public_result_round_trips_through_the_parser() -> None:
    payload = await _public_result()

    result = orchestration_result_from_public(payload)

    assert isinstance(result, OrchestrationResult)
    assert result.app_id == "b54-padiem-claw"
    assert result.context.trace_id == "trace_claw_1"
    assert result.execution_result.answer == "public answer"
    assert result.execution_result.metadata.trace_id == "trace_claw_1"
    assert result.execution_result.metadata.app_id == "b54-padiem-claw"
    assert result.execution_result.metadata.agent_id == "b54-padiem-claw"
    assert result.execution_result.metadata.session_id == "run_claw_1"
    assert result.execution_result.metadata.status is RunStatus.COMPLETED
    assert result.execution_result.route.selected_provider == "test_prov"
    assert result.execution_result.route.selected_model == "test_model"
    assert result.execution_result.route.attempt_count == 1
    assert result.execution_result.route.fallback_used is False
    assert result.execution_result.route.reason_codes == ("ok",)
    assert result.execution_result.route.estimated_krw == 1.5


async def test_events_are_reconstructed_in_wire_order() -> None:
    result = orchestration_result_from_public(await _public_result())

    assert [event.kind for event in result.events] == [
        OrchestrationEventKind.RUN_STARTED,
        OrchestrationEventKind.CONTEXT_PREPARED,
        OrchestrationEventKind.RUN_COMPLETED,
    ]
    assert [event.sequence for event in result.events] == [1, 2, 3]
    assert result.events[-1].run_id == result.events[0].run_id


async def test_state_machine_is_reconstructed() -> None:
    result = orchestration_result_from_public(await _public_result())

    assert result.execution_state is ExecutionState.COMPLETED
    assert result.state_transitions
    assert result.state_transitions[0].sequence == 1
    assert result.state_transitions[0].to_state is ExecutionState.RUNNING
    assert result.state_transitions[-1].to_state is ExecutionState.COMPLETED


async def test_lossless_fields_round_trip_to_an_identical_public_dict() -> None:
    payload = await _public_result()

    rebuilt = orchestration_result_from_public(payload)

    assert rebuilt.to_public_dict() == payload


async def test_unknown_top_level_field_is_rejected_not_skipped() -> None:
    payload = await _public_result()
    payload["evidence_graph"] = {"claims": []}

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_field"


async def test_unknown_nested_field_is_rejected_not_skipped() -> None:
    payload = await _public_result()
    payload["execution"]["metadata"]["tenant_id"] = "tenant_1"

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_field"


def test_non_mapping_payload_is_rejected() -> None:
    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(["not", "a", "mapping"])
    assert caught.value.code == "invalid_result_payload"


async def test_non_empty_evidence_is_rejected() -> None:
    payload = await _public_result()
    payload["evidence"]["claim_count"] = 1

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_evidence"


async def test_non_empty_citations_are_rejected() -> None:
    payload = await _public_result()
    payload["evidence"]["citations"] = [{"claim_id": "claim_1"}]

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_evidence"


async def test_non_empty_assessments_are_rejected() -> None:
    payload = await _public_result()
    payload["evidence"]["assessments"] = [{"claim_id": "claim_1"}]

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_evidence"


async def test_approval_pause_is_rejected_instead_of_dropped() -> None:
    payload = await _public_result()
    payload["approval_pause"] = {"status": "paused", "continuation_id": "pause_1"}

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_approval_pause"


async def test_continuation_state_is_rejected_instead_of_dropped() -> None:
    payload = await _public_result()
    payload["continuation_state"] = {"status": "awaiting_decision", "decision_id": "dec_1"}

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_continuation_state"


async def test_continuation_ref_is_rejected_instead_of_dropped() -> None:
    payload = await _public_result()
    payload["continuation_ref"] = "cont_1"

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_continuation_ref"


async def test_agent_plan_is_rejected_instead_of_dropped() -> None:
    payload = await _public_result()
    payload["plan"] = {"agent_id": "agent:x:y@1", "steps": []}

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_plan"


async def test_activated_skill_is_rejected_instead_of_dropped() -> None:
    payload = await _public_result()
    payload["activated_skill"] = {"skill_id": "skill_1"}

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_skill"


async def test_idempotent_run_is_rejected_instead_of_losing_replay_identity() -> None:
    payload = await _public_result()
    payload["context"]["idempotency_present"] = True

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_idempotency"


async def test_unknown_event_kind_fails_the_whole_result() -> None:
    payload = await _public_result()
    payload["events"][1]["kind"] = "quantum_prepared"

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "invalid_result_event"


async def test_unknown_event_field_fails_the_whole_result() -> None:
    payload = await _public_result()
    payload["events"][0]["raw_reasoning"] = "hidden"

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "invalid_result_event"


async def test_unknown_route_field_is_rejected() -> None:
    payload = await _public_result()
    payload["execution"]["route"]["shadow_model"] = "secret-model"

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_field"


async def test_unknown_transition_field_is_rejected() -> None:
    payload = await _public_result()
    payload["state_machine"]["transitions"][0]["actor"] = "someone"

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_field"


async def test_unsupported_execution_status_is_rejected() -> None:
    payload = await _public_result()
    payload["execution"]["metadata"]["status"] = "almost_done"

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "unsupported_result_status"


async def test_non_scalar_transition_metadata_is_rejected() -> None:
    payload = await _public_result()
    payload["state_machine"]["transitions"][0]["metadata"] = {"nested": {"a": 1}}

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "invalid_result_payload"


async def test_non_string_resolved_tool_ids_are_rejected() -> None:
    payload = await _public_result()
    payload["resolved_tool_ids"] = [{"tool_id": "tool_1"}]

    with pytest.raises(OrchestrationError) as caught:
        orchestration_result_from_public(payload)
    assert caught.value.code == "invalid_result_payload"


async def test_subject_identity_is_never_carried_by_the_public_projection() -> None:
    payload = await _public_result()

    assert "subject_id" not in payload
    assert orchestration_result_from_public(payload).subject_id is None


async def test_parser_does_not_mutate_the_wire_payload() -> None:
    payload = await _public_result()
    snapshot = copy.deepcopy(payload)

    orchestration_result_from_public(payload)

    assert payload == snapshot
