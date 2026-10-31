"""#4434: the PC write authority is the pairing grant, never a prompt.

Core refuses a WRITE tool with no approval policy, so the write tools carry
EXTERNAL_AUTHORIZATION. What this pins is the other half of the Owner's decision:
that policy must not become an approval button, a pause, or a wait state in the
conversation when the account already owns the link to that PC.

The mechanism is one set membership in the real ``ToolRuntime``: an
EXTERNAL_AUTHORIZATION tool is refused only while its id is missing from the
authorization's ``externally_authorized_tools``, and it is executed when the id is
there. ``user_confirmed_tools`` - the field the USER_CONFIRMATION branch reads to
pause a run - is therefore never consulted by this lane.
"""
from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.contracts import ApprovalPolicy, RunStatus, ToolSideEffect

from kagent.pc_query_adapter import (
    CHAT_APP_ID,
    CHAT_PC_QUERY_AGENT_ID,
    PC_DELETE_FILE_TOOL_ID,
    PC_MOVE_FILE_TOOL_ID,
    PC_WRITE_FILE_TOOL_ID,
    build_pc_query_product_contract,
    pc_delete_file_tool_spec,
    pc_move_file_tool_spec,
    pc_write_file_tool_spec,
)


def _contract():
    return build_pc_query_product_contract(
        app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID,
    )


WRITE_SPECS = (
    (PC_WRITE_FILE_TOOL_ID, pc_write_file_tool_spec),
    (PC_MOVE_FILE_TOOL_ID, pc_move_file_tool_spec),
    (PC_DELETE_FILE_TOOL_ID, pc_delete_file_tool_spec),
)


def test_write_tools_declare_the_authority_instead_of_a_user_prompt():
    for tool_id, spec_factory in WRITE_SPECS:
        spec = spec_factory()
        assert spec.side_effect is ToolSideEffect.WRITE, tool_id
        assert spec.approval_policy is ApprovalPolicy.EXTERNAL_AUTHORIZATION, tool_id
        assert spec.approval_policy is not ApprovalPolicy.USER_CONFIRMATION, tool_id
        # No time ceiling: #5995 removed the arbitrary cap, and the write lane
        # adds none of its own back.
        assert spec.timeout_seconds is None, tool_id


def test_a_write_step_reaches_the_handler_without_an_approval_pause():
    """The real authority, the real Core runtime, and no wait in between.

    A set comparison cannot show this: what matters is that an executed
    ``claw.pc.write_file`` gets to the handler on the first pass, because the
    pairing link that already binds this account to this PC is the authorization.
    The counter-case is stated next to it on purpose - if the id were not in the
    grant set, Core would answer tool_external_authorization_required and the
    Engine would read that as a pause.
    """
    from padiem_ai_core.tool_runtime import ToolInvocation, ToolRuntime

    contract = _contract()
    executed: list[str] = []

    async def handler(arguments):
        executed.append(arguments["path"])
        return {"ok": True}

    runtime = ToolRuntime()
    runtime.register(pc_write_file_tool_spec(), handler)
    result = asyncio.run(runtime.execute(
        ToolInvocation(tool_id=PC_WRITE_FILE_TOOL_ID,
                       arguments={"path": "문서/견적.txt", "content": "본문"}),
        contract.compiled.runtime_profile,
        contract.authorization,
    ))
    assert executed == ["문서/견적.txt"], "the write step never reached its handler"
    assert getattr(result, "approval_requirement", None) is None
    assert getattr(result, "approval_pause", None) is None

    # The same call without the grant is the pause shape the lane must not hit.
    from dataclasses import replace

    ungranted = replace(contract.authorization, externally_authorized_tools=frozenset())
    runtime2 = ToolRuntime()
    runtime2.register(pc_write_file_tool_spec(), handler)
    with pytest.raises(Exception) as refused:
        asyncio.run(runtime2.execute(
            ToolInvocation(tool_id=PC_WRITE_FILE_TOOL_ID,
                           arguments={"path": "문서/견적.txt", "content": "본문"}),
            contract.compiled.runtime_profile,
            ungranted,
        ))
    error = refused.value
    assert error.code == "tool_external_authorization_required", (
        type(error).__name__, str(error),
    )
    assert error.event.status is RunStatus.POLICY_BLOCKED


def test_no_pc_tool_declares_a_deadline_of_its_own():
    """#5995 lifted the caps; this lane declares none, read or write.

    The read specs still carried the 300 seconds they were written with before
    that decision, which is a ceiling on how long a PC may take to answer.
    """
    specs = [entry.runtime_spec for entry in _contract().registry_entries]
    assert {spec.timeout_seconds for spec in specs} == {None}, [
        (spec.id, spec.timeout_seconds) for spec in specs
    ]


def test_the_paired_link_already_authorizes_every_write_tool():
    contract = build_pc_query_product_contract(
        app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID,
    )
    authorization = contract.authorization
    for tool_id, _ in WRITE_SPECS:
        assert tool_id in authorization.externally_authorized_tools, tool_id
        assert tool_id in {entry.runtime_spec.id for entry in contract.registry_entries}
    # The scopes the runtime compares against are granted for the same product
    # run, so no second confirmation round can be demanded of the customer.
    granted = set(authorization.granted_auth_scopes)
    for tool_id, spec_factory in WRITE_SPECS:
        assert set(spec_factory().auth_scope) <= granted, tool_id


def test_no_pc_write_step_can_ask_for_a_user_confirmation_state():
    contract = build_pc_query_product_contract(
        app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID,
    )
    # The runtime reaches for `user_confirmed_tools` only when a spec declares
    # USER_CONFIRMATION. No tool in this product contract does, so the field is
    # never read on a PC write and no pause state can be produced from it.
    specs = [entry.runtime_spec for entry in contract.registry_entries]
    assert all(spec.approval_policy is not ApprovalPolicy.USER_CONFIRMATION for spec in specs)
    assert not getattr(contract.authorization, "user_confirmed_tools", frozenset()), (
        "the PC lane must not stage any tool as awaiting a user's confirmation"
    )
