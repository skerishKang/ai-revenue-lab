"""Focused tests for the #1746 Engine tool execution service.

These run the REAL Core ``ToolRuntime`` behind the Engine projection: every
execution, gate, timeout and approval block is decided by Core. Tests assert:
- authorized execution completes through Core with redacted bounded output;
- unknown/unauthorized/schema-invalid/scope-invalid requests fail closed with
  zero handler calls;
- approval-required tools pause (202) and are never self-granted: a resumed
  attempt without a genuine server-side grant re-hits the Core gate with zero
  handler calls;
- continuation is non-widening; cancelled and denied continuations are
  distinguishable terminal states;
- timeout is independent (504) and asyncio cancellation propagates untouched;
- raw tool arguments never echo back and secret-shaped outputs are redacted;
- cross-app scope isolation holds at every lookup.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core.agent_approval import ApprovalPause, ApprovalRequirement, tool_invocation_digest
from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolInvocation, ToolRuntime

from app import orchestration_service as orch_module
from app.orchestration_service import InMemoryContinuationStore, OrchestrationEngineService
from app.service import ServiceContractError
from app.tool_execution_service import ToolExecutionEngineService
from app.tool_projection import (
    TOOL_CANCEL_PATH,
    TOOL_EXECUTE_PATH,
    TOOL_RESUME_PATH,
    EngineToolBinding,
    TrustedToolAuthority,
)

APP_ID = "t1746"
OTHER_APP = "other1746"
CANONICAL_AGENT = "agent:acme:assistant@1"

CANONICAL_SEARCH = "tool:acme:search@1"
RUNTIME_SEARCH = "search.tool"
CANONICAL_WRITE = "tool:acme:write@1"
RUNTIME_WRITE = "write.tool"
CANONICAL_BOOM = "tool:acme:boom@1"
RUNTIME_BOOM = "boom.tool"
CANONICAL_SLOW = "tool:acme:slow@1"
RUNTIME_SLOW = "slow.tool"
CANONICAL_SECRETS = "tool:acme:secrets@1"
RUNTIME_SECRETS = "secrets.tool"
CANONICAL_HANG = "tool:acme:hang@1"
RUNTIME_HANG = "hang.tool"

SECRET_QUERY = "hello-secret-query-do-not-echo"


class Fixture:
    """Real Core runtime + registry + trusted binding + Engine service."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.grants: list[str] = []
        self.scopes: tuple[str, ...] = ("search", "write")
        self.runtime = ToolRuntime()
        specs = self._make_specs()
        handlers = self._make_handlers()
        for spec in specs.values():
            self.runtime.register(spec, handlers[spec.id])
        self.registry = ToolRegistrySnapshot.from_entries(
            [
                RegisteredTool.from_spec(canonical_tool_id=canonical, runtime_spec=spec)
                for canonical, spec in [
                    (CANONICAL_SEARCH, specs[RUNTIME_SEARCH]),
                    (CANONICAL_WRITE, specs[RUNTIME_WRITE]),
                    (CANONICAL_BOOM, specs[RUNTIME_BOOM]),
                    (CANONICAL_SLOW, specs[RUNTIME_SLOW]),
                    (CANONICAL_SECRETS, specs[RUNTIME_SECRETS]),
                    (CANONICAL_HANG, specs[RUNTIME_HANG]),
                ]
            ]
        )
        definition = BoundedAgentDefinition(
            agent_id=CANONICAL_AGENT,
            publisher_id="acme",
            title="Assistant",
            description="Trusted test assistant",
            instruction="Answer safely",
            output_contract_ref="output:text@1",
            allowed_tool_ids=tuple(self.registry.canonical_tool_ids),
            execution_budget=AgentExecutionBudget(),
        )
        policy = TrustedAgentRuntimePolicy(
            context_policy_ref="context:default",
            model_policy_ref="model:auto",
            output_contract_ref="output:text@1",
            task_type="general",
            optimize_for="balanced",
            max_tokens=1024,
            max_steps_cap=8,
            context_policy={},
            model_policy={},
            output_contract={},
            tool_bindings=tuple(
                ToolRuntimeBinding(canonical, spec.id)
                for canonical, spec in [
                    (CANONICAL_SEARCH, specs[RUNTIME_SEARCH]),
                    (CANONICAL_WRITE, specs[RUNTIME_WRITE]),
                    (CANONICAL_BOOM, specs[RUNTIME_BOOM]),
                    (CANONICAL_SLOW, specs[RUNTIME_SLOW]),
                    (CANONICAL_SECRETS, specs[RUNTIME_SECRETS]),
                    (CANONICAL_HANG, specs[RUNTIME_HANG]),
                ]
            ),
        )
        self.compiled = compile_agent_profile(definition, policy)
        authority = TrustedToolAuthority(
            canonical_agent_id=CANONICAL_AGENT,
            definition=definition,
            compiled=self.compiled,
            authorization=ToolAuthorizationContext(
                app_id=APP_ID,
                agent_id=self.compiled.runtime_profile.id,
                granted_auth_scopes=self.scopes,
            ),
        )
        self.binding = EngineToolBinding(
            app_id=APP_ID,
            tool_runtime=self.runtime,
            registry=self.registry,
            authorities={CANONICAL_AGENT: authority},
            authorization_provider=self._provide_authorization,
        )
        self.store = InMemoryContinuationStore()
        self.service = ToolExecutionEngineService(
            tool_binding_resolver=lambda app_id: (
                self.binding if app_id == APP_ID else None
            ),
            approval_decision_verifier=TestVerifier(),
            continuation_store=self.store,
        )
        self.bare_service = ToolExecutionEngineService(
            tool_binding_resolver=lambda app_id: (
                self.binding if app_id == APP_ID else None
            ),
        )

    def _provide_authorization(self, agent_id: str) -> ToolAuthorizationContext:
        # Models server/control-plane grant state; caller JSON never reaches it.
        return ToolAuthorizationContext(
            app_id=APP_ID,
            agent_id=self.compiled.runtime_profile.id,
            granted_auth_scopes=self.scopes,
            user_confirmed_tools=tuple(self.grants),
        )

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
            RUNTIME_SEARCH: ToolSpec(
                id=RUNTIME_SEARCH,
                title="Search",
                description="Read-only search",
                owner="core",
                side_effect=ToolSideEffect.READ,
                approval_policy=ApprovalPolicy.NOT_REQUIRED,
                input_schema=schema("query"),
                auth_scope=("search",),
                timeout_seconds=5,
            ),
            RUNTIME_WRITE: ToolSpec(
                id=RUNTIME_WRITE,
                title="Write",
                description="Side-effecting write",
                owner=APP_ID,
                side_effect=ToolSideEffect.WRITE,
                approval_policy=ApprovalPolicy.USER_CONFIRMATION,
                input_schema=schema("note"),
                auth_scope=("write",),
                timeout_seconds=5,
            ),
            RUNTIME_BOOM: ToolSpec(
                id=RUNTIME_BOOM,
                title="Boom",
                description="Always fails",
                owner="core",
                side_effect=ToolSideEffect.READ,
                approval_policy=ApprovalPolicy.NOT_REQUIRED,
                input_schema=schema("query"),
                timeout_seconds=5,
            ),
            RUNTIME_SLOW: ToolSpec(
                id=RUNTIME_SLOW,
                title="Slow",
                description="Exceeds its own timeout",
                owner="core",
                side_effect=ToolSideEffect.READ,
                approval_policy=ApprovalPolicy.NOT_REQUIRED,
                input_schema=schema("query"),
                timeout_seconds=1,
            ),
            RUNTIME_SECRETS: ToolSpec(
                id=RUNTIME_SECRETS,
                title="Secrets",
                description="Returns secret-shaped output",
                owner="core",
                side_effect=ToolSideEffect.READ,
                approval_policy=ApprovalPolicy.NOT_REQUIRED,
                input_schema=schema("query"),
                timeout_seconds=5,
            ),
            RUNTIME_HANG: ToolSpec(
                id=RUNTIME_HANG,
                title="Hang",
                description="Waits forever until cancelled",
                owner="core",
                side_effect=ToolSideEffect.READ,
                approval_policy=ApprovalPolicy.NOT_REQUIRED,
                input_schema=schema("query"),
                timeout_seconds=30,
            ),
        }

    def _make_handlers(self) -> dict:
        async def search(arguments: dict) -> dict:
            self.bump(RUNTIME_SEARCH)
            return {"hits": 1, "echo": "done"}

        async def write(arguments: dict) -> dict:
            self.bump(RUNTIME_WRITE)
            return {"written": True}

        async def boom(arguments: dict) -> dict:
            self.bump(RUNTIME_BOOM)
            raise RuntimeError("internal handler detail that must not leak")

        async def slow(arguments: dict) -> dict:
            self.bump(RUNTIME_SLOW)
            await asyncio.sleep(3)
            return {"late": True}

        async def secrets(arguments: dict) -> dict:
            self.bump(RUNTIME_SECRETS)
            return {"value": "safe", "api_key": "sk-live-super-secret"}

        async def hang(arguments: dict) -> dict:
            self.bump(RUNTIME_HANG)
            await asyncio.Event().wait()
            return {}

        return {
            RUNTIME_SEARCH: search,
            RUNTIME_WRITE: write,
            RUNTIME_BOOM: boom,
            RUNTIME_SLOW: slow,
            RUNTIME_SECRETS: secrets,
            RUNTIME_HANG: hang,
        }


