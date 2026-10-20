"""#5015: the real Chat PC wire payload survives the production admission lane.

The fixture is the exact transport body Chat's own builders produce. Chat's
producer test owns that claim end to end and is the record's only writer, so
regenerate it from the producer app, never by editing JSON:

    cd apps/padiem-chat
    REGENERATE_5015_WIRE_RECORD=1 python -m pytest \
        tests/test_5015_chat_pc_engine_wire_fixture.py      # rewrite the record
    python -m pytest tests/test_5015_chat_pc_engine_wire_fixture.py
                                                  # assert record == live body

The producer test uses ``build_chat_pc_agent_plan`` /
``build_chat_pc_files_agent_plan``, ``B62EngineOrchestrationBridge.build_engine_request``,
``get_task_mode("auto")`` and the real ``PadiemAiEngineClient.orchestrate`` body
builder over a recording transport, then compares the emitted bytes with this
file (only ``trace_id`` normalized). Chat production dependencies (starlette)
are not in Engine's CI environment, so the producer test lives with the producer
app and the two sides are joined by this record; the command above is the one
that proves they still match.

It is not a hand-written dict and no assertion here reads Chat's source text.

Everything asserted here runs through the real Production composition
(AdmissionBound -> CanonicalIdempotency -> IdentityBound), with the runner
replaced by a recorder: no provider, PC, Chat transport or network call happens.
"""

from __future__ import annotations

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
    pc_list_files_tool_spec,
    pc_read_file_tool_spec,
    plan_step_arguments,
)

import app.orchestration_identity_service as identity_mod
from app.execution_admission import TrustedExecutionAdmission
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from app.tool_projection import EngineToolBinding, TrustedToolAuthority
from padiem_ai_core.contracts import ApprovalPolicy
from padiem_ai_core.tool_registry import ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import ToolResourcePolicy
from padiem_ai_core.tool_runtime import ToolRuntime
from tests.test_canonical_idempotency_identity import ReplayAdapter

FIXTURE = Path(__file__).with_name("fixtures") / "5015_chat_pc_engine_payloads.json"
PAYLOADS = json.loads(FIXTURE.read_text(encoding="utf-8"))
DRIVES_PAYLOAD = PAYLOADS["drives"]
FILES_PAYLOAD = PAYLOADS["files"]
DEVICE_ID = "dev_" + "c" * 32
DEVICE_ID_B = "dev_" + "d" * 32
CHAT_APP_ID = "padiem-chat"


class AllowingAdapter:
    """Admission stub: the real entitlement decision is out of scope here."""

    def resolve_admission(self, request):
        now = datetime.now(timezone.utc)
        return TrustedExecutionAdmission(
            decision_id="adm_5015_pc",
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


class Recorder:
    """Replaces the Core orchestration runner: records, never executes."""

    requests: list = []
    pc_owners: list = []

    def __init__(self, *, runtime, idempotency=None):
        self._runtime = runtime
        self._idempotency = idempotency

    async def run(self, request):
        from app.claw_pc_query_step_driver import _PC_QUERY_OWNER

        Recorder.requests.append(request)
        Recorder.pc_owners.append(_PC_QUERY_OWNER.get())
        return SimpleNamespace(
            approval_pause=None,
            to_public_dict=lambda: {"run_status": "completed", "answer": "기록 전용"},
        )


def _binding():
    authority = SimpleNamespace(
        definition="definition",
        compiled="compiled",
        authorization="authorization",
    )
    return SimpleNamespace(
        app_id=CHAT_APP_ID,
        tool_runtime="tool_runtime",
        registry="registry",
        resource_policy="resource_policy",
        resolve_authority=lambda agent_id: authority,
    )


def _service():
    return AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: SimpleNamespace(),
        b14_service_bound=True,
        admission_adapter=AllowingAdapter(),
        tool_binding_resolver=lambda app_id: _binding() if app_id == CHAT_APP_ID else None,
        pc_query_step_driver_factory=lambda *args, **kwargs: "owner_pc_step_driver",
    )


def _run(monkeypatch, payload):
    Recorder.requests = []
    Recorder.pc_owners = []
    monkeypatch.setattr(identity_mod, "OrchestrationRunner", Recorder)
    service = _service()
    import asyncio

    return asyncio.run(service.orchestrate_payload(dict(payload)))


