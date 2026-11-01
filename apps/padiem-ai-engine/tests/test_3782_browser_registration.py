"""The browser scope reaches the existing PC runtime without widening files."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

# The JavaScript/Python wire client is its own package beside the Engine app;
# `uv sync` installs the Engine, not that sibling, so the one contract this
# file shares with it is imported from its source tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "python"))

from app.orchestration_service import (
    _parse_agent_plan, _canonical_pc_plan, _validated_pc_tool_arguments,
    _validated_pc_declared_plan, _pc_query_selected_device,
)
from app.pc_tools_turn import definitions, parse_pc_tools, tool_names
from app.service import ServiceContractError
from kagent.pc_browser_tools import BROWSER_TOOL_IDS, BROWSER_CANONICAL_IDS
from kagent.pc_query_adapter import (
    PCQueryStepError, StructuredPCQueryStepDriver, build_pc_query_product_contract,
    PC_REQUEST_SCOPE_TOOLS,
)
from padiem_ai_engine_client.client import _trusted_pc_tool_arguments, _pc_tools_context


DEVICE = "dev_" + "c" * 32
OPS = ("browser_open", "browser_read", "browser_screenshot", "browser_act")


def payload(app_id="padiem-chat"):
    agent = "chat" if app_id == "padiem-chat" else "claw"
    return {"app_id": app_id, "subject_id": "sub_example", "session_id": "run_example",
            "agent_plan": {"agent_id": f"agent:padiem:{agent}-pc-query@1",
                           "steps": [{"step_id": op, "tool_id": "claw.pc." + op,
                                      "objective": "Use the delegated browser"} for op in OPS]},
            "tool_arguments": {"browser": {"device_id": DEVICE}}, "declared_plan": "browser"}


@pytest.mark.parametrize("app_id", ["padiem-chat", "b54-padiem-claw"])
def test_browser_plan_and_target_survive_both_wire_validators(app_id):
    value = payload(app_id)
    plan = _parse_agent_plan(value["agent_plan"])
    assert _canonical_pc_plan(app_id, plan) is plan
    assert _trusted_pc_tool_arguments(value["agent_plan"], value["tool_arguments"])
    assert _validated_pc_tool_arguments(value) == value["tool_arguments"]
    assert _validated_pc_declared_plan(value) == "browser"
    assert _pc_query_selected_device(value["tool_arguments"]) == DEVICE


@pytest.mark.parametrize("foreign", ["files", "files_write", "query_drives"])
def test_browser_plan_cannot_borrow_a_file_target(foreign):
    value = payload()
    value["tool_arguments"] = {foreign: {"device_id": DEVICE}}
    assert not _trusted_pc_tool_arguments(value["agent_plan"], value["tool_arguments"])
    with pytest.raises(ServiceContractError):
        _validated_pc_tool_arguments(value)


@pytest.mark.parametrize("app_id", ["padiem-chat", "b54-padiem-claw"])
def test_compiled_product_registry_and_authority_include_the_same_four_tools(app_id):
    contract = build_pc_query_product_contract(app_id=app_id,
        agent_id=payload(app_id)["agent_plan"]["agent_id"])
    assert BROWSER_TOOL_IDS <= set(contract.authorization.externally_authorized_tools)
    assert BROWSER_TOOL_IDS <= set(contract.authorization.granted_auth_scopes)
    assert set(BROWSER_CANONICAL_IDS.values()) <= set(contract.definition.allowed_tool_ids)
    registered = {entry.canonical_tool_id for entry in contract.registry_entries}
    assert set(BROWSER_CANONICAL_IDS.values()) <= registered
    assert not BROWSER_TOOL_IDS & PC_REQUEST_SCOPE_TOOLS["files"]
    assert not BROWSER_TOOL_IDS & PC_REQUEST_SCOPE_TOOLS["files_write"]


@pytest.mark.parametrize("tool_id,args", [
    ("claw.pc.browser_open", {"url": "https://example.com/"}),
    ("claw.pc.browser_read", {}), ("claw.pc.browser_screenshot", {}),
    ("claw.pc.browser_act", {"action": "click", "text": "More information"}),
])
def test_structured_decision_uses_browser_contract_and_admitted_ceiling(tool_id, args):
    driver = StructuredPCQueryStepDriver(select_step=lambda *a: None, allowed_tool_ids=BROWSER_TOOL_IDS)
    decision = driver._decision({"action": "tool", "tool_id": tool_id, "arguments": args}, [])
    assert decision.invocation.tool_id == tool_id
    assert dict(decision.invocation.arguments) == args
    file_driver = StructuredPCQueryStepDriver(select_step=lambda *a: None,
        allowed_tool_ids=PC_REQUEST_SCOPE_TOOLS["files"])
    with pytest.raises(PCQueryStepError):
        file_driver._decision({"action": "tool", "tool_id": tool_id, "arguments": args}, [])


def test_native_browser_only_context_exposes_four_browser_tools_without_file_wrappers():
    context = {"device_id": DEVICE, "allowed_scopes": ["browser"]}
    assert set(tool_names(context)) == set(OPS)
    specs = {tool.name: tool for tool in definitions(context)}
    assert set(specs) == set(OPS)
    for spec in specs.values():
        parameters = spec.parameters
        assert parameters["additionalProperties"] is False
        assert not {"device_id", "page_url", "confirmation"} & set(parameters["properties"])


def test_sdk_and_engine_accept_all_five_distinct_server_scopes():
    value = {"app_id": "padiem-chat", "subject_id": "sub_example", "session_id": "run_example",
             "pc_tools": {"device_id": DEVICE,
                          "allowed_scopes": ["query_drives", "files_list", "files", "files_write", "browser"]}}
    assert parse_pc_tools(value) == _pc_tools_context(value, value["app_id"])
    bad = deepcopy(value)
    bad["pc_tools"]["allowed_scopes"].append("browser")
    with pytest.raises(ServiceContractError):
        parse_pc_tools(bad)


@pytest.mark.parametrize("tool_id,args", [
    ("claw.pc.browser_open", {"url": "https://example.com/"}),
    ("claw.pc.browser_read", {}), ("claw.pc.browser_screenshot", {}),
    ("claw.pc.browser_act", {"action": "click", "text": "More information"}),
    ("claw.pc.browser_act", {"action": "type", "name": "Search", "value": "example"}),
])
def test_sdk_gateway_browser_arguments_match_core(tool_id, args):
    from padiem_ai_core.pc_gateway import parse_pc_gateway
    from padiem_ai_engine_client.client import _parse_pc_gateway
    value = {"version": 1, "source": "mcp", "token_id": "token_example",
             "request_id": "request_example", "tool_id": tool_id, "arguments": args,
             "browser_context": {"url": "https://EXAMPLE.com#fragment"}}
    assert _parse_pc_gateway(value) == parse_pc_gateway(value)


@pytest.mark.parametrize("url", [
    "https://example.com/", "https://EXAMPLE.com:443/a?q=yes#fragment",
    "http://8.8.8.8/", "https://[2606:4700:4700::1111]/", "https://한국.example/",
    "file:///tmp/secret", "http://localhost/", "http://127.0.0.1/",
    "http://169.254.169.254/", "http://[::ffff:127.0.0.1]/", "http://192.168.1.1/",
    "http://2130706433/", "https://service.internal/", "http://user:pass@example.com/",
    "https://example.com:99999/", "https://example.com/\nsecret",
])
def test_gateway_browser_url_decisions_match_dependency_free_sdk(url):
    from padiem_ai_core.pc_gateway import parse_pc_gateway
    from padiem_ai_engine_client.client import _parse_pc_gateway
    value = {"version": 1, "source": "mcp", "token_id": "token_example",
             "request_id": "request_example", "tool_id": "claw.pc.browser_open",
             "arguments": {"url": url}, "browser_context": {"url": url}}
    try:
        expected = parse_pc_gateway(value)
    except ValueError:
        with pytest.raises(ValueError):
            _parse_pc_gateway(value)
    else:
        assert _parse_pc_gateway(value) == expected


@pytest.mark.parametrize("change", [
    {"approval_id": "approval_example"}, {"search_query": "example"},
    {"arguments": {"url": "https://example.com/", "confirmation": True}},
    {"browser_context": {"url": "https://example.com/", "device_id": DEVICE}},
    {"tool_id": "claw.pc.browser_act", "arguments": {"action": "click"}},
    {"tool_id": "claw.pc.browser_act", "arguments": {"action": "type", "text": "Search"}},
])
def test_gateway_browser_rejects_forged_authority_or_incomplete_action(change):
    from padiem_ai_core.pc_gateway import parse_pc_gateway
    from padiem_ai_engine_client.client import _parse_pc_gateway
    value = {"version": 1, "source": "mcp", "token_id": "token_example",
             "request_id": "request_example", "tool_id": "claw.pc.browser_open",
             "arguments": {"url": "https://example.com/"}, **change}
    for parser in (parse_pc_gateway, _parse_pc_gateway):
        with pytest.raises(ValueError):
            parser(value)


@pytest.mark.parametrize("name,args", [
    ("browser_open", {"url": "https://example.com/"}), ("browser_read", {}),
    ("browser_screenshot", {}), ("browser_act", {"action": "click", "text": "More information"}),
])
def test_native_browser_selection_enters_same_admitted_pc_driver(monkeypatch, name, args):
    import asyncio
    from types import SimpleNamespace
    from padiem_ai_core import StreamingExecutionRuntime
    from app.pc_tools_turn import PcToolsTurnRuntime
    from app.service import ServiceResponse
    from tests.test_6460_pc_action_context_wire import _service, _payload, EvidenceDriver, CONTEXT
    from tests.test_pc_native_remote_tools import Native

    captured = []
    initial = []

    class Executor:
        async def execute(self, **kwargs):
            captured.append(kwargs)
            assert [step.step_id for step in kwargs["plan"].steps] == list(OPS)
            return SimpleNamespace(terminal_reason=SimpleNamespace(value="completed"),
                                   answer="Example Domain", tool_events=())

    def driver(*unused, **options):
        initial.append(options.get("initial_decision"))
        return EvidenceDriver()

    async def capable(unused):
        return True

    monkeypatch.setattr("app.pc_tools_turn.AgentPlanExecutor", Executor)
    value = _payload()
    for key in ("agent_plan", "tool_arguments", "declared_plan"):
        value.pop(key, None)
    value["pc_tools"] = {"device_id": DEVICE, "allowed_scopes": ["browser"]}
    model = Native(name, args)
    service = _service(pc_tools_capability=capable,
        pc_streaming_runtime_factory=lambda app: StreamingExecutionRuntime(app_id=app, b14_stream_client=model))
    service._pc_query_step_driver_factory = driver
    built = service._orchestrate_request_from_payload(value)
    assert not isinstance(built, ServiceResponse)
    result = asyncio.run(PcToolsTurnRuntime(service, value, None).run(built[2]))
    assert result.answer == "Example Domain"
    assert captured[-1]["step_driver"].context == tuple(CONTEXT)
    assert dict(captured[-1]["tool_arguments"]) == {"browser": {"device_id": DEVICE}}
    assert initial == [{"action": "tool", "tool_id": "claw.pc." + name, "arguments": args}]
    assert len(model.requests) == 1


def test_browser_is_never_enabled_without_an_explicit_admitted_ceiling():
    driver = StructuredPCQueryStepDriver(select_step=lambda *a: None)
    with pytest.raises(PCQueryStepError):
        driver._decision({"action": "tool", "tool_id": "claw.pc.browser_open",
                          "arguments": {"url": "https://example.com/"}}, [])


@pytest.mark.parametrize("args", [
    {"url": "https://example.com/", "device_id": DEVICE},
    {"url": "https://example.com/", "confirmation": True},
    {"url": "https://example.com/", "page_url": "https://other.example/"},
])
def test_structured_browser_does_not_accept_private_target_or_confirmation(args):
    driver = StructuredPCQueryStepDriver(select_step=lambda *a: None, allowed_tool_ids=BROWSER_TOOL_IDS)
    with pytest.raises(PCQueryStepError):
        driver._decision({"action": "tool", "tool_id": "claw.pc.browser_open", "arguments": args}, [])
