"""#7447/#7654 후속 — MCP pc_search recursive·pc_list depth 인자 확장.

외부 커넥터의 두 읽기 도구가 선택 인자를 얻는다. 두 도구 모두 읽기 전용이며
기존 등록 폴더·권한 검사를 그대로 지난다.

- pc_search recursive(불리언, 기본 false): false·미제공은 기존 immediate-folder
  검색과 완전히 같다. true는 Engine의 재귀 이름 검색 도구(claw.pc.search_files,
  훑기 2,000·결과 50 상한, 상대 경로, 링크 미순회)로 단계가 바뀐다.
- pc_list depth(정수 1..3, 기본 1): 1·미제공은 기존 한 페이지와 같다. 2·3은
  그 깊이까지의 항목을 한 번에 돌려주되 200행에서 잘리고(truncated), 각 행에
  상대 경로와 깊이가 담긴다. 깊이 2 이상에서 offset 이어 보기는 없다.

수정 전에는 이 인자들이 닫힌 실행표·게이트웨이 어휘 어디에도 없었으므로,
아래 단계 시험들은 수정 전에 모두 실패한다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app import mcp_gateway_execution as execution
from app.chat_pc_drive import chat_pc_plan_for_tool
from app.claw_pc_search_command import (
    PC_SEARCH_MAX_LIMIT,
    PC_SEARCH_SCAN_MAX_FILES,
    pc_search_command,
)
from app.mcp_gateway_transport import _TOOLS as MCP_TOOLS
from app.oracle_mesh_read_return_routes import _pc_files_command
from test_7601_mcp_read_tools import (
    PRINCIPAL, gateway_of, harness, plan_of,
)


# ── 1. 선언: 선택 인자, 기본값, 상한 ──────────────────────────────────────


def test_pc_search_gained_one_optional_boolean():
    schema = MCP_TOOLS["pc_search"]["inputSchema"]["properties"]
    assert {"path", "query", "recursive", "device"} == set(schema)
    recursive = schema["recursive"]
    assert recursive["type"] == "boolean"
    assert recursive["default"] is False
    # 필수 인자는 늘지 않았다.
    assert MCP_TOOLS["pc_search"]["inputSchema"]["required"] == ["path", "query"]


def test_pc_list_gained_one_optional_depth_integer():
    schema = MCP_TOOLS["pc_list"]["inputSchema"]["properties"]
    assert {"path", "depth", "job_id", "device"} == set(schema)
    depth = schema["depth"]
    assert depth["type"] == "integer"
    assert depth["minimum"] == 1 and depth["maximum"] == 3
    assert depth["default"] == 1
    assert MCP_TOOLS["pc_list"]["inputSchema"]["required"] == []


def test_the_descriptions_state_the_caps_and_the_link_rule():
    search = MCP_TOOLS["pc_search"]["description"]
    assert "recursive" in search and "2,000" in search and "50건" in search
    assert "바로가기" in search and "따라 들어가지 않습니다" in search
    listing = MCP_TOOLS["pc_list"]["description"]
    assert "depth" in listing and "200행" in listing
    assert "바로가기" in listing and "따라 들어가지 않습니다" in listing
    assert "offset 이어 보기를 지원하지 않습니다" in listing


# ── 2. pc_search recursive: 단계 선택과 게이트웨이 적재 ────────────────────


def test_pc_search_without_recursive_stages_the_same_call_as_before(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_search", {"path": "docs", "query": "예산"}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.list_files"
    assert plan_of(transport) == ["claw.pc.list_files"]
    assert gateway["arguments"] == {"path": "docs"}
    assert gateway["search_query"] == "예산"
    assert "recursive" not in gateway["arguments"]


def test_pc_search_recursive_false_stages_the_same_call_as_before(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_search",
        {"path": "docs", "query": "예산", "recursive": False}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.list_files"
    assert plan_of(transport) == ["claw.pc.list_files"]
    assert gateway["arguments"] == {"path": "docs"}
    assert "recursive" not in gateway["arguments"]


def test_pc_search_recursive_true_stages_the_recursive_search_tool(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_search",
        {"path": "docs", "query": "예산", "recursive": True}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.search_files"
    assert plan_of(transport) == ["claw.pc.search_files"]
    # 검색어는 여전히 검색어 자리로만 간다. recursive는 인자로 전달되지 않는다.
    assert gateway["arguments"] == {"path": "docs"}
    assert gateway["search_query"] == "예산"


def test_the_recursive_plan_names_one_read_only_step():
    plan = chat_pc_plan_for_tool("files_search")
    assert [(s["step_id"], s["tool_id"]) for s in plan["steps"]] == [
        ("search_files", "claw.pc.search_files"),
    ]


def test_recursive_true_requires_the_query(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_search", {"path": "docs", "recursive": True}))
    assert transport.calls == []


@pytest.mark.parametrize("bad", ["true", "false", 1, 0, None])
def test_a_recursive_value_that_is_not_a_boolean_is_refused(monkeypatch, bad):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_search",
            {"path": "docs", "query": "예산", "recursive": bad}))
    assert transport.calls == []


def test_recursive_is_refused_on_the_other_tool(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_list",
            {"path": "docs", "recursive": True}))
    assert transport.calls == []


# ── 3. pc_list depth: 단계 선택과 게이트웨이 적재 ──────────────────────────


def test_pc_list_without_depth_stages_the_same_call_as_before(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_list", {"path": "docs"}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.list_files"
    assert plan_of(transport) == ["claw.pc.list_files"]
    assert gateway["arguments"] == {"path": "docs"}


def test_pc_list_depth_one_stages_the_same_call_as_before(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_list", {"path": "docs", "depth": 1}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["arguments"] == {"path": "docs", "depth": 1}


def test_pc_list_depth_two_travels_to_the_engine(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_list", {"path": "docs", "depth": 2}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.list_files"
    assert plan_of(transport) == ["claw.pc.list_files"]
    assert gateway["arguments"] == {"path": "docs", "depth": 2}


def test_pc_list_depth_three_travels_to_the_engine(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_list", {"path": "docs", "depth": 3}))
    assert result["status"] == "completed"
    assert gateway_of(transport)["arguments"] == {"path": "docs", "depth": 3}


@pytest.mark.parametrize("bad", ["2", 0, 4, -1, True, False, 1.5])
def test_a_depth_value_outside_the_integer_range_is_refused(monkeypatch, bad):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_list", {"path": "docs", "depth": bad}))
    assert transport.calls == []


def test_depth_is_refused_on_the_other_tool(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_search", {"path": "docs", "depth": 2}))
    assert transport.calls == []


# ── 4. 등록 폴더 밖·상위 탈출은 기존 코드로 거절 ──────────────────────────


@pytest.mark.parametrize("path", ["..", "../..", r"..\..\windows", "docs/../../etc"])
def test_the_search_paths_that_leave_the_folder_are_still_refused(path):
    from app.claw_pc_search_command import pc_search_path
    assert pc_search_path(path) is None


def test_an_absolute_path_outside_the_registered_folders_is_refused(monkeypatch):
    # 같은 등록 폴더 경계 검사가 두 도구를 모두 막는다 — 새 검사를 만들지 않았다.
    request, transport, _, _ = harness(monkeypatch)
    for name, args in (
        ("pc_search", {"path": r"C:\windows", "query": "x", "recursive": True}),
        ("pc_list", {"path": r"C:\windows", "depth": 2}),
    ):
        result = asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, name, args))
        assert result["status"] == "failed", name
        assert result["code"] == "pc_path_outside_registered_roots", name
    assert transport.calls == []


# ── 5. 게이트웨이 어휘: 양쪽 표가 같은 키를 안다 ──────────────────────────


def test_the_core_and_client_tables_admit_the_same_widened_keys():
    from padiem_ai_core.pc_gateway import PC_GATEWAY_TOOLS as core_table
    from padiem_ai_engine_client.client import _PC_GATEWAY_TOOLS as engine_table

    for table in (core_table, engine_table):
        assert {"path", "depth"} <= table["claw.pc.list_files"]
        assert "claw.pc.search_files" in table


# ── 6. PC 명령: 깊이 걷기와 재귀 이름 검색 ─────────────────────────────────


def test_the_depth_one_command_is_unchanged_by_the_widen():
    plain = _pc_files_command(op="list", root=r"E:\work", relative="")
    paged = _pc_files_command(op="list", root=r"E:\work", relative="",
                              offset=50, filter_term="report")
    # 기존 한 페이지 명령은 걷기 마커를 하나도 갖지 않는다.
    for script in (plain, paged):
        assert "Add-DepthRow" not in script
        assert "Add-Match" not in script
        assert "$skip=" not in script
    assert "Get-ChildItem -LiteralPath" in plain
    assert "-Skip 50 -First 50" in paged


def test_the_depth_two_command_walks_two_levels_with_one_bounded_answer():
    script = _pc_files_command(op="list", root=r"E:\work", relative="docs", depth=2)
    assert "$maxDepth=2" in script
    assert "$cap=200" in script
    assert "$skip=2 -bor 4 -bor 1024" in script
    assert "relative_path=" in script
    assert "depth=$level" in script
    assert "Sort-Object -Property relative_path" in script
    # 깊이 걷기는 한 번의 응답이므로 offset 페이지가 없다.
    assert "-Skip" not in script
    # 요청 경로의 바로가기 검사는 depth 걷기에서도 맨 앞에 유지된다.
    assert script.startswith("$guardRoot = ")


def test_the_recursive_command_uses_the_existing_search_constants():
    script = _pc_files_command(op="list", root=r"E:\work", relative="docs",
                               recursive=True, filter_term="예산")
    assert f"$cap={PC_SEARCH_MAX_LIMIT}" in script
    assert f"$scan={PC_SEARCH_SCAN_MAX_FILES}" in script
    assert "$skip=2 -bor 4 -bor 1024" in script
    assert "relative_path=" in script
    assert "has_more=$flags.truncated" in script
    assert "scan_truncated=$flags.scan" in script
    # 검색어는 와일드카드 이스케이프 뒤 -like로만 쓰인다.
    assert "-Filter" not in script and "-like" in script


def test_a_recursive_walk_still_refuses_the_scoped_guard_first():
    script = _pc_files_command(op="list", root=r"E:\work", relative=r"docs\..\..",
                               recursive=True, filter_term="x")
    # 상위 탈출 조각이 들어간 요청도 명령 문자열을 만들지 않고 거부된다.
    assert "guardHit" in script


# ── 7. 검색어는 따옴표 안 글자로만 취급된다 ────────────────────────────────


@pytest.mark.parametrize("query", [
    '"; Remove-Item -Recurse -Force E:\\work; "',
    "' ; Start-Process calc ; '",
    "$(Get-ChildItem C:\\)",
    "`n$env:PATH",
])
def test_a_hostile_search_term_stays_a_quoted_literal(monkeypatch, query):
    request, transport, _, _ = harness(monkeypatch)
    asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_search",
        {"path": "docs", "query": query, "recursive": True}))
    gateway = gateway_of(transport)
    assert gateway["search_query"] == query
    assert gateway["tool_id"] == "claw.pc.search_files"
    script = pc_search_command(
        roots=[{"label": "work", "path": r"E:\work"}], query=query, mode="name")
    # 공통 따옴표 함수가 모든 작은따옴표를 두 배로 만든다: 검색어는 글자로만 매칭된다.
    assert "'" + query.replace("'", "''") in script
    assert "Remove-Item -Recurse -Force E:\\work; " + "'" not in script.replace("'" + query.replace("'", "''"), "")
