"""#3782 step 1 — the PC browser scope is a real ceiling, not a widening.

The browser lane decided its own scope so a "open this site and tell me the
notice title" turn cannot borrow the file tools and a file turn cannot borrow
the browser. These tests pin that decision at the one table both the product
and the Engine read, and pin that `browser_act` stays the only writing tool.
"""
from __future__ import annotations

from kagent.pc_browser_tools import tool_specs
from kagent.pc_query_adapter import (
    PC_BROWSER_ACT_TOOL_ID,
    PC_BROWSER_OPEN_TOOL_ID,
    PC_BROWSER_OPS,
    PC_BROWSER_READ_TOOL_ID,
    PC_BROWSER_SCREENSHOT_TOOL_ID,
    PC_BROWSER_TOOL_IDS,
    PC_FILE_TOOL_IDS,
    PC_REQUEST_SCOPE_TOOLS,
    PC_SEARCH_TOOL_IDS,
    StructuredPCQueryStepDriver,
)


def test_the_browser_scope_offers_exactly_the_four_browser_tools():
    assert PC_REQUEST_SCOPE_TOOLS["browser"] == PC_BROWSER_TOOL_IDS
    assert PC_REQUEST_SCOPE_TOOLS["browser"] == {
        PC_BROWSER_OPEN_TOOL_ID, PC_BROWSER_READ_TOOL_ID,
        PC_BROWSER_SCREENSHOT_TOOL_ID, PC_BROWSER_ACT_TOOL_ID,
    }


def test_the_browser_scope_and_the_file_scopes_never_overlap():
    browser = PC_REQUEST_SCOPE_TOOLS["browser"]
    for name in ("files_list", "files", "files_write", "query_drives"):
        assert not (browser & PC_REQUEST_SCOPE_TOOLS[name]), name
    # A browser turn cannot reach a file, and a file turn cannot reach a page.
    assert not (browser & PC_FILE_TOOL_IDS)
    assert not (browser & PC_SEARCH_TOOL_IDS)


def test_the_adapter_names_the_same_ids_the_browser_lane_defines():
    assert {spec.id for spec in tool_specs()} == PC_BROWSER_TOOL_IDS


def test_only_browser_act_is_a_writing_step():
    specs = {spec.id: spec for spec in tool_specs()}
    for tool_id in (PC_BROWSER_OPEN_TOOL_ID, PC_BROWSER_READ_TOOL_ID,
                    PC_BROWSER_SCREENSHOT_TOOL_ID):
        assert specs[tool_id].side_effect.name == "READ"
        assert specs[tool_id].approval_policy.name == "NOT_REQUIRED"
    # No approval button in the conversation, per the Owner's decision: the
    # act step carries EXTERNAL_AUTHORIZATION (the pairing link), and asks a
    # plain question before login/payment/post/send instead of pausing.
    assert specs[PC_BROWSER_ACT_TOOL_ID].side_effect.name == "WRITE"
    assert specs[PC_BROWSER_ACT_TOOL_ID].approval_policy.name == "EXTERNAL_AUTHORIZATION"


def test_every_browser_tool_has_one_claim_op_and_they_do_not_collide():
    assert set(PC_BROWSER_OPS) == PC_BROWSER_TOOL_IDS
    assert set(PC_BROWSER_OPS.values()) == {
        "browser_open", "browser_read", "browser_screenshot", "browser_act",
    }
    # A browser op never reads like a file op in the signed claim.
    assert not set(PC_BROWSER_OPS.values()) & {"list", "read", "write", "move", "delete"}


def test_a_grant_without_the_browser_scope_admits_no_browser_tool():
    """The ceiling intersects real grants; a file-only grant admits nothing."""

    file_only_scopes = tuple(sorted(PC_REQUEST_SCOPE_TOOLS["files"]))

    class Authorization:
        granted_auth_scopes = file_only_scopes
        externally_authorized_tools = frozenset(file_only_scopes)

    driver = StructuredPCQueryStepDriver(select_step=lambda **_: None)
    driver.configure_request_scope(
        Authorization(), ceiling_tool_ids=PC_REQUEST_SCOPE_TOOLS["browser"],
    )
    assert not (driver._allowed_tool_ids & PC_BROWSER_TOOL_IDS)


def test_a_browser_first_decision_is_admitted_as_the_browser_scope():
    class Authorization:
        granted_auth_scopes = tuple(sorted(PC_BROWSER_TOOL_IDS))
        externally_authorized_tools = frozenset(PC_BROWSER_TOOL_IDS)

    driver = StructuredPCQueryStepDriver(select_step=lambda **_: None)
    driver.configure_request_scope(
        Authorization(), ceiling_tool_ids=PC_BROWSER_TOOL_IDS,
    )
    driver._admit_request_scope(
        {"action": "tool", "tool_id": PC_BROWSER_READ_TOOL_ID, "arguments": {}},
    )
    claim = driver.scope_state["claim"]
    assert claim["requested"] == "browser"
    assert claim["admitted"] == "browser"
    assert set(claim["ops"]) == {"browser_open", "browser_read",
                                 "browser_screenshot", "browser_act"}