class TestVerifier:
    """Echo verifier: proves the wire assertion alone grants NOTHING."""

    def verify(self, submission, *, pause, app_id):
        from padiem_ai_core.agent_approval import VerifiedApprovalDecision

        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


@pytest.fixture()
def fx() -> Fixture:
    return Fixture()


def execute_payload(tool_id: str = CANONICAL_SEARCH, arguments: dict | None = None, **overrides) -> dict:
    payload = {
        "app_id": APP_ID,
        "agent_id": CANONICAL_AGENT,
        "tool_id": tool_id,
        "arguments": arguments if arguments is not None else {"query": SECRET_QUERY},
    }
    payload.update(overrides)
    return payload


async def pause_tool(fx: Fixture) -> tuple[dict, dict]:
    """Run the approval-gated write tool, expect a 202 pause; return (body, decision)."""
    response = await fx.service.execute_payload(
        execute_payload(CANONICAL_WRITE, {"note": "apply change"})
    )
    assert response.status_code == 202, response.body
    tool = response.body["tool"]
    decision = {
        "decision_id": "dec_t1746",
        "pause_id": tool["approval_pause"]["continuation_id"],
        "outcome": "approved",
        "authority_ref": "user:admin",
        "evidence_ref": "session:auth",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    return tool, decision


def resume_payload(tool: dict, decision: dict, **overrides) -> dict:
    payload = {"app_id": APP_ID, "continuation_ref": tool["continuation_ref"], "decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# authorized execution through Core
# ---------------------------------------------------------------------------


async def test_authorized_execution_completes_via_core(fx: Fixture):
    response = await fx.service.execute_payload(execute_payload())
    assert response.status_code == 200
    tool = response.body["tool"]
    assert tool["status"] == "completed"
    assert tool["canonical_tool_id"] == CANONICAL_SEARCH
    assert tool["agent_id"] == CANONICAL_AGENT
    assert tool["contract_version"] == "padiem.engine.tools/1.0"
    assert tool["output"] == {"hits": 1, "echo": "done"}
    assert tool["event"]["tool_id"] == RUNTIME_SEARCH
    assert tool["lifecycle"][0]["kind"] == "completed"
    assert fx.total(RUNTIME_SEARCH) == 1


async def test_private_arguments_never_echo(fx: Fixture):
    response = await fx.service.execute_payload(execute_payload())
    assert SECRET_QUERY not in json.dumps(response.body)


# ---------------------------------------------------------------------------
# fail-closed gates: zero handler calls
# ---------------------------------------------------------------------------


async def test_unregistered_tool_fails_closed(fx: Fixture):
    response = await fx.service.execute_payload(
        execute_payload("tool:acme:ghost@1", {"query": "x"})
    )
    assert response.status_code == 403
    assert response.body["error"]["code"] == "tool_not_registered"
    assert fx.total() == 0


async def test_unbound_agent_fails_closed(fx: Fixture):
    response = await fx.service.execute_payload(
        execute_payload(agent_id="agent:acme:ghost@1")
    )
    assert response.status_code == 403
    assert response.body["error"]["code"] == "tool_agent_not_bound"
    assert fx.total() == 0


async def test_unprovisioned_app_fails_closed(fx: Fixture):
    response = await fx.service.execute_payload(execute_payload(app_id=OTHER_APP))
    assert response.status_code == 503
    assert response.body["error"]["code"] == "tool_runtime_unavailable"
    assert fx.total() == 0


async def test_missing_auth_scope_fails_closed(fx: Fixture):
    fx.scopes = ()
    response = await fx.service.execute_payload(execute_payload())
    assert response.status_code == 403
    assert response.body["error"]["code"] == "tool_auth_scope_missing"
    assert fx.total() == 0


async def test_schema_invalid_arguments_fails_closed(fx: Fixture):
    response = await fx.service.execute_payload(execute_payload(CANONICAL_SEARCH, {}))
    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_tool_arguments"
    assert fx.total() == 0


async def test_provider_wire_key_rejected_without_execution(fx: Fixture):
    response = await fx.service.execute_payload(
        execute_payload(tool_calls=[{"id": "evil"}])
    )
    assert response.status_code == 400
    assert response.body["error"]["code"] == "provider_tool_wire_rejected"
    assert fx.total() == 0


async def test_caller_minted_authority_rejected_without_execution(fx: Fixture):
    response = await fx.service.execute_payload(
        execute_payload(approved=[RUNTIME_SEARCH])
    )
    assert response.status_code == 400
    assert response.body["error"]["code"] == "caller_minted_tool_authority_rejected"
    assert fx.total() == 0


# ---------------------------------------------------------------------------
# approval pause / resume: APPROVAL_SELF_GRANT = NO
# ---------------------------------------------------------------------------


async def test_approval_tool_pauses_without_handler_call(fx: Fixture):
    tool, _decision = await pause_tool(fx)
    assert tool["status"] == "paused"
    assert tool["approval_pause"]["requirement"] == "user_confirmation"
    assert tool["continuation_ref"].startswith("cont_")
    assert fx.total(RUNTIME_WRITE) == 0


async def test_resume_without_genuine_grant_reblocks_with_zero_calls(fx: Fixture):
    tool, decision = await pause_tool(fx)
    response = await fx.service.resume_payload(resume_payload(tool, decision))
    # The wire asserts approval, but no server-side grant exists: the Core gate
    # fires again and the handler still never ran.
    assert response.status_code == 403
    assert response.body["error"]["code"] == "tool_user_confirmation_required"
    assert fx.total(RUNTIME_WRITE) == 0


async def test_resume_after_genuine_server_grant_executes_once(fx: Fixture):
    tool, decision = await pause_tool(fx)
    fx.grants = [RUNTIME_WRITE]
    response = await fx.service.resume_payload(resume_payload(tool, decision))
    assert response.status_code == 200
    body = response.body["tool"]
    assert body["status"] == "completed"
    assert body["canonical_tool_id"] == CANONICAL_WRITE
    assert body["continuation_ref"] == tool["continuation_ref"]
    assert fx.total(RUNTIME_WRITE) == 1


async def test_resume_denied_is_terminal(fx: Fixture):
    tool, decision = await pause_tool(fx)
    decision = dict(decision, outcome="denied")
    response = await fx.service.resume_payload(resume_payload(tool, decision))
    assert response.status_code == 409
    assert response.body["error"]["code"] == "approval_denied"
    assert response.body["error"]["metadata"]["terminal_state"] == "denied"
    assert fx.total(RUNTIME_WRITE) == 0
    # Consumed: a second attempt cannot revive it.
    second = await fx.service.resume_payload(
        resume_payload(tool, dict(decision, decision_id="dec_t1746_b"))
    )
    assert second.status_code == 409
    assert second.body["error"]["code"] == "continuation_consumed"


async def test_resume_payload_is_non_widening(fx: Fixture):
    tool, decision = await pause_tool(fx)
    response = await fx.service.resume_payload(
        resume_payload(tool, decision, tool_id=CANONICAL_SEARCH, arguments={"query": "swap"})
    )
    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_tool_request"
    assert fx.total() == 0


async def test_resume_decision_identity_mismatch(fx: Fixture):
    tool, decision = await pause_tool(fx)
    wrong = dict(decision, pause_id="pause:deadbeef")
    response = await fx.service.resume_payload(resume_payload(tool, wrong))
    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_identity_mismatch"


async def test_resume_cross_app_continuation_isolated(fx: Fixture):
    tool, decision = await pause_tool(fx)
    response = await fx.service.resume_payload(
        resume_payload(tool, decision, app_id=OTHER_APP)
    )
    assert response.status_code == 409
    assert fx.total(RUNTIME_WRITE) == 0


async def test_cancelled_continuation_is_distinguishable(fx: Fixture):
    tool, decision = await pause_tool(fx)
    cancel = await fx.service.cancel_payload(
        {"app_id": APP_ID, "continuation_ref": tool["continuation_ref"], "reason": "user_cancelled"}
    )
    assert cancel.status_code == 200
    assert cancel.body["status"] == "cancelled"
    assert cancel.body["tool"]["lifecycle"][0]["kind"] == "cancelled"
    assert cancel.body["tool"]["tool_id"] == CANONICAL_WRITE
    # Cancelled is a distinct terminal state from denied/expired.
    resume = await fx.service.resume_payload(resume_payload(tool, decision))
    assert resume.status_code == 409
    assert resume.body["error"]["code"] == "continuation_cancelled"
    assert fx.total(RUNTIME_WRITE) == 0


async def test_pause_fails_closed_without_continuation_infrastructure(fx: Fixture):
    response = await fx.bare_service.execute_payload(
        execute_payload(CANONICAL_WRITE, {"note": "apply change"})
    )
    assert response.status_code == 503
    assert response.body["error"]["code"] == "approval_verification_unavailable"
    assert fx.total(RUNTIME_WRITE) == 0


# ---------------------------------------------------------------------------
# timeout / failure / cancellation are independent outcomes
# ---------------------------------------------------------------------------


async def test_core_timeout_maps_to_504_not_failure(fx: Fixture):
    response = await fx.service.execute_payload(execute_payload(CANONICAL_SLOW))
    assert response.status_code == 504
    error = response.body["error"]
    assert error["code"] == "tool_timeout"
    assert error["metadata"]["terminal_state"] == "timed_out"
    assert fx.total(RUNTIME_SLOW) == 1


async def test_handler_failure_maps_to_500_without_detail_leak(fx: Fixture):
    response = await fx.service.execute_payload(execute_payload(CANONICAL_BOOM))
    assert response.status_code == 500
    error = response.body["error"]
    assert error["code"] == "tool_execution_failed"
    assert "internal handler detail" not in json.dumps(response.body)


async def test_task_cancellation_propagates_untouched(fx: Fixture):
    task = asyncio.create_task(fx.service.execute_payload(execute_payload(CANONICAL_HANG)))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Cancellation was never converted into a timeout or internal-error response.
    assert fx.total(RUNTIME_HANG) == 1


# ---------------------------------------------------------------------------
# output redaction across the service boundary
# ---------------------------------------------------------------------------


async def test_secret_shaped_output_values_never_cross(fx: Fixture):
    response = await fx.service.execute_payload(execute_payload(CANONICAL_SECRETS))
    assert response.status_code == 200
    tool = response.body["tool"]
    assert tool["output"]["value"] == "safe"
    assert tool["output"]["api_key"] == "[redacted]"
    assert "sk-live-super-secret" not in json.dumps(response.body)


# ---------------------------------------------------------------------------
# transport envelope
# ---------------------------------------------------------------------------


async def test_handle_transport_guards(fx: Fixture):
    body = json.dumps(execute_payload()).encode("utf-8")
    missing = await fx.service.handle(method="POST", path="/internal/v1/nope", content_type="application/json", body=body)
    assert missing.status_code == 404
    bad_method = await fx.service.handle(method="GET", path=TOOL_EXECUTE_PATH, content_type="application/json", body=body)
    assert bad_method.status_code == 405
    bad_type = await fx.service.handle(method="POST", path=TOOL_EXECUTE_PATH, content_type="text/plain", body=body)
    assert bad_type.status_code == 415
    bad_json = await fx.service.handle(method="POST", path=TOOL_EXECUTE_PATH, content_type="application/json", body=b"{")
    assert bad_json.status_code == 400
    assert bad_json.body["error"]["code"] == "invalid_json"
    huge = await fx.service.handle(
        method="POST", path=TOOL_EXECUTE_PATH, content_type="application/json",
        body=b"x" * (10 * 1024 * 1024),
    )
    assert huge.status_code == 413
    ok = await fx.service.handle(
        method="POST", path=TOOL_EXECUTE_PATH,
        content_type="application/json; charset=utf-8", body=body,
    )
    assert ok.status_code == 200
    resume_guard = await fx.service.handle(
        method="POST", path=TOOL_RESUME_PATH, content_type="application/json", body=b"{}"
    )
    assert resume_guard.status_code == 400
    assert resume_guard.body["error"]["code"] == "invalid_tool_request"
    cancel_guard = await fx.service.handle(
        method="POST", path=TOOL_CANCEL_PATH, content_type="application/json", body=b"{}"
    )
    assert cancel_guard.status_code == 400
    assert cancel_guard.body["error"]["code"] == "invalid_tool_request"


# ---------------------------------------------------------------------------
# Part C: orchestration cross-runtime tool path (#1746)
# ---------------------------------------------------------------------------

PLAN_WIRE = {
    "agent_id": CANONICAL_AGENT,
    "steps": [{"step_id": "step-1", "objective": "apply the change", "tool_id": RUNTIME_WRITE}],
}


def orch_payload(app_id: str = APP_ID) -> dict:
    return {
        "app_id": app_id,
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
        },
        "messages": [{"role": "user", "content": "run the plan"}],
        "trace_id": "tr_orch_test",
        "execution_context": {"trace_id": "tr_orch_test", "timeout_seconds": 15.0},
    }


class _CapturedRequest(Exception):
    def __init__(self, request):
        self.request = request
        super().__init__("captured")


class _FakeRunner:
    captured: list = []

    def __init__(self, runtime=None, idempotency=None):
        pass

    async def run(self, request):
        _FakeRunner.captured.append(request)
        raise _CapturedRequest(request)

    async def resume(self, request):
        _FakeRunner.captured.append(request)
        raise _CapturedRequest(request)


@pytest.fixture()
def capture_runner(monkeypatch):
    _FakeRunner.captured = []
    monkeypatch.setattr(orch_module, "OrchestrationRunner", _FakeRunner)
    return _FakeRunner


class _MockOrchRuntime:
    async def run(self, request):
        raise AssertionError("runtime must not be reached behind the fake runner")


def make_orch_service(fx: Fixture, *, resolver=None) -> OrchestrationEngineService:
    return OrchestrationEngineService(
        runtime_factory=lambda app_id: _MockOrchRuntime(),
        b14_service_bound=True,
        approval_decision_verifier=TestVerifier(),
        continuation_store=InMemoryContinuationStore(),
        tool_binding_resolver=resolver
        if resolver is not None
        else (lambda app_id: fx.binding if app_id == APP_ID else None),
    )


async def test_tool_arguments_without_plan_rejected(fx: Fixture, capture_runner):
    service = make_orch_service(fx)
    payload = orch_payload()
    payload["tool_arguments"] = {"step-1": {"note": "x"}}
    response = await service.orchestrate_payload(payload)
    assert response.status_code == 400
    assert response.body["error"]["code"] == "tool_arguments_without_plan"


async def test_plan_with_tool_arguments_but_no_binding_fails_503(fx: Fixture, capture_runner):
    service = make_orch_service(fx, resolver=lambda app_id: None)
    payload = orch_payload()
    payload["agent_plan"] = PLAN_WIRE
    payload["tool_arguments"] = {"step-1": {"note": "x"}}
    response = await service.orchestrate_payload(payload)
    assert response.status_code == 503
    assert response.body["error"]["code"] == "tool_runtime_unavailable"


async def test_binding_resolver_failure_maps_to_503(fx: Fixture, capture_runner):
    def boom_resolver(app_id: str):
        raise RuntimeError("resolver exploded")

    service = make_orch_service(fx, resolver=boom_resolver)
    payload = orch_payload()
    payload["agent_plan"] = PLAN_WIRE
    response = await service.orchestrate_payload(payload)
    assert response.status_code == 503
    assert response.body["error"]["code"] == "tool_runtime_unavailable"


async def test_cross_app_binding_rejected_503(fx: Fixture, capture_runner):
    def wrong_app(app_id: str):
        return fx.binding  # binding.app_id == APP_ID, request is for another app

    service = make_orch_service(fx, resolver=wrong_app)
    payload = orch_payload(app_id=OTHER_APP)
    payload["agent_plan"] = {**PLAN_WIRE, "agent_id": CANONICAL_AGENT}
    response = await service.orchestrate_payload(payload)
    assert response.status_code == 503
    assert response.body["error"]["code"] == "tool_runtime_unavailable"


async def test_plan_without_binding_attaches_no_tool_authority(fx: Fixture, capture_runner):
    service = make_orch_service(fx, resolver=lambda app_id: None)
    payload = orch_payload()
    payload["agent_plan"] = PLAN_WIRE
    response = await service.orchestrate_payload(payload)
    assert response.status_code == 500  # captured fake runner always 500s
    request = capture_runner.captured[0]
    assert request.tool_runtime is None
    assert request.tool_registry is None
    assert request.tool_authorization is None
    assert request.agent_definition is None
    assert request.tool_arguments is None


async def test_provisioned_binding_attaches_server_side_authority(fx: Fixture, capture_runner):
    service = make_orch_service(fx)
    payload = orch_payload()
    payload["agent_plan"] = PLAN_WIRE
    payload["tool_arguments"] = {"step-1": {"note": "apply the change"}}
    response = await service.orchestrate_payload(payload)
    assert response.status_code == 500  # captured fake runner always 500s
    request = capture_runner.captured[0]
    assert request.tool_runtime is fx.runtime
    assert request.tool_registry is fx.registry
    assert request.agent_definition is fx.binding.authorities[CANONICAL_AGENT].definition
    assert request.compiled_agent_profile is fx.compiled
    assert request.tool_authorization.app_id == APP_ID
    assert request.tool_arguments == {"step-1": {"note": "apply the change"}}


async def test_invalid_tool_arguments_shape_rejected_with_binding(fx: Fixture, capture_runner):
    service = make_orch_service(fx)
    payload = orch_payload()
    payload["agent_plan"] = PLAN_WIRE
    payload["tool_arguments"] = {"step-1": "not-an-object"}
    response = await service.orchestrate_payload(payload)
    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_tool_arguments"
    assert not capture_runner.captured


def _unit_pause(*, tool_id: str = RUNTIME_WRITE, step_index: int = 1, arguments=None) -> ApprovalPause:
    invocation = ToolInvocation(
        tool_id=tool_id,
        arguments=arguments if arguments is not None else {"note": "apply the change"},
    )
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_unit_c",
        run_id="run_unit_c",
        agent_runtime_id="agent-runtime:unit-c",
        tool_id=tool_id,
        invocation_sha256=tool_invocation_digest(invocation),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=step_index,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _unit_plan(*, objective: str = "apply the change", tool_id: str = RUNTIME_WRITE) -> AgentPlan:
    return AgentPlan(
        agent_id=CANONICAL_AGENT,
        steps=(AgentPlanStep(step_id="step-1", objective=objective, tool_id=tool_id),),
    )


def test_resumed_invocation_byte_identical_passes():
    pause = _unit_pause()
    OrchestrationEngineService._assert_resumed_invocation_matches(
        _unit_plan(), pause, {"step-1": {"note": "apply the change"}}
    )


def test_resumed_invocation_objective_fallback_matches_bridge():
    # Mirrors agent_execution_bridge: no args for the step -> {"query": objective}.
    pause = _unit_pause(arguments={"query": "apply the change"})
    OrchestrationEngineService._assert_resumed_invocation_matches(
        _unit_plan(), pause, {}
    )


def test_resumed_invocation_widened_arguments_rejected():
    pause = _unit_pause()
    with pytest.raises(ServiceContractError) as exc:
        OrchestrationEngineService._assert_resumed_invocation_matches(
            _unit_plan(), pause, {"step-1": {"note": "different change"}}
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "continuation_identity_mismatch"


def test_resumed_invocation_step_tool_mismatch_rejected():
    pause = _unit_pause(tool_id=RUNTIME_SEARCH, arguments={"query": "apply the change"})
    with pytest.raises(ServiceContractError) as exc:
        OrchestrationEngineService._assert_resumed_invocation_matches(
            _unit_plan(tool_id=RUNTIME_WRITE), pause, {}
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "continuation_identity_mismatch"


def test_resumed_invocation_step_index_out_of_range_rejected():
    pause = _unit_pause(step_index=5)
    with pytest.raises(ServiceContractError) as exc:
        OrchestrationEngineService._assert_resumed_invocation_matches(
            _unit_plan(), pause, {"step-1": {"note": "apply the change"}}
        )
    assert exc.value.status_code == 409


def test_resumed_invocation_non_json_arguments_rejected():
    pause = _unit_pause()
    with pytest.raises(ServiceContractError) as exc:
        OrchestrationEngineService._assert_resumed_invocation_matches(
            _unit_plan(), pause, {"step-1": {"note": {1, 2}}}
        )
    assert exc.value.status_code == 409


async def test_orchestration_resume_non_widening_rejects_changed_arguments(fx: Fixture, capture_runner):
    service = make_orch_service(fx)
    pause = _unit_pause()
    pause = ApprovalPause(
        pause_id=pause.pause_id,
        run_id=pause.run_id,
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id=pause.tool_id,
        invocation_sha256=pause.invocation_sha256,
        requirement=pause.requirement,
        step_index=pause.step_index,
        created_at=pause.created_at,
        expires_at=pause.expires_at,
        trace_id="tr_orch_test",
        plan_id=CANONICAL_AGENT,
    )
    ref = service._continuation_store.issue(app_id=APP_ID, pause=pause, plan_id=CANONICAL_AGENT)
    payload = orch_payload()
    payload.update(
        {
            "continuation_ref": ref,
            "decision": {
                "decision_id": "dec_orch_c",
                "pause_id": pause.pause_id,
                "outcome": "approved",
                "authority_ref": "user:admin",
                "evidence_ref": "session:auth",
                "decided_at": datetime.now(timezone.utc).isoformat(),
            },
            "agent_plan": PLAN_WIRE,
            "tool_arguments": {"step-1": {"note": "widened change"}},
        }
    )
    response = await service.resume_payload(payload)
    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_identity_mismatch"
    assert not capture_runner.captured
    # Rejection is pre-claim: the continuation is still resumable, not consumed.
    payload["tool_arguments"] = {"step-1": {"note": "apply the change"}}
    response = await service.resume_payload(payload)
    assert response.status_code == 500  # byte-identical resume reaches the runner
    request = capture_runner.captured[0]
    assert request.tool_runtime is fx.runtime
    assert not hasattr(request, "tool_registry")
    assert not hasattr(request, "tool_resource_policy")
    assert request.pause.pause_id == pause.pause_id
