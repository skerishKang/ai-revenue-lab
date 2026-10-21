"""#5015: the trusted PC tool authority follows the canonical PC plan.

The identity-bound lane is the innermost service of the Production composition
(AdmissionBound -> CanonicalIdempotency -> IdentityBound), so it is the lane
that actually builds the ``OrchestrationRequest`` and runs Core. #5429 attached
the trusted tool authority there, but it attached it to the presence of the
optional ``tool_arguments`` wire field instead of to the canonical PC plan.

Both product adapters also send the canonical PC plan *without* that field when
the owner has no explicit PC selection and the Broker resolves the pinned
target from the owner scope
(``kagent.p01_adapter`` builds ``tool_arguments=None`` in that case, and the
Claw client accepts a plan whose arguments are ``None``). For that request the
identity lane attached no tool authority at all, so the plan started and then
failed inside Core with an opaque ``engine_internal_error`` instead of running
the PC tool.

This test proves the authority is bound to the canonical PC plan:

* the canonical PC plan runs with and without a device hint, and the real Core
  runtime executes the real tool spec;
* a wrong product identity or a non-canonical PC plan shape is refused before
  the runner, with a bounded error;
* a non-PC plan still gets no tool authority.

The synthetic tool runs the real Core ``ToolRuntime`` with the production tool
spec, agent authority, authorization and step policy, so the tool call is
validated exactly as in Production while no PC request, provider call or
network egress happens.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from kagent.pc_query_adapter import (
    CHAT_PC_QUERY_AGENT_ID,
    PC_DRIVES_TOOL_ID,
    PC_LIST_FILES_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    StructuredPCQueryStepDriver,
    build_pc_query_product_contract,
    pc_drives_tool_spec,
    plan_step_arguments,
)

import app.orchestration_identity_service as identity_mod
from app.execution_admission import TrustedExecutionAdmission
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from app.tool_projection import EngineToolBinding, TrustedToolAuthority
from padiem_ai_core.tool_registry import ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import ToolResourcePolicy
from padiem_ai_core.tool_runtime import ToolRuntime
from tests.test_canonical_idempotency_identity import ReplayAdapter

CHAT_APP_ID = "padiem-chat"
CLAW_APP_ID = "b54-padiem-claw"
CLAW_PC_QUERY_AGENT_ID = "agent:padiem:claw-pc-query@1"
DEVICE_ID = "dev_" + "c" * 32

FIXTURE = Path(__file__).with_name("fixtures") / "5015_chat_pc_engine_payloads.json"
DRIVES_PAYLOAD = json.loads(FIXTURE.read_text(encoding="utf-8"))["drives"]


class AllowingAdapter:
    """Admission stub: the real entitlement decision is out of scope here."""

    def resolve_admission(self, request):
        now = datetime.now(timezone.utc)
        return TrustedExecutionAdmission(
            decision_id="adm_5015_pc_authority",
            app_id=request.app_id,
            subject_id=request.subject_id,
            capability=request.capability,
            allowed=True,
            authority_ref="control-plane:entitlement:run",
            policy_revision="policy:run:5015",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
            request_fingerprint=request.request_fingerprint,
        )


class SyntheticPcTool:
    """The PC tool, executed by the real Core ToolRuntime, but without a PC."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, arguments):
        self.calls.append(dict(arguments))
        return {"drives": [{"Name": "C:", "Root": "C:\\"}]}


class UnusedModelRuntime:
    """The plan bridge answers from the tool lane, so the model lane is unused."""

    async def run(self, request):
        raise AssertionError("the model lane must not run in this harness")


class RecordingRunner:
    """Records the request Core would receive, without running it."""

    requests: list = []

    def __init__(self, *, runtime, idempotency=None):
        self._runtime = runtime
        self._idempotency = idempotency

    async def run(self, request):
        RecordingRunner.requests.append(request)
        return SimpleNamespace(
            approval_pause=None,
            to_public_dict=lambda: {"run_status": "completed", "answer": "recorded"},
        )


