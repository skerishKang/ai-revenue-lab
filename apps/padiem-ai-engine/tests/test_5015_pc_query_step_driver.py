import asyncio
from types import SimpleNamespace

import pytest

from app.claw_pc_query_step_driver import (
    CHAT_APP_ID,
    CHAT_ENGINE_PC_DRIVE_URL,
    CHAT_PC_QUERY_AGENT_ID,
    CLAW_APP_ID,
    CLAW_ENGINE_PC_DRIVE_URL,
    PC_DRIVES_CANONICAL_TOOL_ID,
    PC_DRIVES_TOOL_ID,
    PC_LIST_FILES_CANONICAL_TOOL_ID,
    PC_LIST_FILES_SCOPE,
    PC_LIST_FILES_TOOL_ID,
    PC_QUERY_SCOPE,
    PC_READ_FILE_CANONICAL_TOOL_ID,
    PC_READ_FILE_SCOPE,
    PC_READ_FILE_TOOL_ID,
    StructuredPCQueryStepDriver,
    PCQueryStepError,
    build_chat_pc_query_tool_binding,
    build_claw_pc_query_tool_binding,
)
from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.tool_runtime import ToolInvocation
from padiem_ai_core.tool_runtime import ToolExecutionResult
from padiem_ai_core.contracts import ToolEvent, RunStatus


def test_stream_owner_binding_is_exact_and_narrow():
    """#5015: only the canonical PC-query plan may carry a stream owner."""
    from types import SimpleNamespace

    from app.orchestration_service import _pc_query_stream_owner

    plan = SimpleNamespace(agent_id="agent:padiem:claw-pc-query@1")
    request = SimpleNamespace(
        agent_plan=plan,
        subject_id="sub_" + "a" * 32,
        execution_request=SimpleNamespace(session_id="run_5015"),
        tool_arguments=None,
    )
    assert _pc_query_stream_owner("b54-padiem-claw", request) == (
        "sub_" + "a" * 32, "run_5015", "b54-padiem-claw", None,
    )

    # A different plan, product, or missing identity never receives an owner.
    for app_id, override in (
        ("b54-padiem-claw", {"agent_plan": SimpleNamespace(agent_id="agent:padiem:claw-desktop@1")}),
        ("other-app", {}),
        ("b54-padiem-claw", {"subject_id": None}),
        ("b54-padiem-claw", {"execution_request": SimpleNamespace(session_id=None)}),
    ):
        candidate = SimpleNamespace(**{**vars(request), **override})
        assert _pc_query_stream_owner(app_id, candidate) is None


def test_model_selects_drive_tool_as_first_step_then_sees_result():
    seen = []

    async def select_step(*, context, compiled_profile, observations):
        seen.append(observations)
        if not observations:
            return {"action": "tool", "tool_id": PC_DRIVES_TOOL_ID, "arguments": {}}
        return {"action": "complete", "answer": "실행 계정에서 C: 드라이브를 확인했습니다."}

    driver = StructuredPCQueryStepDriver(select_step=select_step)
    context = AgentStepContext(run_id="run_5015", step_index=1, input_text="내 PC 드라이브 목록을 알려줘", tool_results=())
    decision = asyncio.run(driver.next_step(context, object()))
    assert decision.invocation == ToolInvocation(tool_id=PC_DRIVES_TOOL_ID, arguments={})
    result = ToolExecutionResult(tool_id=PC_DRIVES_TOOL_ID,
        output={"output": "drive inventory observed", "exit_code": None},
        event=ToolEvent(tool_id=PC_DRIVES_TOOL_ID, status=RunStatus.COMPLETED))
    context2 = AgentStepContext(run_id="run_5015", step_index=2, input_text="내 PC 드라이브 목록을 알려줘", tool_results=(result,))
    final = asyncio.run(driver.next_step(context2, object()))
    assert final.answer == "실행 계정에서 C: 드라이브를 확인했습니다."
    assert seen[1][0]["output"]["output"] == "drive inventory observed"


def test_model_cannot_select_unauthorized_tool():
    async def select_step(**kwargs):
        return {"action": "tool", "tool_id": "claw.desktop.click", "arguments": {}}

    driver = StructuredPCQueryStepDriver(select_step=select_step)
    context = AgentStepContext(run_id="run_5015", step_index=1, input_text="list drives", tool_results=())
    with pytest.raises(PCQueryStepError):
        asyncio.run(driver.next_step(context, object()))


