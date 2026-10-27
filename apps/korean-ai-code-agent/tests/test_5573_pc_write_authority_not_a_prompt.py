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

from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect

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