def test_the_fixture_still_matches_the_shared_chat_pc_contract():
    provenance = PAYLOADS["_provenance"]
    assert "app.chat_pc_drive.build_chat_pc_agent_plan" in provenance["chat_builders"]
    assert "padiem_ai_engine_client.client.PadiemAiEngineClient.orchestrate " \
           "(_run_payload -> recording transport)" in provenance["chat_builders"]
    assert DRIVES_PAYLOAD["app_id"] == FILES_PAYLOAD["app_id"] == CHAT_APP_ID
    for payload, step_ids, tool_ids in (
        (DRIVES_PAYLOAD, ("query_drives",), (PC_DRIVES_TOOL_ID,)),
        (
            FILES_PAYLOAD,
            ("list_files", "read_file"),
            (PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID),
        ),
    ):
        plan = payload["agent_plan"]
        assert plan["agent_id"] == CHAT_PC_QUERY_AGENT_ID
        assert tuple(step["step_id"] for step in plan["steps"]) == step_ids
        assert tuple(step["tool_id"] for step in plan["steps"]) == tool_ids
        # One server-provided target binds the whole plan; the model never
        # supplies a second key.
        assert list(payload["tool_arguments"].values()) == [{"device_id": DEVICE_ID}]


def test_the_real_chat_drives_payload_reaches_the_runner_with_pc_authority(monkeypatch):
    response = _run(monkeypatch, DRIVES_PAYLOAD)

    assert response.status_code == 200, response.body
    assert len(Recorder.requests) == 1
    request = Recorder.requests[0]
    # Core's plan bridge needs all five of these; the identity lane used to
    # build its own request without them, so the PC plan could not execute.
    assert request.agent_definition == "definition"
    assert request.compiled_agent_profile == "compiled"
    assert request.tool_authorization == "authorization"
    assert request.tool_runtime == "tool_runtime"
    assert request.agent_plan.agent_id == CHAT_PC_QUERY_AGENT_ID
    assert request.tool_arguments == {"query_drives": {"device_id": DEVICE_ID}}
    # The owner-selected step driver, not Core's plan-backed default, drives the
    # closed PC tool schema.
    assert request.agent_step_driver == "owner_pc_step_driver"
    # Execution target is bound to the verified admission subject and run.
    assert Recorder.pc_owners == [
        (
            DRIVES_PAYLOAD["subject_id"],
            DRIVES_PAYLOAD["session_id"],
            CHAT_APP_ID,
            DEVICE_ID,
        )
    ]


def test_the_real_chat_files_payload_reaches_the_runner_with_pc_authority(monkeypatch):
    response = _run(monkeypatch, FILES_PAYLOAD)

    assert response.status_code == 200, response.body
    request = Recorder.requests[0]
    assert request.tool_arguments == {"files": {"device_id": DEVICE_ID}}
    assert request.agent_step_driver == "owner_pc_step_driver"
    assert tuple(step.step_id for step in request.agent_plan.steps) == (
        "list_files",
        "read_file",
    )


