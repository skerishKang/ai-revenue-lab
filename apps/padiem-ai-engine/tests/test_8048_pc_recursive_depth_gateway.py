"""#8048 — the gateway's recursive search and depth listing reach the PC.

Both failures were before any PC dispatch. The recursive call was refused at
the orchestration gate because Chat's closed target key had no canonical step
alias, and the deep listing was refused by the step driver's argument table and
by the registered list ToolSpec. This file drives the real admission, agent
runtime, tool runtime and PC callback for both calls.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from app.orchestration_service import OrchestrationEngineService
from app.orchestration_wire import _parse_agent_plan
from app.pc_gateway_action import PcGatewayAction
from kagent.pc_query_adapter import (
    pc_list_files_tool_spec,
    pc_read_file_tool_spec,
)
from padiem_ai_core.tool_runtime import _BoundedSchemaValidator, _thaw_json

from tests.test_5574_pc_read_boundary_end_to_end import (
    DEVICE_ID,
    _instant_sleep,
    _Response,
    _ScriptedModel,
)
from tests.test_6460_pc_action_driver import _service, _WritePcEndpoint
from tests.test_mcp_gateway_pc_execution import gateway_payload, run_gateway

KOREAN_QUERY = "보고서"
KOREAN_ROW = "한글 폴더\\보고서.txt"


class _SearchPc(_WritePcEndpoint):
    """A read-only PC facade that answers one bounded name-search dispatch."""

    def __init__(self):
        super().__init__()
        self.search_dispatches = []

    async def fetch(self, request):
        body = json.loads(request.body)
        if body["mode"] == "dispatch" and body["op"] == "search":
            self.search_dispatches.append(body)
            output = json.dumps({
                "ok": True, "query": body.get("query"), "mode": "name",
                "engine": "list", "office": "none", "count": 1,
                "truncated": False, "scan_truncated": False, "has_more": False,
                "entries": [{"path": KOREAN_ROW, "size_bytes": 12,
                             "modified_utc": "2026-11-19T00:00:00.000Z",
                             "content_state": "name_only", "line": None,
                             "snippet": "", "reason": ""}],
            }, ensure_ascii=False)
            dispatch_id = "dsp_8048_" + str(len(self.rows) + 1)
            self.rows[dispatch_id] = {
                "run_id": body["run_id"], "kind": "command", "op": "search",
                "output": output, "content_bytes": len(output.encode("utf-8")),
            }
            return _Response({"ok": True, "dispatch": {
                "dispatch_id": dispatch_id, "run_id": body["run_id"],
                "kind": "command", "device_id": body["device_id"]}})
        return await super().fetch(request)


def _recursive_payload():
    payload = gateway_payload("read")
    payload["agent_plan"] = {
        "agent_id": payload["agent_plan"]["agent_id"],
        "steps": [{"step_id": "search_files", "objective": "Find files",
                   "tool_id": "claw.pc.search_files"}],
    }
    payload["tool_arguments"] = {"files_search": {"device_id": DEVICE_ID}}
    payload["declared_plan"] = "files_search"
    payload["pc_gateway"].update(tool_id="claw.pc.search_files",
                                 arguments={"path": "."}, search_query=KOREAN_QUERY)
    return payload


def _depth_payload(depth):
    payload = gateway_payload("read")
    payload["pc_gateway"].update(tool_id="claw.pc.list_files",
                                 arguments={"path": ".", "depth": depth})
    return payload


def test_recursive_gateway_call_dispatches_and_relays_relative_rows():
    pc = _SearchPc()
    payload = _recursive_payload()
    service = _service(_ScriptedModel([]), pc)

    async def scenario():
        with patch.object(asyncio, "sleep", _instant_sleep):
            return await service.orchestrate_payload(payload)

    response = asyncio.run(scenario())
    assert response.status_code == 200
    result = json.loads(response.body["orchestration"]["execution"]["answer"])
    assert result["status"] == "completed"
    assert result["output"]["search_scope"] == "recursive_folder"
    assert result["output"]["entries"][0]["path"] == KOREAN_ROW
    assert [call["op"] for call in pc.search_dispatches] == ["search"]
    assert pc.search_dispatches[0]["query"] == KOREAN_QUERY


@pytest.mark.parametrize("depth", [2, 3])
def test_depth_gateway_call_dispatches_one_bounded_walk(depth):
    payload = _depth_payload(depth)
    result, pc = run_gateway(payload)
    assert result["status"] == "completed"
    assert pc.ops == ["list"]
    assert pc.dispatches[0]["depth"] == depth
    assert pc.dispatches[0]["path"] == "."


def test_the_list_tool_spec_names_the_tuning_keys_and_the_read_tool_does_not():
    listing = _BoundedSchemaValidator.compile(
        _thaw_json(pc_list_files_tool_spec().input_schema))
    for arguments in ({"path": "docs", "depth": 2}, {"path": "docs", "offset": 50}):
        listing.validate(arguments)
    for bad in ({"path": "docs", "depth": "2"}, {"path": "docs", "depth": 0}):
        with pytest.raises(ValueError):
            listing.validate(bad)
    reading = _BoundedSchemaValidator.compile(
        _thaw_json(pc_read_file_tool_spec().input_schema))
    with pytest.raises(ValueError):
        reading.validate({"path": "docs", "depth": 2})


def test_the_closed_plan_hint_accepts_both_step_and_scope_keys():
    from tests.test_5574_pc_read_boundary_end_to_end import FILES_RECORD
    plan = FILES_RECORD["agent_plan"]

    def with_step(step_id, tool_id):
        return {**plan, "steps": [{"step_id": step_id, "objective": "one",
                                   "tool_id": tool_id}]}

    cases = (
        (with_step("search_files", "claw.pc.search_files"), "files_search"),
        (with_step("search_contents", "claw.pc.search_contents"), "files_search_contents"),
        (with_step("read_chunk", "claw.pc.read_file_chunk"), "files_chunk"),
    )
    for named_plan, key in cases:
        OrchestrationEngineService._validate_pc_plan_tool_arguments(
            _parse_agent_plan(named_plan), {key: {"device_id": DEVICE_ID}})


def test_the_signed_search_arguments_are_not_treated_as_a_mutated_request():
    action = PcGatewayAction({
        "version": 1, "source": "mcp", "token_id": "tok", "request_id": "req",
        "tool_id": "claw.pc.search_files", "arguments": {"path": "."},
        "search_query": KOREAN_QUERY,
    })
    decision = action.decision(observations=())
    assert decision["arguments"] == {"path": ".", "query": KOREAN_QUERY}
    assert action.question(decision["tool_id"], {"query": KOREAN_QUERY},
                           policy=None, device_id=None, context=None) is None


def test_external_search_continuation_keeps_only_the_job_id():
    job_id = "dsp_" + "a" * 32
    action = PcGatewayAction({
        "version": 1, "source": "mcp", "token_id": "tok", "request_id": "req",
        "tool_id": "claw.pc.search_files", "arguments": {"job_id": job_id},
        "search_query": KOREAN_QUERY,
    })
    decision = action.decision([])
    assert decision["action"] == "tool"
    assert decision["arguments"] == {"job_id": job_id}
    assert action.question(decision["tool_id"], decision["arguments"],
                           policy=None, device_id=None, context=None) is None


def test_external_recursive_search_with_absolute_folder_dispatches():
    """#8048: an external connector may name a whole-drive absolute folder.

    Chat's gateway already checks that folder against the owner's registered
    roots at the signed handler. The model-output relative-path guard must not
    refuse it before any dispatch (the live run answered unavailable).
    """
    pc = _SearchPc()
    payload = _recursive_payload()
    payload.pop("declared_plan", None)  # the live external call declares none
    win_folder = "G:\Ddrive\worktrees"
    payload["pc_gateway"]["arguments"] = {"path": win_folder}
    service = _service(_ScriptedModel([]), pc)

    async def scenario():
        with patch.object(asyncio, "sleep", _instant_sleep):
            return await service.orchestrate_payload(payload)

    response = asyncio.run(scenario())
    assert response.status_code == 200
    result = json.loads(response.body["orchestration"]["execution"]["answer"])
    assert result["status"] == "completed"
    assert [call["op"] for call in pc.search_dispatches] == ["search"]
