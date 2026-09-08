"""Tests for the #1746/#1753 E9 A3 Tool Runtime activation gate.

The synthetic probes run the REAL Core ``ToolRuntime`` behind the Engine
projection so the activation readiness record is grounded in genuine Core
semantics (approval blocks, non-widening resume, atomic cancellation), not
mocked assertions.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.agent_approval import VerifiedApprovalDecision
from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

from app.orchestration_continuation import InMemoryContinuationStore
from app.tool_execution_service import ToolExecutionEngineService
from app.tool_projection import EngineToolBinding, TrustedToolAuthority
from app.tool_runtime_activation import (
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
from app.tool_runtime_activation import REFERENCE_CONSUMERS as A3_REFERENCE_CONSUMERS

FIXTURE_MAIN = "b6b3157bae1e250613126bfac6dcb23c28a33b51"
FIXTURE_ACCEPTED_SOURCE_HEAD = "e7453cfd10f162e2edd90dcc81309e17776a69fb"

PROBE_APP_ID = "engine-a3-synthetic-probe"
CANONICAL_AGENT = "agent:engine:a3-probe@1"

CANONICAL_READ = "tool:engine:a3probe-read@1"
RUNTIME_READ = "a3probe-read.tool"
CANONICAL_GATE = "tool:engine:a3probe-gate@1"
RUNTIME_GATE = "a3probe-gate.tool"

PARITY_APPS = ("b62-padiem-chat-a3-parity", "b54-padiem-claw-a3-parity")

PROBE_READ_SCOPE = "a3probe.read"
PROBE_WRITE_SCOPE = "a3probe.write"
PROBE_SCOPES = (PROBE_READ_SCOPE, PROBE_WRITE_SCOPE)


def run(coro):
    return asyncio.run(coro)


class EchoVerifier:
    """Echo verifier: proves the wire assertion alone grants NOTHING."""

    def verify(self, submission, *, pause, app_id):
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


class ProbeContinuationStore(InMemoryContinuationStore):
    """In-memory store that exposes server-held pending continuation state.

    ``has_pending(app_id)`` models the server-side genuine grant: a non-terminal
    continuation issued for the app means the server holds a grant that a later
    resume may satisfy. The wire decision alone never grants anything.
    """

    def has_pending(self, app_id: str) -> bool:
        return any(
            record.app_id == app_id and record.state in ("active", "claimed")
            for record in self._records.values()
        )


class Fixture:
    """Real Core ToolRuntime + trusted bindings + Engine service for A3 probes."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.runtime = ToolRuntime()
        specs = self._make_specs()
        handlers = self._make_handlers()
        for spec in specs.values():
            self.runtime.register(spec, handlers[spec.id])
        self.registry = ToolRegistrySnapshot.from_entries(
            [
                RegisteredTool.from_spec(canonical_tool_id=canonical, runtime_spec=spec)
                for canonical, spec in [
                    (CANONICAL_READ, specs[RUNTIME_READ]),
                    (CANONICAL_GATE, specs[RUNTIME_GATE]),
                ]
            ]
        )
        definition = BoundedAgentDefinition(
            agent_id=CANONICAL_AGENT,
            publisher_id="engine",
            title="A3 synthetic probe agent",
            description="Non-sensitive structural probe for Tool Runtime activation.",
            instruction="Run only synthetic structural probes.",
            output_contract_ref="output:text@1",
            allowed_tool_ids=(CANONICAL_READ, CANONICAL_GATE),
            execution_budget=AgentExecutionBudget(),
        )
        self.definition = definition
        policy = TrustedAgentRuntimePolicy(
            context_policy_ref="context:default",
            model_policy_ref="model:auto",
            output_contract_ref="output:text@1",
            task_type="general",
            optimize_for="balanced",
            max_tokens=512,
            max_steps_cap=4,
            context_policy={},
            model_policy={},
            output_contract={},
            tool_bindings=(
                ToolRuntimeBinding(CANONICAL_READ, specs[RUNTIME_READ].id),
                ToolRuntimeBinding(CANONICAL_GATE, specs[RUNTIME_GATE].id),
            ),
        )
        self.compiled = compile_agent_profile(definition, policy)
        self.store = ProbeContinuationStore()
        self.bindings: dict[str, EngineToolBinding] = {}
        for app_id in (PROBE_APP_ID, *PARITY_APPS):
            self.bindings[app_id] = EngineToolBinding(
                app_id=app_id,
                tool_runtime=self.runtime,
                registry=self.registry,
                authorities={CANONICAL_AGENT: self._authority(app_id)},
                authorization_provider=self._provider(app_id),
            )
        self.service = ToolExecutionEngineService(
            tool_binding_resolver=lambda app_id: self.bindings.get(app_id),
            approval_decision_verifier=EchoVerifier(),
            continuation_store=self.store,
        )
        self.bare_service = ToolExecutionEngineService(
            tool_binding_resolver=lambda app_id: self.bindings.get(app_id),
        )

    def _authority(self, app_id: str) -> TrustedToolAuthority:
        return TrustedToolAuthority(
            canonical_agent_id=CANONICAL_AGENT,
            definition=self.definition,
            compiled=self.compiled,
            authorization=ToolAuthorizationContext(
                app_id=app_id,
                agent_id=self.compiled.runtime_profile.id,
                granted_auth_scopes=PROBE_SCOPES,
            ),
        )

    def _provider(self, app_id: str):
        def provide(canonical_agent_id: str) -> ToolAuthorizationContext:
            # Server-side genuine grant: only the write tool is granted once a
            # non-terminal continuation exists for the app. Caller JSON never
            # reaches this decision.
            user_confirmed = (RUNTIME_GATE,) if self.store.has_pending(app_id) else ()
            return ToolAuthorizationContext(
                app_id=app_id,
                agent_id=self.compiled.runtime_profile.id,
                granted_auth_scopes=PROBE_SCOPES,
                user_confirmed_tools=user_confirmed,
            )

        return provide

    def bump(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def total(self, name: str | None = None) -> int:
        if name is None:
            return sum(self.calls.values())
        return self.calls.get(name, 0)

    def _make_specs(self) -> dict[str, ToolSpec]:
        def schema(prop: str) -> dict:
            return {
                "type": "object",
                "properties": {prop: {"type": "string"}},
                "required": [prop],
                "additionalProperties": False,
            }

        return {
            RUNTIME_READ: ToolSpec(
                id=RUNTIME_READ,
                title="A3 Read",
                description="Read-only structural probe tool",
                owner="core",
                side_effect=ToolSideEffect.READ,
                approval_policy=ApprovalPolicy.NOT_REQUIRED,
                input_schema=schema("query"),
                auth_scope=(PROBE_READ_SCOPE,),
                timeout_seconds=5,
            ),
            RUNTIME_GATE: ToolSpec(
                id=RUNTIME_GATE,
                title="A3 Gated Write",
                description="Approval-gated write for continuation probes",
                owner=PROBE_APP_ID,
                side_effect=ToolSideEffect.WRITE,
                approval_policy=ApprovalPolicy.USER_CONFIRMATION,
                input_schema=schema("note"),
                auth_scope=(PROBE_WRITE_SCOPE,),
                timeout_seconds=5,
            ),
        }

    def _make_handlers(self) -> dict:
        async def read(arguments: dict) -> dict:
            self.bump(RUNTIME_READ)
            return {"hits": 1, "echo": "done"}

        async def gate(arguments: dict) -> dict:
            self.bump(RUNTIME_GATE)
            return {"written": True}

        return {
            RUNTIME_READ: read,
            RUNTIME_GATE: gate,
        }


@pytest.fixture()
def fx() -> Fixture:
    return Fixture()


# --- activation gate ---------------------------------------------------------


def test_confirmation_token_is_owner_phrase() -> None:
    assert CONFIRMATION_TOKEN == "ACTIVATE_ENGINE_A3_TOOL_RUNTIME"


def test_verify_confirmation_token_accepts_exact_token() -> None:
    verify_confirmation_token(CONFIRMATION_TOKEN)


def test_verify_confirmation_token_fails_closed_on_other_token() -> None:
    with pytest.raises(ActivationError) as excinfo:
        verify_confirmation_token("ACTIVATE_ENGINE_A1_WEB_RESEARCH")
    assert excinfo.value.code == "activation_not_authorized"


def test_verify_confirmation_token_fails_closed_on_non_string() -> None:
    with pytest.raises(ActivationError) as excinfo:
        verify_confirmation_token(None)  # type: ignore[arg-type]
    assert excinfo.value.code == "activation_not_authorized"


def test_verify_exact_main_accepts_sha_shape() -> None:
    verify_exact_main(FIXTURE_MAIN)


def test_verify_exact_main_fails_closed_on_bad_shape() -> None:
    with pytest.raises(ActivationError) as excinfo:
        verify_exact_main("not-a-real-sha")
    assert excinfo.value.code == "invalid_sha"


def test_rollback_anchor_records_audited_versions() -> None:
    anchor = record_rollback_anchor()
    assert isinstance(anchor, RollbackAnchor)
    assert anchor.deployment_target == DEPLOYMENT_TARGET
    assert anchor.current_deployed_version == CURRENT_DEPLOYED_VERSION
    assert anchor.rollback_version == ROLLBACK_VERSION
    assert anchor.config_binding_diff == "none"
    assert anchor.secret_name_diff == "none"


# --- synthetic probes --------------------------------------------------------


def test_synthetic_probe_execute_passes(fx: Fixture) -> None:
    result = run(run_synthetic_probe(fx.service, operation="execute"))
    assert isinstance(result, SyntheticProbeResult)
    assert result.operation == "execute"
    assert result.ok is True
    assert result.error_code is None
    assert fx.total(RUNTIME_READ) == 1
    assert fx.total(RUNTIME_GATE) == 0


def test_synthetic_probe_resume_passes(fx: Fixture) -> None:
    result = run(run_synthetic_probe(fx.service, operation="resume"))
    assert result.operation == "resume"
    assert result.ok is True
    assert result.error_code is None
    assert fx.total(RUNTIME_GATE) == 1


def test_synthetic_probe_cancel_passes(fx: Fixture) -> None:
    result = run(run_synthetic_probe(fx.service, operation="cancel"))
    assert result.operation == "cancel"
    assert result.ok is True
    assert result.error_code is None
    assert fx.total(RUNTIME_GATE) == 0


def test_synthetic_probe_fails_closed_on_unknown_operation(fx: Fixture) -> None:
    with pytest.raises(ActivationError) as excinfo:
        run(run_synthetic_probe(fx.service, operation="explode"))
    assert excinfo.value.code == "invalid_probe_operation"


def test_synthetic_probe_resume_fails_closed_without_continuation_infrastructure(
    fx: Fixture,
) -> None:
    result = run(run_synthetic_probe(fx.bare_service, operation="resume"))
    assert result.ok is False
    assert result.error_code == "synthetic_probe_failed"


def test_synthetic_probe_cancel_fails_closed_without_continuation_infrastructure(
    fx: Fixture,
) -> None:
    result = run(run_synthetic_probe(fx.bare_service, operation="cancel"))
    assert result.ok is False
    assert result.error_code == "synthetic_probe_failed"


# --- reference parity probe --------------------------------------------------


def test_reference_parity_probe_passes_for_reference_consumers(fx: Fixture) -> None:
    results = run(run_reference_parity_probe(fx.service))
    assert len(results) == 2
    assert all(result.ok for result in results)
    serialized = json.dumps([result.to_public_dict() for result in results])
    assert "route" not in serialized
    assert "metadata" not in serialized
    assert "secret" not in serialized


def test_reference_parity_probe_uses_bounded_consumer_ids(fx: Fixture) -> None:
    assert A3_REFERENCE_CONSUMERS == ("b62-padiem-chat", "b54-padiem-claw")
    results = run(run_reference_parity_probe(fx.service))
    assert {result.consumer for result in results} == {"b62-padiem-chat", "b54-padiem-claw"}


def test_reference_parity_probe_fails_closed_when_runtime_unbound() -> None:
    service = ToolExecutionEngineService(
        tool_binding_resolver=lambda _app_id: None,
        approval_decision_verifier=EchoVerifier(),
        continuation_store=ProbeContinuationStore(),
    )
    results = run(run_reference_parity_probe(service))
    assert len(results) == 2
    assert all(result.ok is False for result in results)


# --- full activation evaluation ----------------------------------------------


def test_evaluate_activation_records_complete_secret_free_evidence(fx: Fixture) -> None:
    evidence = run(
        evaluate_activation(
            fx.service,
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
    assert evidence.reference_consumers == ("b62-padiem-chat", "b54-padiem-claw")
    assert len(evidence.synthetic_probes) == 3
    assert all(
        isinstance(probe, SyntheticProbeResult) and probe.ok
        for probe in evidence.synthetic_probes
    )
    assert len(evidence.reference_parity) == 2
    assert all(
        isinstance(result, ReferenceParityResult) and result.ok
        for result in evidence.reference_parity
    )
    assert evidence.real_provider_call_count == 0
    assert evidence.real_user_data == 0
    assert evidence.mutation_scope == "A3 Tool Runtime activation only"
    assert evidence.final_disposition == "PENDING_PRODUCTION_AUTHORIZATION"

    public = evidence.to_public_dict()
    serialized = json.dumps(public)
    assert serialized.count("real_provider_call_count") == 1
    assert public["real_provider_call_count"] == 0
    assert public["real_user_data"] == 0
    assert "PRIVATE" not in serialized
    assert "metadata" not in serialized
    assert "route" not in serialized


def test_evaluate_activation_fails_closed_without_confirmation_token(fx: Fixture) -> None:
    with pytest.raises(ActivationError) as excinfo:
        run(
            evaluate_activation(
                fx.service,
                confirmation_token="wrong-token",
                current_main=FIXTURE_MAIN,
                accepted_source_head=FIXTURE_ACCEPTED_SOURCE_HEAD,
            )
        )
    assert excinfo.value.code == "activation_not_authorized"


def test_evaluate_activation_fails_closed_on_bad_exact_main(fx: Fixture) -> None:
    with pytest.raises(ActivationError) as excinfo:
        run(
            evaluate_activation(
                fx.service,
                confirmation_token=CONFIRMATION_TOKEN,
                current_main="not-a-real-sha",
                accepted_source_head=FIXTURE_ACCEPTED_SOURCE_HEAD,
            )
        )
    assert excinfo.value.code == "invalid_sha"


def test_evaluate_activation_fails_closed_when_probe_fails(fx: Fixture) -> None:
    with pytest.raises(ActivationError) as excinfo:
        run(
            evaluate_activation(
                fx.bare_service,
                confirmation_token=CONFIRMATION_TOKEN,
                current_main=FIXTURE_MAIN,
                accepted_source_head=FIXTURE_ACCEPTED_SOURCE_HEAD,
            )
        )
    assert excinfo.value.code == "synthetic_probe_failed"
