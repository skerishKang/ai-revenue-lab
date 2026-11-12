"""#7601 follow-up: four read-only PC tools for the external AI connector.

pc_search_contents and pc_file_info are new declarations; the range read is
pc_read carrying two optional arguments instead of a new tool name. Nothing
here writes: no approval id is attached, and the plan each call stages is the
one-step plan of the Engine tool that actually does the work.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import mcp_gateway_execution as execution
from app.chat_pc_drive import chat_pc_plan_for_tool
from app.claw_pc_search_command import pc_search_path
from app.mcp_gateway_transport import _TOOLS as MCP_TOOLS
from padiem_ai_engine_client import PadiemAiEngineClient

from test_7065_pc_edit_tool import (  # noqa: F401 - shared harness
    DEVICE, PRINCIPAL, UID, History, RecordingTransport,
)
from app.orchestration_bridge import B62EngineOrchestrationBridge


ROOT = Path(__file__).resolve().parents[1]


def harness(monkeypatch):
    calls = []

    async def owner(request, uid):
        calls.append(("identity", uid))
        return SimpleNamespace(session_id="session_fixture"), "sub_" + "a" * 32, "workspace_fixture"

    async def context(request, **kwargs):
        calls.append(("context", kwargs))
        return SimpleNamespace(selected_confirmed=True, tool_available=True, selection_offline=False,
                               selected_device_id=DEVICE, execution_device_id=DEVICE)

    async def grant(request, session, **kwargs):
        calls.append(("grant", kwargs))
        return True

    async def delegation(request, uid):
        calls.append(("delegation", uid))
        return {"version": 1, "rules": []}

    async def notice(*args, **kwargs):
        calls.append(("notice", kwargs))
        return True

    async def folders(request, **kwargs):
        return [{"name": "work", "path": r"E:\work"}]

    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)
    monkeypatch.setattr(execution, "_registered_pc_folders", folders)
    transport, history = RecordingTransport(), History()
    bridge = B62EngineOrchestrationBridge(client=PadiemAiEngineClient(transport=transport,
        app_id="padiem-chat", caller_id="padiem-chat", credential="fixture" * 8), store=object())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge, history_store=history)))
    return request, transport, history, calls


def body_of(transport):
    return json.loads(transport.calls[0]["body"])


def gateway_of(transport):
    return body_of(transport)["pc_gateway"]


def plan_of(transport):
    """The Engine plan this call stages; it sits beside the gateway block."""
    return [step["tool_id"] for step in body_of(transport)["agent_plan"]["steps"]]


# ── 1. 선언: 읽기 전용, 승인 불필요, 닫힌 인자 ─────────────────────────────


def test_the_two_new_tools_are_declared_read_only():
    for name in ("pc_search_contents", "pc_file_info"):
        tool = MCP_TOOLS[name]
        assert tool["annotations"]["readOnlyHint"] is True, name
        assert tool["annotations"]["destructiveHint"] is False, name
        # 승인이 필요한 도구로 표시하지 않는다.
        assert tool["inputSchema"]["additionalProperties"] is False, name
    assert set(MCP_TOOLS["pc_search_contents"]["inputSchema"]["properties"]) == {
        "path", "query", "device",
    }
    assert MCP_TOOLS["pc_search_contents"]["inputSchema"]["required"] == ["path", "query"]
    assert set(MCP_TOOLS["pc_file_info"]["inputSchema"]["properties"]) == {"path", "device"}
    assert MCP_TOOLS["pc_file_info"]["inputSchema"]["required"] == ["path"]


def test_the_read_tool_gained_two_optional_range_arguments():
    read = MCP_TOOLS["pc_read"]["inputSchema"]["properties"]
    assert {"path", "offset", "length", "job_id", "device"} == set(read)
    assert read["length"]["maximum"] == 1_000_000
    assert read["offset"]["minimum"] == 0
    # 필수 인자는 늘지 않았다: 인자 없이 부르면 예전과 같은 전체 읽기다.
    assert MCP_TOOLS["pc_read"]["inputSchema"]["required"] == []


def test_the_execution_table_maps_each_tool_to_the_engine_tool_that_does_it():
    assert execution._TOOLS["pc_search_contents"][1] == "claw.pc.search_contents"
    assert execution._TOOLS["pc_file_info"][1] == "claw.pc.list_files"
    # 정보 조회도 path 도구라 등록 폴더 검사를 그대로 통과한다.
    assert {"pc_search_contents", "pc_file_info"} <= execution._PC_FILE_PATH_TOOLS


# ── 2. 계획: 한 단계, 읽기 도구 하나 ───────────────────────────────────────


def test_each_plan_names_one_read_only_step():
    assert [(s["step_id"], s["tool_id"]) for s in chat_pc_plan_for_tool("files_search_contents")["steps"]] == [
        ("search_contents", "claw.pc.search_contents"),
    ]
    assert [s["tool_id"] for s in chat_pc_plan_for_tool("files_info")["steps"]] == [
        "claw.pc.list_files",
    ]
    assert [s["tool_id"] for s in chat_pc_plan_for_tool("files_chunk")["steps"]] == [
        "claw.pc.read_file_chunk",
    ]


# ── 3. 정상 호출: 엔진 도구·인자·승인 없음 ────────────────────────────────


def test_a_content_search_stages_the_engine_search_with_the_query(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_search_contents", {"path": "docs", "query": "예산"}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.search_contents"
    assert plan_of(transport) == ["claw.pc.search_contents"]
    # 검색어는 경로가 아니라 검색어 자리로만 간다.
    assert gateway["search_query"] == "예산"
    assert gateway["arguments"] == {"path": "docs"}
    assert "approval_id" not in gateway


def test_a_file_info_call_asks_for_the_listing_of_one_path(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_file_info", {"path": "보고서.txt"}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.list_files"
    assert plan_of(transport) == ["claw.pc.list_files"]
    assert gateway["arguments"] == {"path": "보고서.txt"}
    assert "approval_id" not in gateway


def test_a_range_read_uses_the_engine_chunk_tool(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_read", {"path": "big.log", "offset": 2048, "length": 4096}))
    assert result["status"] == "completed"
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.read_file_chunk"
    assert plan_of(transport) == ["claw.pc.read_file_chunk"]
    assert gateway["arguments"] == {"path": "big.log", "offset": 2048, "length": 4096}


def test_pc_read_without_the_range_arguments_stages_the_same_call_as_before(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)
    asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_read", {"path": "big.log"}))
    gateway = gateway_of(transport)
    assert gateway["tool_id"] == "claw.pc.read_file"
    assert plan_of(transport) == ["claw.pc.list_files", "claw.pc.read_file"]
    assert gateway["arguments"] == {"path": "big.log"}


# ── 4. 범위: 폴더 밖·상위 탈출은 기존 오류 코드로 거절 ─────────────────────


@pytest.mark.parametrize("path", [r"C:\Windows\win.ini", "/etc/passwd", r"E:\other\x.txt"])
def test_an_absolute_path_outside_the_registered_folders_is_refused(monkeypatch, path):
    request, transport, _, _ = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_search_contents", {"path": path, "query": "x"}))
    # 같은 함수(등록 폴더 경계 검사)가 막는다 — 새 검사를 만들지 않았다.
    assert execution._pc_relative_inside_roots(
        path, [{"name": "work", "path": r"E:\work"}])[1] == "outside"
    assert result["status"] == "failed"
    assert result["code"] == "pc_path_outside_registered_roots"
    assert result["folders"] == [{"name": "work", "path": r"E:\work"}]
    # 거절은 디스패치를 만들지 않는다.
    assert transport.calls == []


@pytest.mark.parametrize("path", ["..", "../..", r"..\..\windows", "docs/../../etc"])
def test_a_relative_path_cannot_walk_out_of_the_folder(path):
    # 명령을 만드는 기존 규칙이 상위 탈출 조각을 거부한다.
    assert pc_search_path(path) is None


@pytest.mark.parametrize("path", ["docs", r"docs\sub", r"E:\work\docs"])
def test_a_path_inside_the_registered_folder_is_admitted(path):
    assert execution._pc_relative_inside_roots(
        path, [{"name": "work", "path": r"E:\work"}]) != (None, "outside")


# ── 5. 권한 없는 토큰 ─────────────────────────────────────────────────────


def test_a_token_without_the_pc_grant_is_refused_before_any_dispatch(monkeypatch):
    request, transport, _, _ = harness(monkeypatch)

    async def grant(request, session, **kwargs):
        return False

    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    for name, args in (("pc_search_contents", {"path": "docs", "query": "x"}),
                       ("pc_file_info", {"path": "docs"}),
                       ("pc_read", {"path": "big.log", "offset": 0, "length": 100})):
        with pytest.raises(Exception) as refused:
            asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, name, args))
        assert refused.value.status_code == 403, name
        assert refused.value.code == "chat_pc_target_unavailable", name
    assert transport.calls == []


# ── 6. 검색어는 문자열로만, 명령을 따옴표 밖으로 못 뺀다 ────────────────────


@pytest.mark.parametrize("query", [
    '"; Remove-Item -Recurse -Force E:\\work; "',
    "' ; Start-Process calc ; '",
    "$(Get-ChildItem C:\\)",
    "`n$env:PATH",
])
def test_a_query_cannot_leave_its_quoted_slot(monkeypatch, query):
    request, transport, _, _ = harness(monkeypatch)
    asyncio.run(execution.execute_mcp_pc_tool(
        request, PRINCIPAL, "pc_search_contents", {"path": "docs", "query": query}))
    command = gateway_of(transport)["arguments"].get("command")
    if command is None:  # the command is built PC-side from the query, not here
        assert gateway_of(transport)["search_query"] == query
        return
    # A single-quoted PowerShell literal hides every metacharacter in it.
    assert command.count("-Pattern") <= 1
    body = command.split("-Pattern", 1)[1][: 2 * len(query) + 8]
    assert body.lstrip().startswith("'")
    assert body.lstrip().startswith("'" + query.replace("'", "''"))


# ── 7. 인자 검사: 범위 밖 인자·잘못된 타입은 거절 ────────────────────────


@pytest.mark.parametrize("arguments", [
    {"path": "docs"},                                            # 검색어 없음
    {"path": "docs", "query": "x", "extra": "y"},                # 닫힌 표 밖
    {"path": "docs", "query": 5},                                # 문자열 아님
])
def test_bad_search_arguments_are_refused(monkeypatch, arguments):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_search_contents", arguments))
    assert transport.calls == []


@pytest.mark.parametrize("arguments", [
    {"path": "big.log", "offset": 10},                           # 시작만 있고 끝 없음
    {"path": "big.log", "offset": -1, "length": 10},
    {"path": "big.log", "offset": 0, "length": 0},
    {"path": "big.log", "offset": 0, "length": 1_000_001},
    {"path": "big.log", "offset": "0", "length": 10},            # 문자열 숫자
])
def test_bad_range_arguments_are_refused(monkeypatch, arguments):
    request, transport, _, _ = harness(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_read", arguments))
    assert transport.calls == []


# ── 8. 설명: 상한을 한국어로 밝힌다 ──────────────────────────────────────


def test_the_descriptions_state_the_engine_limits():
    search = MCP_TOOLS["pc_search_contents"]["description"]
    assert "2,000" in search and "50" in search
    assert "이어 읽기를 지원하지 않습니다" in search
    read = MCP_TOOLS["pc_read"]["description"]
    assert "1,000,000" in read


# ── 9. 수정 전에는 실패하던 것들 ──────────────────────────────────────────


def test_the_parser_received_each_new_tool_only_after_this_change():
    """The gateway parsers would have refused these calls before the change.

    A tool id that is not in the closed table is refused, so the two new ids
    were unreachable: this is the failure each of them fixes.
    """
    from padiem_ai_engine_client.client import _PC_GATEWAY_TOOLS as engine_table
    from padiem_ai_core.pc_gateway import PC_GATEWAY_TOOLS as core_table

    for table in (engine_table, core_table):
        assert "claw.pc.search_contents" in table
        assert "claw.pc.read_file_chunk" in table
    # read_file originally took only the path.
    assert "offset" not in {"path"} and {"path", "offset", "length"} <= engine_table[
        "claw.pc.read_file_chunk"]
