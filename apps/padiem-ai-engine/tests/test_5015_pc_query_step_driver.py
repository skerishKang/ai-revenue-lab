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
    PC_QUERY_SCOPE,
    StructuredPCQueryStepDriver,
    PCQueryStepError,
    build_chat_pc_query_tool_binding,
    build_claw_pc_query_tool_binding,
)
from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.tool_runtime import ToolInvocation
from padiem_ai_core.tool_runtime import ToolExecutionResult
from padiem_ai_core.contracts import ToolEvent, RunStatus


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


def test_drive_binding_registers_core_toolruntime_contract():
    binding = build_claw_pc_query_tool_binding(
        service=object(), request_factory=lambda *args, **kwargs: None, secret="s" * 32,
    )
    assert binding.registry.canonical_tool_ids == ("tool:padiem:claw-pc-query-drives@1",)
    assert binding.tool_runtime.registered_tool_ids == (PC_DRIVES_TOOL_ID,)


def test_chat_binding_shares_contract_under_chat_product_only():
    claw = build_claw_pc_query_tool_binding(
        service=object(), request_factory=lambda *args, **kwargs: None, secret="s" * 32,
    )
    chat = build_chat_pc_query_tool_binding(
        service=object(), request_factory=lambda *args, **kwargs: None, secret="s" * 32,
    )
    # Same shared tool contract: identical canonical/runtime ids and scope.
    assert chat.registry.canonical_tool_ids == claw.registry.canonical_tool_ids == (
        PC_DRIVES_CANONICAL_TOOL_ID,)
    assert chat.tool_runtime.registered_tool_ids == claw.tool_runtime.registered_tool_ids == (
        PC_DRIVES_TOOL_ID,)
    # Distinct product authority: Chat binding never carries the Claw app or
    # agent identity, and Claw never carries the Chat one.
    assert chat.app_id == CHAT_APP_ID == "padiem-chat"
    assert claw.app_id == CLAW_APP_ID
    assert set(chat.authorities) == {CHAT_PC_QUERY_AGENT_ID}
    assert set(claw.authorities) != {CHAT_PC_QUERY_AGENT_ID}
    chat_auth = chat.authorities[CHAT_PC_QUERY_AGENT_ID].authorization
    assert chat_auth.app_id == CHAT_APP_ID
    assert chat_auth.granted_auth_scopes == (PC_QUERY_SCOPE,)
    assert CLAW_ENGINE_PC_DRIVE_URL != CHAT_ENGINE_PC_DRIVE_URL
    assert CHAT_ENGINE_PC_DRIVE_URL.endswith("/internal/chat/engine-pc-drive")
