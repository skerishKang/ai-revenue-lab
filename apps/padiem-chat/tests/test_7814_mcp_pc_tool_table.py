"""#7814 T4 — `execute_mcp_pc_tool` 1/2 앞 구간 골든 표.

`_mcp_pc_tool_intake`로 옮긴 입력·도구 이름·인자·승인 검사 구간이 지키던
계약을 리팩터링 전 `main`의 실행 결과 그대로 고정한다. 보안 경계이므로
검사 순서와 예외 종류·메시지를 함께 고정한다.

- 옮긴 구간의 raise 13개와 return 3개를 하나씩 일으킨다.
- 검사가 2개 이상 걸리는 입력 3개로 어느 쪽이 먼저 나는지 고정한다.
- 정상 입력 2개는 끝까지 돌려 디스패치 인자와 최종 응답을 고정한다.

골든은 같은 방식으로 리팩터링 전 `main`에서 먼저 떴다
(`fixtures/mcp_pc_tool_7814_intake.json`). 값은 전부 합성값이다.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app import mcp_gateway_execution as execution
from app.mcp_gateway_store import mcp_request_digest
from test_mcp_gateway_execution import PRINCIPAL, harness

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "fixtures" / "mcp_pc_tool_7814_intake.json"
)

VALID_WRITE = {"path": "notes.txt", "content": "hello"}
VALID_READ = {"path": "notes.txt"}


def _snapshot_raise(error: Exception) -> dict:
    return {"outcome": "raise", "error": f"{type(error).__name__}: {error}"}


def snapshot(case: str, monkeypatch) -> dict:
    request, transport, history, calls = harness(monkeypatch)
    state = request.app.state
    principal = PRINCIPAL
    tool = "pc_read"
    arguments = VALID_READ
    approval = None

    if case == "principal_not_mapping":
        principal = "not-a-mapping"
    elif case == "principal_invalid_fields":
        principal = {**PRINCIPAL, "owner_id": None}
    elif case == "tool_unsupported":
        tool = "bogus_tool"
    elif case == "shell_args_invalid":
        tool, arguments = "pc_shell", {"command": 123}
    elif case == "args_wrong_keys":
        arguments = {"path": "notes.txt", "owner_id": "forged"}
    elif case == "edit_replace_all_bad":
        tool, arguments = "pc_edit", {
            "path": "notes.txt", "old_text": "a", "new_text": "b", "replace_all": "false",
        }
    elif case == "write_mode_bad":
        tool, arguments = "pc_write", {"path": "notes.txt", "content": "x", "mode": "prepend"}
    elif case == "read_range_half":
        arguments = {"path": "notes.txt", "offset": 4}
    elif case == "search_recursive_bad":
        tool, arguments = "pc_search", {"query": "x", "recursive": "true"}
    elif case == "list_depth_bad":
        tool, arguments = "pc_list", {"path": ".", "depth": 9}
    elif case == "search_recursive_no_query":
        tool, arguments = "pc_search", {"recursive": True}
    elif case == "browser_approval":
        tool, arguments = "pc_browser_read", {}
        approval = {"approval_id": "a", "request_digest": "d"}
    elif case == "approval_bad_digest":
        tool, arguments = "pc_write", VALID_WRITE
        approval = {"approval_id": "a", "request_digest": "wrong"}
    elif case == "pc_devices":
        tool, arguments = "pc_devices", {}
        async def _devices(req, *, owner_id, principal):
            return [{"id6": "dev1", "name": "PC-one"}]
        monkeypatch.setattr("app.mcp_device_selection.list_owner_devices", _devices)
    elif case == "shell_start_interactive":
        tool, arguments = "pc_shell_start", {"interactive": True, "command": "dir", "mode": "system"}
    elif case == "shell_system_denied":
        tool, arguments = "pc_shell", {"command": "dir", "mode": "system"}
        state.settings = type("S", (), {
            "mcp_pc_shell_enabled": True, "mcp_pc_shell_user_mode_enabled": False,
        })()
        async def _not_allowed(req, *, uid, device_id):
            return False
        monkeypatch.setattr(execution, "_pc_system_mode_allowed", _not_allowed)
    elif case == "order_principal_before_tool":
        principal, tool = {**PRINCIPAL, "owner_id": None}, "bogus_tool"
    elif case == "order_args_before_approval":
        tool, arguments = "pc_write", {"path": "notes.txt", "content": "x", "mode": "prepend"}
        approval = {"approval_id": "a", "request_digest": "wrong"}
    elif case == "order_interactive_before_disabled":
        tool, arguments = "pc_shell_start", {"interactive": True, "command": "dir", "mode": "system"}
        state.settings = type("S", (), {
            "mcp_pc_shell_enabled": False, "mcp_pc_shell_user_mode_enabled": False,
        })()
    elif case == "normal_read":
        tool, arguments = "pc_read", VALID_READ
    elif case == "normal_write_approval":
        tool, arguments = "pc_write", VALID_WRITE
        approval = {
            "approval_id": "approval_fixture",
            "request_digest": mcp_request_digest("pc_write", VALID_WRITE),
        }
    else:
        raise AssertionError(case)

    try:
        result = asyncio.run(
            execution.execute_mcp_pc_tool(request, principal, tool, arguments, approval=approval)
        )
    except Exception as exc:
        return _snapshot_raise(exc)

    out = {"outcome": "return", "response": result, "calls_order": [item[0] for item in calls[:3]]}
    if transport.calls:
        sent = json.loads(transport.calls[0]["body"])
        gateway = dict(sent.get("pc_gateway", {}))
        gateway["request_id"] = "<request_id>" if gateway.get("request_id") else None
        out["dispatch"] = {
            "tool_id": gateway.get("tool_id"),
            "arguments": gateway.get("arguments"),
            "source": gateway.get("source"),
            "token_id": gateway.get("token_id"),
            "approval_id": gateway.get("approval_id"),
            "request_id": gateway.get("request_id"),
            "tool_arguments": sent.get("tool_arguments"),
            "subject_id": sent.get("subject_id"),
            "pc_action_context": sent.get("pc_action_context"),
            "pc_delegation": sent.get("pc_delegation"),
        }
    else:
        out["dispatch"] = None
    out["final_run_id"] = "<run_id>" if result.get("run_id") else None
    result = dict(result)
    result.pop("run_id", None)
    out["response"] = result
    out["history_actions"] = [item["action"] for item in history.runs]
    return out


CASES = (
    "principal_not_mapping", "principal_invalid_fields", "tool_unsupported",
    "shell_args_invalid", "args_wrong_keys", "edit_replace_all_bad",
    "write_mode_bad", "read_range_half", "search_recursive_bad",
    "list_depth_bad", "search_recursive_no_query", "browser_approval",
    "approval_bad_digest", "pc_devices", "shell_start_interactive",
    "shell_system_denied", "order_principal_before_tool",
    "order_args_before_approval", "order_interactive_before_disabled",
    "normal_read", "normal_write_approval",
)


def test_golden_is_the_pre_refactor_intake_table():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert set(golden) == set(CASES)
    assert golden["principal_not_mapping"]["error"].startswith("ValueError: A verified")
    assert golden["principal_invalid_fields"]["error"] == "ValueError: Invalid MCP principal"
    assert golden["tool_unsupported"]["error"] == "ValueError: Unsupported MCP PC tool"
    assert golden["approval_bad_digest"]["error"] == "ValueError: MCP approval does not match this request"
    assert golden["browser_approval"]["error"] == (
        "ValueError: Browser confirmation must use ordinary first-party conversation"
    )
    assert golden["pc_devices"]["outcome"] == "return"
    assert golden["normal_read"]["dispatch"]["source"] == "mcp"
    assert golden["normal_write_approval"]["dispatch"]["approval_id"] == "approval_fixture"


@pytest.mark.parametrize("case", CASES)
def test_intake_snapshot_matches_the_pre_refactor_golden(case, monkeypatch):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[case]
    assert snapshot(case, monkeypatch) == golden