def _binding(*, app_id: str, agent_id: str, tool: SyntheticPcTool) -> EngineToolBinding:
    contract = build_pc_query_product_contract(app_id=app_id, agent_id=agent_id)
    tool_runtime = ToolRuntime()
    tool_runtime.register(pc_drives_tool_spec(), tool)
    return EngineToolBinding(
        app_id=app_id,
        tool_runtime=tool_runtime,
        registry=ToolRegistrySnapshot.from_entries(contract.registry_entries),
        authorities={
            agent_id: TrustedToolAuthority(
                canonical_agent_id=agent_id,
                definition=contract.definition,
                compiled=contract.compiled,
                authorization=contract.authorization,
            )
        },
        authorization_provider=None,
        resource_policy=ToolResourcePolicy(),
    )


def _step_driver_factory():
    """The product step policy with a synthetic model step: no model call."""

    async def select_step(*, context, compiled_profile, observations):
        if not observations:
            return {"action": "tool", "tool_id": PC_DRIVES_TOOL_ID, "arguments": {}}
        return {"action": "complete", "answer": "synthetic pc drive result"}

    def factory(model_id, model_policy, task_type, optimize_for, *, tool_arguments=None):
        return StructuredPCQueryStepDriver(
            select_step=select_step,
            static_arguments=plan_step_arguments(tool_arguments, "query_drives"),
        )

    return factory


def _service(*, app_id: str, agent_id: str, tool: SyntheticPcTool, recorder: bool = False):
    binding = _binding(app_id=app_id, agent_id=agent_id, tool=tool)
    service = AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda _app_id: UnusedModelRuntime(),
        b14_service_bound=True,
        admission_adapter=AllowingAdapter(),
        idempotency_adapter=ReplayAdapter(),
        tool_binding_resolver=lambda _app_id: binding if _app_id == app_id else None,
        pc_query_step_driver_factory=_step_driver_factory(),
    )
    return service


def _payload(
    *,
    app_id: str = CHAT_APP_ID,
    agent_id: str = CHAT_PC_QUERY_AGENT_ID,
    device_id: str | None = DEVICE_ID,
    tool_arguments_key: str = "query_drives",
    plan_shape: str = "drives",
) -> dict:
    payload = dict(DRIVES_PAYLOAD)
    payload["app_id"] = app_id
    payload["session_id"] = "chat_pcq_5015_authority"
    if plan_shape == "drives":
        steps = [
            {
                "step_id": "query_drives",
                "objective": "Query verified PC filesystem drives",
                "tool_id": PC_DRIVES_TOOL_ID,
            }
        ]
    else:
        steps = [
            {
                "step_id": "not_a_canonical_pc_step",
                "objective": "not a canonical PC plan shape",
                "tool_id": PC_DRIVES_TOOL_ID,
            }
        ]
    payload["agent_plan"] = {"agent_id": agent_id, "steps": steps}
    payload.pop("tool_arguments", None)
    if device_id is not None:
        payload["tool_arguments"] = {tool_arguments_key: {"device_id": device_id}}
    return payload


def _run(monkeypatch, service, payload, *, recorder: bool = True):
    if recorder:
        RecordingRunner.requests = []
        monkeypatch.setattr(identity_mod, "OrchestrationRunner", RecordingRunner)
    return asyncio.run(service.orchestrate_payload(dict(payload)))


def test_the_canonical_pc_plan_runs_with_a_device_hint(monkeypatch):
    tool = SyntheticPcTool()
    service = _service(app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID, tool=tool)

    response = _run(monkeypatch, service, _payload(), recorder=False)

    assert response.status_code == 200, response.body
    assert tool.calls == [{"device_id": DEVICE_ID}]


def test_the_canonical_pc_plan_runs_without_a_device_hint(monkeypatch):
    """The product-designed owner-scoped request keeps its tool authority.

    Without the fix this request carried no trusted tool authority, so the
    plan started and then failed inside Core instead of running the PC tool.
    """
    tool = SyntheticPcTool()
    service = _service(app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID, tool=tool)

    response = _run(monkeypatch, service, _payload(device_id=None), recorder=False)

    assert response.status_code == 200, response.body
    # The owner scope resolves the pinned target, so the tool call carries no
    # device hint. The tool still ran.
    assert tool.calls == [{}]