def test_file_tool_signed_body_matches_the_closed_server_key_sets():
    import json

    from app.claw_pc_query_step_driver import _signed_files_call

    captured: list[dict] = []

    class _Request:
        def __init__(self, url, *, method, headers, body):
            self.url = url
            self.method = method
            self.headers = headers
            self.body = body
            self.js_object = self

    class _Response:
        status = 200

        async def text(self):
            return '{"ok":true}'

    class _Service:
        async def fetch(self, request):
            captured.append(json.loads(request.body))
            return _Response()

    owner = ("sub_" + "a" * 32, "run_1", "b54-padiem-claw", "device-1")
    secret = "s" * 32
    asyncio.run(_signed_files_call(
        service=_Service(), request_factory=_Request, secret=secret,
        owner=owner, mode="command_status", payload={"dispatch_id": "dsp_1"},
    ))
    assert set(captured[0]) == {
        "subject_id", "run_id", "dispatch_id", "mode",
    }
    asyncio.run(_signed_files_call(
        service=_Service(), request_factory=_Request, secret=secret,
        owner=owner, mode="dispatch",
        payload={"op": "list", "path": ".", "tool_call_ref": "call-1"},
    ))
    assert set(captured[1]) == {
        "subject_id", "run_id", "device_id", "op", "path",
        "tool_call_ref", "mode",
    }


def test_model_lists_then_reads_the_selected_file_in_one_run():
    """#4976: the listing result is the next step's file-selection input."""
    import json

    seen = []

    async def select_step(*, context, compiled_profile, observations):
        seen.append(observations)
        if not observations:
            return {
                "action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID,
                "arguments": {"path": "."},
            }
        if len(observations) == 1:
            listed = json.loads(observations[0]["output"]["output"])
            target = listed["entries"][0]["relative_path"]
            return {
                "action": "tool", "tool_id": PC_READ_FILE_TOOL_ID,
                "arguments": {"path": target},
            }
        return {
            "action": "complete",
            "answer": "읽은 내용: " + observations[-1]["output"]["content"],
        }

    driver = StructuredPCQueryStepDriver(select_step=select_step)
    first = asyncio.run(driver.next_step(
        AgentStepContext(run_id="run_5015", step_index=1,
                         input_text="폴더 목록을 보고 TXT를 읽어줘", tool_results=()),
        object(),
    ))
    assert first.invocation == ToolInvocation(
        tool_id=PC_LIST_FILES_TOOL_ID, arguments={"path": "."},
    )

    listing = json.dumps({
        "ok": True,
        "entries": [{"relative_path": "notes.txt", "PSIsContainer": False}],
    })
    list_result = ToolExecutionResult(
        tool_id=PC_LIST_FILES_TOOL_ID,
        output={"output": listing, "entry_count": 1},
        event=ToolEvent(tool_id=PC_LIST_FILES_TOOL_ID, status=RunStatus.COMPLETED),
    )
    second = asyncio.run(driver.next_step(
        AgentStepContext(run_id="run_5015", step_index=2,
                         input_text="폴더 목록을 보고 TXT를 읽어줘",
                         tool_results=(list_result,)),
        object(),
    ))
    assert second.invocation == ToolInvocation(
        tool_id=PC_READ_FILE_TOOL_ID, arguments={"path": "notes.txt"},
    )

    read_result = ToolExecutionResult(
        tool_id=PC_READ_FILE_TOOL_ID,
        output={"content": "PADIEM TEST CONTENT", "content_bytes": 19},
        event=ToolEvent(tool_id=PC_READ_FILE_TOOL_ID, status=RunStatus.COMPLETED),
    )
    final = asyncio.run(driver.next_step(
        AgentStepContext(run_id="run_5015", step_index=3,
                         input_text="폴더 목록을 보고 TXT를 읽어줘",
                         tool_results=(list_result, read_result)),
        object(),
    ))
    assert final.answer == "읽은 내용: PADIEM TEST CONTENT"
    assert len(seen) == 3


