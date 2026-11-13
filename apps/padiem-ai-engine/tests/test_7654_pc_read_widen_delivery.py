"""#7654 후속 — Engine driver: listing depth와 gateway action의 검색 전달.

- pc_list의 depth(2..3)는 드라이버 인자 검사를 통과해 dispatch payload로
  흐르고, 결과 행의 relative_path·depth·truncated를 호출자에게 전달한다.
- 게이트웨이 액션은 검색 텍스트를 도구 인자로 접어 search handler에 전달하고
  (#7654의 pc_search_contents가 런타임에 이 fold가 없어 실패했던 것을 함께
  바로잡는다), 검색 projection(entries)을 그대로 호출자에게 relay한다.
"""
from __future__ import annotations

import json

import pytest

from app.claw_pc_query_step_driver import (
    _pc_list_item,
    _validate_pc_step_arguments,
)
from app.pc_gateway_action import PcGatewayAction


def test_the_listing_without_depth_keeps_the_default_payload():
    path, extra = _validate_pc_step_arguments("list", {"path": "docs"})
    assert path == "docs"
    assert extra == {}


def test_the_listing_depth_flows_into_the_dispatch_payload():
    path, extra = _validate_pc_step_arguments("list", {"path": "docs", "depth": 2})
    assert path == "docs"
    assert extra == {"depth": 2}


@pytest.mark.parametrize("depth", ["2", 0, 4, -1, True])
def test_a_depth_that_is_not_an_in_range_integer_is_refused(depth):
    with pytest.raises(Exception) as refused:
        _validate_pc_step_arguments("list", {"path": "docs", "depth": depth})
    assert "depth" in str(refused.value.code) or refused.value.code == "pc_list_depth_invalid"


def test_a_deep_listing_row_keeps_its_relative_path_and_depth():
    row = _pc_list_item({
        "Name": "target.txt", "Length": 12,
        "Modified": "2026-11-13T00:00:00.000Z", "PSIsContainer": False,
        "relative_path": "sub\\deep\\target.txt", "depth": 2,
    })
    assert row["path"] == "sub\\deep\\target.txt"
    assert row["depth"] == 2


def test_a_plain_listing_row_still_has_no_depth_field():
    row = _pc_list_item({
        "Name": "notes.txt", "Length": 3,
        "Modified": "2026-11-13T00:00:00.000Z", "PSIsContainer": False,
    })
    assert "depth" not in row


def test_the_gateway_action_folds_the_search_text_into_the_tool_arguments():
    # #7654의 pc_search_contents는 이 fold가 없어 런타임에 검색어가 핸들러에
    # 도달하지 못했다. 검색 도구의 첫 호출은 검색어를 인자로 접어 전달하고,
    # immediate listing(claw.pc.list_files)은 인자를 그대로 유지해 관측 후
    # 게이트웨이에서 필터링된다.
    action = PcGatewayAction({
        "version": 1, "source": "mcp", "token_id": "tok", "request_id": "req_mcp_1",
        "tool_id": "claw.pc.search_contents", "arguments": {"path": "docs"},
        "search_query": "예산",
    })
    decision = action.decision(observations=())
    assert decision["action"] == "tool"
    assert decision["tool_id"] == "claw.pc.search_contents"
    assert decision["arguments"] == {"path": "docs", "query": "예산"}
    listing_action = PcGatewayAction({
        "version": 1, "source": "mcp", "token_id": "tok", "request_id": "req_mcp_3",
        "tool_id": "claw.pc.list_files", "arguments": {"path": "docs"},
        "search_query": "예산",
    })
    listing_decision = listing_action.decision(observations=())
    # immediate 검색은 목록 관측 뒤 필터링되므로 핸들러 인자에 검색어가 흐르지 않는다.
    assert listing_decision["arguments"] == {"path": "docs"}


def test_the_recursive_search_projection_is_relayed_with_its_relative_paths():
    # The search handler's observation wraps the projection as a JSON string
    # beside the dispatch evidence (dispatch_id, execution_confirmed, ...).
    action = PcGatewayAction({
        "version": 1, "source": "mcp", "token_id": "tok", "request_id": "req_mcp_2",
        "tool_id": "claw.pc.search_files", "arguments": {"path": "docs"},
        "search_query": "예산",
    })
    action.selected = True
    projection = {
        "ok": True, "query": "예산", "mode": "name", "engine": "list",
        "office": "none", "count": 1, "truncated": False, "scan_truncated": False,
        "has_more": False,
        "entries": [{"path": "reports\\2026\\예산본.txt", "size_bytes": 12,
                     "modified_utc": "2026-11-13T00:00:00.000Z",
                     "content_state": "name_only", "line": None, "snippet": "",
                     "reason": ""}],
    }
    observation_output = {
        "dispatch_id": "dsp_" + "e" * 32,
        "output": json.dumps(projection, ensure_ascii=False, separators=(",", ":")),
        "count": projection["count"], "truncated": False, "scan_truncated": False,
        "engine": "list", "result_sha256": "f" * 64, "execution_confirmed": True,
        "termination": "no_exit_code", "exit_code": None,
    }
    decision = action.decision(observations=[{"tool_id": "claw.pc.search_files",
                                              "output": observation_output}])
    assert decision["action"] == "complete"
    relayed = json_of(decision["answer"])
    assert relayed["status"] == "completed"
    assert relayed["output"]["entries"][0]["path"] == "reports\\2026\\예산본.txt"
    assert relayed["output"]["has_more"] is False
    assert relayed["output"]["search_scope"] == "recursive_folder"


def json_of(answer: str) -> dict:
    import json
    return json.loads(answer)


def test_the_gateway_search_text_reaches_the_search_handler(monkeypatch):
    """The whole way: gateway envelope → action → real search handler → dispatch.

    The handler receives only the tool arguments, so the text has to be folded
    into them before the handler's own validation runs. On main this call never
    reaches the dispatch: the handler refuses the missing query first.
    """
    import asyncio

    from app import claw_pc_query_step_driver as driver

    action = PcGatewayAction({
        "version": 1, "source": "mcp", "token_id": "tok", "request_id": "req_mcp_4",
        "tool_id": "claw.pc.search_contents", "arguments": {"path": "docs"},
        "search_query": "예산",
    })
    decision = action.decision(observations=())
    assert decision["action"] == "tool"

    calls = []

    async def fake_signed_call(*, service, request_factory, secret, owner, payload, mode):
        calls.append((mode, payload))
        raise RuntimeError("stop once the dispatch payload is known")

    monkeypatch.setattr(driver, "_signed_files_call", fake_signed_call)
    handler = driver._make_pc_search_handler(
        tool_id="claw.pc.search_contents", search_mode="content",
        service=None, request_factory=None, secret=None)
    token = driver._PC_QUERY_OWNER.set(("usr_owner", "run_1", "subj_1", None))
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(handler(decision["arguments"]))
    finally:
        driver._PC_QUERY_OWNER.reset(token)

    assert [mode for mode, _ in calls] == ["dispatch"]
    mode, payload = calls[0]
    assert payload["op"] == "search"
    assert payload["query"] == "예산"
    assert payload["search_mode"] == "content"
    assert payload["path"] == "docs"