def test_the_canonical_pc_plan_runs_without_a_device_hint_for_the_claw_product(monkeypatch):
    tool = SyntheticPcTool()
    service = _service(app_id=CLAW_APP_ID, agent_id=CLAW_PC_QUERY_AGENT_ID, tool=tool)

    response = _run(
        monkeypatch, service,
        _payload(app_id=CLAW_APP_ID, agent_id=CLAW_PC_QUERY_AGENT_ID, device_id=None),
        recorder=False,
    )

    assert response.status_code == 200, response.body
    assert tool.calls == [{}]


def test_a_wrong_pc_product_identity_is_refused_before_the_runner(monkeypatch):
    tool = SyntheticPcTool()
    service = _service(app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID, tool=tool)

    # The Chat product presents the Claw PC agent id.
    response = _run(
        monkeypatch, service,
        _payload(app_id=CHAT_APP_ID, agent_id=CLAW_PC_QUERY_AGENT_ID, device_id=None),
    )

    assert response.status_code == 400, response.body
    assert response.body["error"]["code"] == "invalid_plan"
    assert RecordingRunner.requests == []
    assert tool.calls == []


def test_a_non_canonical_pc_plan_shape_is_refused_before_the_runner(monkeypatch):
    tool = SyntheticPcTool()
    service = _service(app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID, tool=tool)

    response = _run(
        monkeypatch, service,
        _payload(plan_shape="other", device_id=None),
    )

    assert response.status_code == 400, response.body
    assert response.body["error"]["code"] == "invalid_plan"
    assert RecordingRunner.requests == []
    assert tool.calls == []


def test_a_non_pc_plan_still_gets_no_tool_authority(monkeypatch):
    tool = SyntheticPcTool()
    service = _service(app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID, tool=tool)
    payload = _payload(device_id=None)
    payload["agent_plan"] = {
        "agent_id": "agent:other:answer@1",
        "steps": [{"step_id": "answer", "objective": "answer", "tool_id": "other.tool"}],
    }

    response = _run(monkeypatch, service, payload)

    # The non-PC lane is unchanged: it reaches the runner without any trusted
    # PC tool authority, exactly as before this change.
    assert response.status_code == 200, response.body
    request = RecordingRunner.requests[0]
    assert request.tool_authorization is None
    assert request.tool_runtime is None
    assert request.agent_definition is None
    assert tool.calls == []


def test_the_pc_files_plan_keeps_its_shared_target_without_a_hint(monkeypatch):
    """The two-step list/read plan is canonical too, with one shared target.

    The captured request is the claim, not the response code. A recorder that
    always succeeds reports 200 for a request that carries no tool authority
    at all, so this asserts the attachment itself: the trusted tool authority,
    the tool runtime and the owner-selected PC step driver must be present on
    the request Core receives.
    """
    tool = SyntheticPcTool()
    service = _service(app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID, tool=tool)
    payload = _payload(device_id=None)
    payload["agent_plan"] = {
        "agent_id": CHAT_PC_QUERY_AGENT_ID,
        "steps": [
            {
                "step_id": "list_files",
                "objective": "List the approved folder on the verified owner PC",
                "tool_id": PC_LIST_FILES_TOOL_ID,
            },
            {
                "step_id": "read_file",
                "objective": "Read the requested UTF-8 text file",
                "tool_id": PC_READ_FILE_TOOL_ID,
            },
        ],
    }

    response = _run(monkeypatch, service, payload)

    assert response.status_code == 200, response.body
    assert len(RecordingRunner.requests) == 1
    request = RecordingRunner.requests[0]
    # Core's plan bridge needs all five of these. Without them the plan runs
    # with no trusted authority and the PC tool is never reachable.
    assert request.agent_definition is not None
    assert request.compiled_agent_profile is not None
    assert request.tool_authorization is not None
    assert request.tool_runtime is not None
    # The owner-selected step driver, not Core's plan-backed default.
    assert request.agent_step_driver is not None
    assert request.agent_plan.agent_id == CHAT_PC_QUERY_AGENT_ID
    assert tuple(step.step_id for step in request.agent_plan.steps) == (
        "list_files",
        "read_file",
    )
    # No hint means no named target; the owner scope resolves the pinned one.
    assert request.tool_arguments == {}
    # The recorder replaces the runner, so the tool itself is never called here.
    assert tool.calls == []