def test_file_tool_arguments_are_closed():
    async def select_step(**kwargs):
        return {
            "action": "tool", "tool_id": PC_READ_FILE_TOOL_ID,
            "arguments": {"path": "notes.txt", "command": "whoami"},
        }

    driver = StructuredPCQueryStepDriver(select_step=select_step)
    context = AgentStepContext(
        run_id="run_5015", step_index=1, input_text="read", tool_results=(),
    )
    with pytest.raises(PCQueryStepError):
        asyncio.run(driver.next_step(context, object()))


def test_drive_binding_registers_core_toolruntime_contract():
    binding = build_claw_pc_query_tool_binding(
        service=object(), request_factory=lambda *args, **kwargs: None, secret="s" * 32,
    )
    assert set(binding.registry.canonical_tool_ids) == {
        PC_DRIVES_CANONICAL_TOOL_ID,
        PC_LIST_FILES_CANONICAL_TOOL_ID,
        PC_READ_FILE_CANONICAL_TOOL_ID,
    }
    assert set(binding.tool_runtime.registered_tool_ids) == {
        PC_DRIVES_TOOL_ID, PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID,
    }


def test_chat_binding_shares_contract_under_chat_product_only():
    claw = build_claw_pc_query_tool_binding(
        service=object(), request_factory=lambda *args, **kwargs: None, secret="s" * 32,
    )
    chat = build_chat_pc_query_tool_binding(
        service=object(), request_factory=lambda *args, **kwargs: None, secret="s" * 32,
    )
    # Same shared tool contract: identical canonical/runtime ids and scopes.
    assert set(chat.registry.canonical_tool_ids) == set(claw.registry.canonical_tool_ids) == {
        PC_DRIVES_CANONICAL_TOOL_ID,
        PC_LIST_FILES_CANONICAL_TOOL_ID,
        PC_READ_FILE_CANONICAL_TOOL_ID,
    }
    assert set(chat.tool_runtime.registered_tool_ids) == set(claw.tool_runtime.registered_tool_ids) == {
        PC_DRIVES_TOOL_ID, PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID,
    }
    # Distinct product authority: Chat binding never carries the Claw app or
    # agent identity, and Claw never carries the Chat one.
    assert chat.app_id == CHAT_APP_ID == "padiem-chat"
    assert claw.app_id == CLAW_APP_ID
    assert set(chat.authorities) == {CHAT_PC_QUERY_AGENT_ID}
    assert set(claw.authorities) != {CHAT_PC_QUERY_AGENT_ID}
    chat_auth = chat.authorities[CHAT_PC_QUERY_AGENT_ID].authorization
    assert chat_auth.app_id == CHAT_APP_ID
    assert chat_auth.granted_auth_scopes == (
        PC_QUERY_SCOPE, PC_LIST_FILES_SCOPE, PC_READ_FILE_SCOPE,
    )
    assert CLAW_ENGINE_PC_DRIVE_URL != CHAT_ENGINE_PC_DRIVE_URL
    assert CHAT_ENGINE_PC_DRIVE_URL.endswith("/internal/chat/engine-pc-drive")


def test_streaming_lane_composes_the_pc_query_step_driver(monkeypatch):
    """#5015: the live stream lane must set the PC query step driver.

    Without it the Core plan-backed driver injects a ``query`` argument the
    drive tool schema rejects, so the tool call fails with
    ``invalid_tool_arguments`` before any Mesh dispatch.
    """
    import json
    from unittest.mock import patch

    import app.orchestration_service as service_module
    from app.orchestration_service import (
        ORCHESTRATION_STREAM_PATH,
        OrchestrationEngineService,
    )
    from padiem_ai_core.orchestration_events import (
        OrchestrationEvent,
        OrchestrationEventKind,
    )

    sentinel = object()
    captured = {}

    def factory(model_id, model_policy, task_type, optimize_for, tool_arguments=None):
        captured["model_id"] = model_id
        captured["tool_arguments"] = tool_arguments
        return sentinel

    class FakeRunner:
        def __init__(self, *, runtime, idempotency, event_sink):
            self._sink = event_sink

        async def run(self, request):
            captured["request"] = request
            self._sink(OrchestrationEvent(
                event_id="evt_stream_pc_1",
                run_id=request.execution_request.session_id,
                trace_id=request.context.trace_id,
                app_id=request.app_id,
                kind=OrchestrationEventKind.RUN_STARTED,
                sequence=1,
                timestamp_iso="2026-10-19T00:00:00Z",
            ))

    payload = {
        "app_id": "b54-padiem-claw",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
            "model_policy": {
                "model": "google/gemini-3.5-flash-lite",
                "max_retries": 0,
                "product_tier": "plus",
            },
        },
        "messages": [{"role": "user", "content": "내 PC에 어떤 드라이브가 있어?"}],
        "trace_id": "tr_orch_test",
        "execution_context": {"trace_id": "tr_orch_test", "timeout_seconds": 15.0},
        "subject_id": "sub_" + "a" * 32,
        "session_id": "run_5015_pc_stream",
    }
    payload["agent_plan"] = {
        "agent_id": "agent:padiem:claw-pc-query@1",
        "steps": [{
            "step_id": "query_drives",
            "objective": "Query verified PC filesystem drives",
            "tool_id": "claw.pc.query_drives",
        }],
    }
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: object(),
        b14_service_bound=True,
        pc_query_step_driver_factory=factory,
    )
    with patch.object(service_module, "OrchestrationRunner", FakeRunner):
        prepared = asyncio.run(service.prepare_stream(
            method="POST",
            path=ORCHESTRATION_STREAM_PATH,
            content_type="application/json",
            body=json.dumps(payload).encode("utf-8"),
        ))
    assert prepared.__class__.__name__ == "PreparedOrchestrationStream"
    assert captured["model_id"] == "google/gemini-3.5-flash-lite"
    assert captured["request"].agent_step_driver is sentinel