def test_tool_arguments_stay_closed_for_a_non_pc_plan(monkeypatch):
    payload = dict(DRIVES_PAYLOAD)
    payload["agent_plan"] = {
        "agent_id": "agent:other:answer@1",
        "steps": [{"step_id": "answer", "objective": "answer", "tool_id": "other.tool"}],
    }

    response = _run(monkeypatch, payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "unsupported_orchestration_field"
    assert Recorder.requests == []


def test_resume_keeps_the_closed_wire_and_still_refuses_tool_arguments(monkeypatch):
    """Deliberate scope: resume does not open a target field.

    A PC tool declares ``ApprovalPolicy.NOT_REQUIRED``, so no server-issued PC
    pause exists to resume, and the paused-invocation digest is derived from the
    step id, which cannot represent the shared ``files`` target. Opening the
    field would widen the resume wire without a provable positive path.
    """
    import asyncio

    payload = dict(FILES_PAYLOAD)
    payload["continuation_ref"] = "cont_" + "f" * 32
    payload["decision"] = {
        "decision_id": "decision_5015",
        "pause_id": "pause_5015",
        "outcome": "approved",
        "authority_ref": "user:trusted",
        "evidence_ref": "evidence:session",
        "decided_at": "2026-10-21T00:00:00+00:00",
    }
    Recorder.requests = []
    monkeypatch.setattr(identity_mod, "OrchestrationRunner", Recorder)

    response = asyncio.run(_service().resume_payload(payload))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "unsupported_orchestration_field"
    assert Recorder.requests == []


def test_the_pc_tools_never_pause_so_no_pc_continuation_can_exist():
    """#5015: the PC lane has no server-issued approval pause to resume.

    Every PC tool declares ``ApprovalPolicy.NOT_REQUIRED``, so the Engine can
    never issue a PC pause and no PC continuation can exist. That is why the
    resume wire stays closed here: a resume request that carries a target is
    refused before any tool is reached.
    """
    for spec in (
        pc_drives_tool_spec(),
        pc_list_files_tool_spec(),
        pc_read_file_tool_spec(),
    ):
        assert spec.approval_policy is ApprovalPolicy.NOT_REQUIRED


def test_a_malformed_pc_target_is_refused_before_the_runner(monkeypatch):
    payload = dict(FILES_PAYLOAD)
    # A path separator is not part of either canonical device identity form.
    payload["tool_arguments"] = {"files": {"device_id": "bad/device"}}

    response = _run(monkeypatch, payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_tool_arguments"
    assert Recorder.requests == []


class SyntheticPcTool:
    """The PC tool, executed by the real Core ToolRuntime, but without a PC.

    The registered spec, the input schema, the agent authority and the
    authorization are the production ones, so the tool call is validated
    exactly as in Production. Only the handler is synthetic: no PC request,
    provider call or network egress happens.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, arguments):
        self.calls.append(dict(arguments))
        return {"drives": [{"Name": "C:", "Root": "C:\\"}]}


class UnusedModelRuntime:
    """The plan bridge answers from the tool lane, so the model lane is unused."""

    async def run(self, request):
        raise AssertionError("the model lane must not run in this harness")


def _with_key(payload):
    """Same run and same durable key, with the execution context Chat omits."""
    keyed = dict(payload)
    keyed["execution_context"] = {
        **payload["execution_context"],
        "idempotency_key": "idem_5015_pc_run",
    }
    return keyed


def _synthetic_pc_binding():
    """The production PC binding with one synthetic tool handler."""
    contract = build_pc_query_product_contract(
        app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID
    )
    tool = SyntheticPcTool()
    tool_runtime = ToolRuntime()
    tool_runtime.register(pc_drives_tool_spec(), tool)
    binding = EngineToolBinding(
        app_id=CHAT_APP_ID,
        tool_runtime=tool_runtime,
        registry=ToolRegistrySnapshot.from_entries(contract.registry_entries),
        authorities={
            CHAT_PC_QUERY_AGENT_ID: TrustedToolAuthority(
                canonical_agent_id=CHAT_PC_QUERY_AGENT_ID,
                definition=contract.definition,
                compiled=contract.compiled,
                authorization=contract.authorization,
            )
        },
        authorization_provider=None,
        resource_policy=ToolResourcePolicy(),
    )
    return binding, tool


def _synthetic_step_driver_factory():
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


def _composed_service():
    binding, tool = _synthetic_pc_binding()
    service = AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: UnusedModelRuntime(),
        b14_service_bound=True,
        admission_adapter=AllowingAdapter(),
        idempotency_adapter=ReplayAdapter(),
        tool_binding_resolver=lambda app_id: binding if app_id == CHAT_APP_ID else None,
        pc_query_step_driver_factory=_synthetic_step_driver_factory(),
    )
    return service, tool


def test_one_key_replays_pc_a_and_refuses_pc_b_without_a_second_execution():
    """#5015: the durable fingerprint covers the validated PC target.

    Same service, same key, same run: PC A executes once, a re-request for A
    reuses that result, and changing only the target to PC B is a material
    change under the same key, so it must be refused instead of returning A's
    result. The synthetic tool runs exactly once for all three requests.
    """
    import asyncio

    service, tool = _composed_service()

    first = asyncio.run(service.orchestrate_payload(_with_key(DRIVES_PAYLOAD)))
    replay = asyncio.run(service.orchestrate_payload(_with_key(DRIVES_PAYLOAD)))
    other_pc = _with_key(DRIVES_PAYLOAD)
    other_pc["tool_arguments"] = {"query_drives": {"device_id": DEVICE_ID_B}}
    conflict = asyncio.run(service.orchestrate_payload(other_pc))

    assert first.status_code == 200, first.body
    assert replay.status_code == 200, replay.body
    assert replay.body["orchestration"]["events"][-1]["metadata"]["replay"] is True
    assert conflict.status_code == 409
    assert conflict.body["error"]["code"] == "idempotency_conflict"
    # One tool execution for the whole key/run: the replay reuses PC A's
    # result, and PC B is refused before the tool is reached at all.
    assert tool.calls == [{"device_id": DEVICE_ID}]
