"""PC delegation never grants external SEND/record authority in real Core."""
from __future__ import annotations

import asyncio

import pytest

from kagent.connector_projection import PROJECTED_CATALOGUE_ENTRIES, project_reviewed_entries
from kagent.pc_query_adapter import (
    pc_delete_file_tool_spec, pc_move_file_tool_spec, pc_write_file_tool_spec,
)
from padiem_ai_core.contracts import AgentProfile, ApprovalPolicy
from padiem_ai_core.tool_runtime import (
    ToolAuthorizationContext, ToolInvocation, ToolRuntime, ToolRuntimeError,
)


def _profile(tool_id):
    return AgentProfile(id="delegation-test", title="Delegation boundary",
                        description="Local test handler", system_instruction="Use allowed tools.",
                        task_type="general", optimize_for="balanced", max_tokens=500,
                        allowed_tools=(tool_id,))


@pytest.mark.parametrize("connector,tool_name", [
    ("gmail", "send_existing_approved_draft"),
    ("gmail", "create_draft"),
    *[(entry.connector_id, entry.write_tools[0]) for entry in PROJECTED_CATALOGUE_ENTRIES
      if entry.connector_id != "gmail" and entry.write_tools],
])
def test_external_send_or_record_requires_confirmation_despite_external_grant(connector, tool_name):
    tool = project_reviewed_entries().tool_registry.get(
        f"tool:b54:{connector}_{tool_name}@1").runtime_spec
    calls = []

    async def handler(arguments):
        calls.append(arguments)
        return {"ok": True}

    runtime = ToolRuntime()
    runtime.register(tool, handler)
    profile = _profile(tool.id)
    # Even an external grant and model-supplied confirmation/delegation fields
    # cannot substitute for the actual user-confirmation authority.
    invocation = ToolInvocation(tool.id, {"confirmed": True, "pc_delegation": {
        "version": 1, "rules": [{"folder": ".", "actions": ["write"], "mode": "allow"}],
    }})
    authorization = ToolAuthorizationContext(
        app_id="b54", agent_id=profile.id, externally_authorized_tools=(tool.id,))
    with pytest.raises(ToolRuntimeError) as error:
        asyncio.run(runtime.execute(invocation, profile, authorization))
    assert error.value.code == "tool_user_confirmation_required"
    assert calls == []
    if connector == "gmail" and tool_name == "send_existing_approved_draft":
        confirmed = ToolAuthorizationContext(
            app_id="b54", agent_id=profile.id, user_confirmed_tools=(tool.id,))
        result = asyncio.run(runtime.execute(invocation, profile, confirmed))
        assert result.output_copy() == {"ok": True}
        assert calls == [invocation.arguments_copy()]


@pytest.mark.parametrize("factory,arguments", [
    (pc_write_file_tool_spec, {"path": "notes/a.txt", "content": "local test"}),
    (pc_move_file_tool_spec, {"path": "notes/a.txt", "destination": "notes/b.txt"}),
    (pc_delete_file_tool_spec, {"path": "notes/a.txt"}),
])
def test_admitted_local_pc_actions_have_no_second_confirmation_button(factory, arguments):
    tool = factory()
    assert tool.approval_policy is ApprovalPolicy.EXTERNAL_AUTHORIZATION
    calls = []

    async def handler(values):
        calls.append(values)
        return {"ok": True}

    runtime = ToolRuntime()
    runtime.register(tool, handler)
    profile = _profile(tool.id)
    authorization = ToolAuthorizationContext(
        app_id="padiem-chat", agent_id=profile.id, granted_auth_scopes=tool.auth_scope,
        externally_authorized_tools=(tool.id,), user_confirmed_tools=(),
    )
    result = asyncio.run(runtime.execute(ToolInvocation(tool.id, arguments), profile, authorization))
    assert result.output_copy() == {"ok": True}
    assert calls == [arguments]


def test_external_read_needs_no_user_confirmation():
    tool = project_reviewed_entries().tool_registry.get("tool:b54:gmail_search_messages@1").runtime_spec
    assert tool.approval_policy is ApprovalPolicy.NOT_REQUIRED
    runtime = ToolRuntime()

    async def handler(arguments):
        return {"messages": []}

    runtime.register(tool, handler)
    profile = _profile(tool.id)
    authorization = ToolAuthorizationContext(app_id="b54", agent_id=profile.id)
    result = asyncio.run(runtime.execute(ToolInvocation(tool.id, {"query": "test"}), profile, authorization))
    assert result.output_copy() == {"messages": []}