# ── #5015: the verified target travels with the trusted plan ────────────────


def test_plan_target_is_injected_into_the_selected_tool():
    async def select_step(**kwargs):
        return {"action": "tool", "tool_id": PC_DRIVES_TOOL_ID, "arguments": {}}

    driver = StructuredPCQueryStepDriver(
        select_step=select_step, static_arguments={"device_id": "office-pc"},
    )
    context = AgentStepContext(run_id="run_5015", step_index=1, input_text="list drives", tool_results=())
    decision = asyncio.run(driver.next_step(context, object()))
    assert decision.invocation == ToolInvocation(
        tool_id=PC_DRIVES_TOOL_ID, arguments={"device_id": "office-pc"},
    )


def test_model_cannot_choose_or_change_the_execution_target():
    async def select_step(**kwargs):
        return {
            "action": "tool", "tool_id": PC_DRIVES_TOOL_ID,
            "arguments": {"device_id": "attacker-pc"},
        }

    driver = StructuredPCQueryStepDriver(
        select_step=select_step, static_arguments={"device_id": "office-pc"},
    )
    context = AgentStepContext(run_id="run_5015", step_index=1, input_text="list drives", tool_results=())
    with pytest.raises(PCQueryStepError):
        asyncio.run(driver.next_step(context, object()))


def test_plan_target_rejects_other_arguments():
    from app.claw_pc_query_step_driver import _plan_step_arguments

    assert _plan_step_arguments(
        {"query_drives": {"device_id": "office-pc"}}, "query_drives",
    ) == {"device_id": "office-pc"}
    assert _plan_step_arguments(None, "query_drives") == {}
    with pytest.raises(PCQueryStepError):
        _plan_step_arguments({"query_drives": {"device_id": "pc", "run_id": "x"}}, "query_drives")


def test_signed_dispatch_body_carries_the_same_target():
    import json

    from app.claw_pc_query_step_driver import _signed_chat_call

    class FakeResponse:
        status = 200

        async def text(self):
            return json.dumps({"ok": True, "dispatch": {}})

    class FakeService:
        def __init__(self):
            self.bodies = []

        async def fetch(self, js_object):
            self.bodies.append(js_object["body"])
            return FakeResponse()

    service = FakeService()
    asyncio.run(_signed_chat_call(
        service=service,
        request_factory=lambda url, **kwargs: SimpleNamespace(js_object={"body": kwargs["body"]}),
        secret="s" * 32, subject_id="sub_" + "a" * 32, run_id="run_5015",
        mode="dispatch", device_id="office-pc",
    ))
    body = json.loads(service.bodies[0])
    assert body["device_id"] == "office-pc"
    assert body["subject_id"] == "sub_" + "a" * 32
    assert body["run_id"] == "run_5015"


