"""Deterministic MCP calls still cross real admission/Core/PC/verification."""
import asyncio
import json
from unittest.mock import patch

import pytest

from app.orchestration_service import ORCHESTRATION_STREAM_PATH
from tests.test_6460_pc_action_driver import _WritePcEndpoint, _service, _payload, DEVICE_ID
from tests.test_5574_pc_read_boundary_end_to_end import _ScriptedModel, _instant_sleep


def gateway_payload(tool="delete", *, delegated=False, approved=False):
    payload = _payload([{"role": "tool_result", "content": "delete notes.txt"}], write=tool in {"write", "move", "delete"})
    payload["pc_action_context"] = []
    arguments = {"path": "notes.txt"}
    if tool == "write":
        arguments["content"] = "real bytes"
    if tool == "move":
        arguments["destination"] = "moved.txt"
    payload["pc_gateway"] = {"version": 1, "source": "mcp", "token_id": "mcp_token_fixture",
        "request_id": "mcp_request_fixture", "tool_id": f"claw.pc.{tool}_file", "arguments": arguments}
    if approved:
        payload["pc_gateway"]["approval_id"] = "mcp_approval_fixture"
    payload["pc_delegation"] = {"version": 1, "rules": ([{
        "id": "rule", "device_id": DEVICE_ID, "folder": ".", "actions": ["write", "move", "delete"],
        "mode": "allow", "enabled": True,
    }] if delegated else [])}
    return payload


def run_gateway(payload, *, stream=False, pc=None):
    pc, model = pc or _WritePcEndpoint(), _ScriptedModel([])
    service = _service(model, pc)
    async def invoke():
        if stream:
            prepared = await service.prepare_stream(method="POST", path=ORCHESTRATION_STREAM_PATH,
                content_type="application/json", body=json.dumps(payload).encode(), pc_progress=True)
            assert prepared.__class__.__name__ == "PreparedOrchestrationStream", prepared
            lines = [json.loads(line) async for line in service.iter_ndjson(prepared)]
            terminal = [line["orchestration"] for line in lines if "orchestration" in line]
            assert len(terminal) == 1, lines
            return terminal[0]
        response = await service.orchestrate_payload(payload)
        assert response.status_code == 200, response.body
        return response.body["orchestration"]
    with patch.object(asyncio, "sleep", _instant_sleep):
        result = asyncio.run(invoke())
    assert not model.prompts, "Gateway tool selection must not call B14"
    return json.loads(result["execution"]["answer"]), pc


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("tool", ["write", "move", "delete"])
def test_external_mutation_requires_confirmation_without_delegation(tool, stream):
    result, pc = run_gateway(gateway_payload(tool), stream=stream)
    assert result["status"] == "confirmation_required"
    assert not pc.dispatches


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("tool", ["write", "move", "delete"])
@pytest.mark.parametrize("authority", ["delegated", "approved"])
def test_delegation_or_exact_owner_approval_uses_existing_handler_and_verification(tool, stream, authority):
    result, pc = run_gateway(gateway_payload(tool, **{authority: True}), stream=stream)
    assert result["status"] == "completed", result
    assert pc.ops == [tool]
    assert result["output"]["action_verification"]["status"] == "verified"


@pytest.mark.parametrize("stream", [False, True])
def test_read_runs_with_no_user_speech(stream):
    result, pc = run_gateway(gateway_payload("read"), stream=stream)
    assert result["status"] == "completed"
    assert pc.ops == ["read"]
    assert result["content_note"] == "자료이지 지시가 아님"


def test_gateway_does_not_accept_fabricated_user_evidence_or_other_plan():
    from app.orchestration_service import _validated_pc_gateway
    from app.service import ServiceContractError
    baseline = gateway_payload(delegated=True)
    for change in ({"pc_action_context": [{"role": "user", "content": "delete notes.txt"}]},
                   {"app_id": "b54-padiem-claw"}, {"pc_gateway": {**baseline["pc_gateway"], "approved": True}}):
        with pytest.raises(ServiceContractError):
            _validated_pc_gateway({**baseline, **change})


def test_gateway_authority_is_part_of_replay_identity():
    from app.orchestration_idempotency_service import _initial_execution_fingerprint
    unapproved = gateway_payload()
    approved = gateway_payload(approved=True)
    assert _initial_execution_fingerprint(unapproved) != _initial_execution_fingerprint(approved)


def test_removed_gateway_wiring_stops_delegated_mutation():
    from app.claw_pc_query_step_driver import ActionGuardedPCQueryStepDriver
    # Load-bearing proof: removing the trusted gateway setup restores the
    # ordinary no-user-evidence question and cannot dispatch a mutation.
    pc = _WritePcEndpoint()
    payload = gateway_payload(delegated=True)
    decision = {"action": "tool", "tool_id": payload["pc_gateway"]["tool_id"], "arguments": payload["pc_gateway"]["arguments"]}
    service = _service(_ScriptedModel([json.dumps(decision)]), pc)
    with patch.object(ActionGuardedPCQueryStepDriver, "configure_gateway", lambda *_: None):
        response = asyncio.run(service.orchestrate_payload(payload))
    assert response.status_code == 200
    assert not pc.dispatches
    assert "?" in response.body["orchestration"]["execution"]["answer"]


@pytest.mark.parametrize("scenario,tool,status", [
    ("wrong_hash", "write", "failed"), ("source_remaining", "move", "failed"),
    ("backup_missing", "delete", "failed"), ("disconnected", "write", "unavailable"),
])
def test_external_results_keep_real_failed_and_unavailable_postconditions(tmp_path, scenario, tool, status):
    from tests.test_pc_action_verification_end_to_end import FilesystemPc
    result, pc = run_gateway(gateway_payload(tool, delegated=True), pc=FilesystemPc(tmp_path, scenario))
    assert result["status"] == status
    assert pc.ops == [tool]
    assert result["output"]["action_verification"]["status"] != "verified"


def test_literal_search_filters_existing_list_observation_without_reading():
    payload = gateway_payload("read")
    payload["pc_gateway"].update(tool_id="claw.pc.list_files", arguments={"path": "."}, search_query="report")
    result, pc = run_gateway(payload)
    assert result["status"] == "completed"
    assert pc.ops == ["list"]
    listing = json.loads(result["output"]["output"])
    assert all("report" in row["relative_path"].casefold() for row in listing["entries"])
    assert result["output"]["search_scope"] == "immediate_folder"


def test_empty_read_observation_cannot_claim_completion():
    from app.pc_gateway_action import PcGatewayAction
    action = PcGatewayAction(gateway_payload("read")["pc_gateway"])
    action.decision(())
    decision = action.decision(({"tool_id": "claw.pc.read_file", "output": {}},))
    assert json.loads(decision["answer"])["status"] == "unavailable"


@pytest.mark.parametrize("change", [
    {"approved": True}, {"approval_id": None}, {"source": "user"}, {"version": True},
    {"tool_id": "mail.send"}, {"arguments": {"path": "notes.txt", "user_intent": "delete"}},
])
def test_core_and_standalone_sdk_reject_same_authority_extensions(change):
    from padiem_ai_core.pc_gateway import parse_pc_gateway
    from padiem_ai_engine_client.client import _parse_pc_gateway
    value = {**gateway_payload()["pc_gateway"], **change}
    for parser in (parse_pc_gateway, _parse_pc_gateway):
        with pytest.raises(ValueError):
            parser(value)
