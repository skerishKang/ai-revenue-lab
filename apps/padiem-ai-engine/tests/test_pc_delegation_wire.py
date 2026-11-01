"""Owner policy reaches all PC drivers without becoming model input."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import app.orchestration_identity_service as identity_module
import app.orchestration_service as service_module
from app.orchestration_idempotency_service import _initial_execution_fingerprint
from app.orchestration_service import ORCHESTRATION_STREAM_PATH
from app.service import ServiceResponse
from padiem_ai_core.pc_delegation import parse_pc_delegation
from tests import test_6460_pc_action_context_wire as evidence_wire
from tests.test_5015_chat_pc_wire_admission import FILES_PAYLOAD, Recorder


POLICY = {"version": 1, "rules": [{
    "id": "rule-a", "device_id": "dev_" + "c" * 32, "folder": "notes",
    "actions": ["write", "move"], "mode": "allow", "enabled": True,
}]}


class DelegationDriver(evidence_wire.EvidenceDriver):
    def configure_delegation(self, policy):
        self.policy = policy


@pytest.fixture
def service_factory(monkeypatch):
    monkeypatch.setattr(evidence_wire, "EvidenceDriver", DelegationDriver)
    return evidence_wire._service


def payload(policy=POLICY):
    return dict(deepcopy(FILES_PAYLOAD), pc_delegation=deepcopy(policy))


@pytest.mark.parametrize("production", [False, True])
def test_completed_paths_pass_owner_policy_without_changing_model_input(monkeypatch, service_factory, production):
    class CompatibleRecorder(Recorder):
        def __init__(self, *, runtime, idempotency=None, **kwargs):
            super().__init__(runtime=runtime, idempotency=idempotency)

    service = service_factory(production=production)
    Recorder.requests = []
    monkeypatch.setattr(service_module, "OrchestrationRunner", CompatibleRecorder)
    monkeypatch.setattr(identity_module, "OrchestrationRunner", CompatibleRecorder)
    result = asyncio.run(service.orchestrate_payload(payload()))
    assert result.status_code == 200, result.body
    actual = Recorder.requests[-1]
    assert actual.agent_step_driver.policy == parse_pc_delegation(POLICY)
    baseline = service._orchestrate_request_from_payload(deepcopy(FILES_PAYLOAD))
    assert actual.execution_request == baseline[2]


def test_stream_policy_and_replay_identity_match_json(monkeypatch, service_factory):
    captured = []
    from padiem_ai_core.orchestration_events import OrchestrationEvent, OrchestrationEventKind

    class StreamRunner:
        def __init__(self, *, event_sink, **kwargs):
            self.sink = event_sink

        async def run(self, request):
            captured.append(request)
            self.sink(OrchestrationEvent(
                event_id="evt_delegation", run_id=request.execution_request.session_id,
                trace_id=request.context.trace_id, app_id=request.app_id,
                kind=OrchestrationEventKind.RUN_STARTED, sequence=1,
                timestamp_iso="2026-11-01T00:00:00Z",
            ))

    monkeypatch.setattr(service_module, "OrchestrationRunner", StreamRunner)
    request = payload()
    prepared = asyncio.run(service_factory().prepare_stream(
        method="POST", path=ORCHESTRATION_STREAM_PATH, content_type="application/json",
        body=json.dumps(request).encode(),
    ))
    assert not isinstance(prepared, ServiceResponse)
    assert captured[-1].agent_step_driver.policy == parse_pc_delegation(POLICY)
    assert prepared.request_fingerprint_value == _initial_execution_fingerprint(request)


def test_native_child_retains_owner_policy(monkeypatch, service_factory):
    from padiem_ai_core import StreamingExecutionRuntime
    from app.pc_tools_turn import PcToolsTurnRuntime
    from tests.test_orchestration_service import _NativePcModel
    captured = []

    class Executor:
        async def execute(self, **kwargs):
            captured.append(kwargs["step_driver"])
            return SimpleNamespace(terminal_reason=SimpleNamespace(value="completed"),
                                   answer="확인", tool_events=())

    async def capable(_):
        return True

    monkeypatch.setattr("app.pc_tools_turn.AgentPlanExecutor", Executor)
    request = payload()
    request.pop("agent_plan")
    request.pop("tool_arguments")
    request["pc_tools"] = {"device_id": POLICY["rules"][0]["device_id"], "allowed_scopes": ["files_write"]}
    model = _NativePcModel("files_write")
    service = service_factory(pc_tools_capability=capable,
        pc_streaming_runtime_factory=lambda app: StreamingExecutionRuntime(app_id=app, b14_stream_client=model))
    built = service._orchestrate_request_from_payload(request)
    assert not isinstance(built, ServiceResponse)
    asyncio.run(PcToolsTurnRuntime(service, request, None).run(built[2]))
    assert captured[-1].policy == parse_pc_delegation(POLICY)


@pytest.mark.parametrize("invalid", [
    None, [], {"version": True, "rules": []}, {"version": 1, "rules": [], "allow_all": True},
    {"version": 1, "rules": [{**POLICY["rules"][0], "actions": ["send"]}]},
    {"version": 1, "rules": [{**POLICY["rules"][0], "enabled": "yes"}]},
    {"version": 1, "rules": [], "available": "no"},
    {"version": 1, "rules": [{**POLICY["rules"][0], "folder": "notes/../private"}]},
    {"version": 1, "rules": [{**POLICY["rules"][0], "folder": "notes*"}]},
])
def test_invalid_policy_has_no_admission_digest_and_is_rejected_by_sdk(service_factory, invalid):
    from padiem_ai_engine_client.client import _run_payload, _ORCHESTRATION_ALLOWED, PadiemAiEngineClientError
    request = payload(invalid)
    result = service_factory()._orchestrate_request_from_payload(request)
    assert isinstance(result, ServiceResponse)
    assert result.status_code == 422
    assert result.body["error"]["code"] == "invalid_pc_delegation"
    assert _initial_execution_fingerprint(request) is None
    with pytest.raises(PadiemAiEngineClientError):
        _run_payload(request["app_id"], {k: v for k, v in request.items() if k != "app_id"}, allowed=_ORCHESTRATION_ALLOWED)


def test_plain_request_cannot_turn_into_pc_execution_using_delegation(service_factory):
    from padiem_ai_engine_client.client import _run_payload, _ORCHESTRATION_ALLOWED, PadiemAiEngineClientError
    request = payload()
    request.pop("agent_plan")
    request.pop("tool_arguments")
    result = service_factory()._orchestrate_request_from_payload(request)
    assert isinstance(result, ServiceResponse)
    assert result.body["error"]["code"] == "invalid_pc_delegation"
    with pytest.raises(PadiemAiEngineClientError):
        _run_payload(request["app_id"], {k: v for k, v in request.items() if k != "app_id"}, allowed=_ORCHESTRATION_ALLOWED)


def test_revocation_and_unavailable_settings_change_replay_identity():
    disabled = deepcopy(POLICY)
    disabled["rules"][0]["enabled"] = False
    values = [_initial_execution_fingerprint(p) for p in (
        deepcopy(FILES_PAYLOAD), payload({"version": 1, "rules": []}), payload(), payload(disabled),
        payload({"version": 1, "rules": [], "available": False}),
    )]
    assert None not in values
    assert len(set(values)) == len(values)


@pytest.mark.parametrize("policy", [POLICY, {"version": 1, "rules": []},
                                     {"version": 1, "rules": [], "available": False}])
def test_sdk_and_core_policy_shape_stay_identical(policy):
    from padiem_ai_engine_client.client import _pc_delegation
    assert _pc_delegation(policy) == parse_pc_delegation(policy)