def test_handler_refuses_a_dispatch_that_resolved_another_device():
    import json

    from app.claw_pc_query_step_driver import (
        _PC_QUERY_OWNER,
        _make_query_drives_handler,
    )
    from padiem_ai_core.tool_runtime import ToolHandlerError

    class FakeResponse:
        status = 200

        async def text(self):
            return json.dumps({"ok": True, "dispatch": {
                "dispatch_id": "dsp_1", "run_id": "run_5015",
                "kind": "command", "device_id": "other-pc",
            }})

    class FakeService:
        async def fetch(self, js_object):
            return FakeResponse()

    handler = _make_query_drives_handler(
        service=FakeService(),
        request_factory=lambda url, **kwargs: SimpleNamespace(js_object={"body": kwargs["body"]}),
        secret="s" * 32, endpoint_url="https://chat.example.test/internal/claw/engine-pc-drive",
    )
    token = _PC_QUERY_OWNER.set(
        ("sub_" + "a" * 32, "run_5015", "b54-padiem-claw", "office-pc")
    )
    try:
        with pytest.raises(ToolHandlerError) as caught:
            asyncio.run(handler({"device_id": "office-pc"}))
    finally:
        _PC_QUERY_OWNER.reset(token)
    assert caught.value.code == "pc_query_target_mismatch"


def test_pc_plan_arguments_are_closed_to_the_device_property():
    from types import SimpleNamespace

    from app.orchestration_service import OrchestrationEngineService

    plan = SimpleNamespace(
        agent_id="agent:padiem:claw-pc-query@1",
        steps=(SimpleNamespace(step_id="query_drives"),),
    )
    validate = OrchestrationEngineService._validate_pc_plan_tool_arguments
    validate(plan, {"query_drives": {"device_id": "office-pc"}})
    validate(plan, {})
    for bad in (
        {"query_drives": {"device_id": "office-pc", "run_id": "x"}},
        {"other_step": {"device_id": "office-pc"}},
        {"query_drives": {"device_id": "bad/path"}},
        {"query_drives": {"device_id": None}},
    ):
        with pytest.raises(Exception) as caught:
            validate(plan, bad)
        assert getattr(caught.value, "code", "") == "invalid_tool_arguments"
    # A non-PC plan keeps the historical argument surface.
    other = SimpleNamespace(agent_id="agent:padiem:other@1", steps=(SimpleNamespace(step_id="s"),))
    validate(other, {"s": {"query": "x"}})


def _selected_pc_test_plan(agent_id, kind):
    from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep

    if kind == "drive":
        steps = (AgentPlanStep(
            step_id="query_drives", objective="Query verified drives",
            tool_id=PC_DRIVES_TOOL_ID,
        ),)
    else:
        steps = (
            AgentPlanStep(
                step_id="list_files", objective="List approved folder",
                tool_id=PC_LIST_FILES_TOOL_ID,
            ),
            AgentPlanStep(
                step_id="read_file", objective="Read selected UTF-8 file",
                tool_id=PC_READ_FILE_TOOL_ID,
            ),
        )
    return AgentPlan(agent_id=agent_id, steps=steps)


@pytest.mark.parametrize("app_id,agent_id,binding_builder", (
    (CLAW_APP_ID, "agent:padiem:claw-pc-query@1", build_claw_pc_query_tool_binding),
    (CHAT_APP_ID, CHAT_PC_QUERY_AGENT_ID, build_chat_pc_query_tool_binding),
))
@pytest.mark.parametrize("kind,target_key", (("drive", "query_drives"), ("files", "files")))
def test_selected_target_survives_engine_tool_attachment_and_owner_binding(
    app_id, agent_id, binding_builder, kind, target_key,
):
    """A selected file loop must not be rejected as an unknown plan step."""
    from app.orchestration_service import (
        OrchestrationEngineService, _pc_query_stream_owner,
    )

    binding = binding_builder(
        service=object(), request_factory=lambda *args, **kwargs: None, secret="s" * 32,
    )
    service = OrchestrationEngineService(
        runtime_factory=lambda app: object(), b14_service_bound=True,
        tool_binding_resolver=lambda app: binding,
    )
    plan = _selected_pc_test_plan(agent_id, kind)
    arguments = {target_key: {"device_id": "office-pc"}}
    attached = service._tool_request_kwargs(
        app_id=app_id, plan=plan, raw_tool_arguments=arguments,
    )
    assert attached["tool_arguments"] == arguments
    assert attached["tool_runtime"] is binding.tool_runtime
    request = SimpleNamespace(
        agent_plan=plan, subject_id="sub_" + "a" * 32,
        execution_request=SimpleNamespace(session_id="run_selected_pc"),
        tool_arguments=attached["tool_arguments"],
    )
    assert _pc_query_stream_owner(app_id, request) == (
        "sub_" + "a" * 32, "run_selected_pc", app_id, "office-pc",
    )
    # The unselected contract remains available.
    assert service._tool_request_kwargs(
        app_id=app_id, plan=plan, raw_tool_arguments=None,
    )["tool_arguments"] == {}


@pytest.mark.parametrize("kind,target_key,wrong_key", (
    ("drive", "query_drives", "files"),
    ("files", "files", "list_files"),
))
def test_selected_pc_hint_validation_stays_closed(kind, target_key, wrong_key):
    from app.orchestration_service import OrchestrationEngineService
    from app.service import ServiceContractError

    plan = _selected_pc_test_plan("agent:padiem:claw-pc-query@1", kind)
    validate = OrchestrationEngineService._validate_pc_plan_tool_arguments
    cases = [
        {target_key: {}},
        {wrong_key: {"device_id": "office-pc"}},
        {target_key: {"device_id": "office-pc", "command": "whoami"}},
        {target_key: {"device_id": "office-pc"}, "other": {"device_id": "office-pc"}},
    ]
    cases.extend(
        {target_key: {"device_id": value}}
        for value in (None, True, "", "bad/path", "bad pc", "pc\nother", "x" * 129)
    )
    for arguments in cases:
        with pytest.raises(ServiceContractError) as caught:
            validate(plan, arguments)
        assert caught.value.code == "invalid_tool_arguments"


def test_files_target_alias_cannot_authorize_a_different_pc_plan():
    from app.orchestration_service import OrchestrationEngineService
    from app.service import ServiceContractError
    from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep

    plan = AgentPlan(
        agent_id="agent:padiem:claw-pc-query@1",
        steps=(AgentPlanStep(
            step_id="other", objective="Different plan",
            tool_id=PC_LIST_FILES_TOOL_ID,
        ),),
    )
    with pytest.raises(ServiceContractError) as caught:
        OrchestrationEngineService._validate_pc_plan_tool_arguments(
            plan, {"files": {"device_id": "office-pc"}},
        )
    assert caught.value.code == "invalid_tool_arguments"


@pytest.mark.parametrize("upstream_code,expected_stage", (
    ("oracle_mesh_file_path_invalid", "pc_files_path_invalid"),
    ("oracle_mesh_file_call_invalid", "pc_files_call_invalid"),
    ("oracle_mesh_device_directory_unavailable", "pc_files_owner_unavailable"),
    ("canonical_session_required", "pc_files_owner_unavailable"),
    ("PRIVATE_DOWNSTREAM_ERROR_FROM_UNTRUSTED_SOURCE", "pc_files_denied"),
))
def test_signed_pc_files_callback_retains_only_reviewed_failure_stage(
    upstream_code, expected_stage, capsys,
):
    """No command replay, error-message disclosure or generic tool_failed."""
    from app.claw_pc_query_step_driver import _signed_files_call
    from padiem_ai_core.tool_runtime import ToolHandlerError

    class DeniedResponse:
        status = 422

        async def text(self):
            return json.dumps({
                "ok": False,
                "error": {
                    "code": upstream_code,
                    "message": "PRIVATE_PATH_AND_CUSTOMER_CONTENT_MUST_NOT_LEAK",
                },
            })

    class DeniedService:
        def __init__(self):
            self.calls = 0

        async def fetch(self, js_object):
            self.calls += 1
            return DeniedResponse()

    service = DeniedService()
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(_signed_files_call(
            service=service,
            request_factory=lambda url, **kwargs: SimpleNamespace(
                js_object={"body": kwargs["body"]},
            ),
            secret="s" * 32,
            owner=("sub_" + "a" * 32, "run_5015", "b54-padiem-claw", "office-pc"),
            mode="dispatch",
            payload={"op": "read", "path": "sample.txt", "tool_call_ref": "run_5015:read:abc"},
        ))
    assert caught.value.code == expected_stage
    assert service.calls == 1
    log = capsys.readouterr().out
    assert "stage=" + expected_stage in log
    assert "PRIVATE_" not in log
    assert "sample.txt" not in log
