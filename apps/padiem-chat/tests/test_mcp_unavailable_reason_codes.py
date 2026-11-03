"""#6717 후속: MCP unavailable이 분기 이름까지 남는다.

05:02 실측에서 pc_list·pc_shell이 status=unavailable로 끝났는데 이유는
별도 줄(`chat_pc_mesh_grant_denied=…`)에만 있었고, 요청과 연결되지 않았다.
이 파일은 세 절을 고정한다.

1. `command_target_matches`가 0행·1행·2행을 구분한다(`command_target`은
   단일 행만 대상으로 하므로 0과 2 이상이 같은 None이었다).
2. `_check_mesh_grant`가 거절 분기 코드를 호출자에게 전달한다
   (not_found / not_unique 구분 포함).
3. dispatch가 ChatPCDriveError를 잡아 `deny_reason`을 mcp_operation
   이벤트에 실는다. 소유자에게 보이는 문안은 그대로다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app import mcp_gateway_dispatch as dispatch
from app import mcp_gateway_execution as execution
from app.chat_pc_drive import ChatPCDriveError
from app.oracle_mesh_read_return_routes import OracleMeshReturnSource

UID = "usr_" + "a" * 32
NODE = "k0pVCZx5VqYn8P9FW23CaqTNZWHGSlLASVKF1tqJTPRjRGBOhcTfgZbmfi$D62t1"


def _source(rows):
    return OracleMeshReturnSource(rows, "x" * 32)


def _row(account_ref=UID, path="notes.txt", command_exec=True):
    return {"account_ref": account_ref, "device_id": None, "node_ref": "node-fixture",
            "root_ref": "root-fixture", "path_relative": path, "file_path": path,
            "command_exec": command_exec}


def test_command_target_matches_distinguishes_zero_one_and_two():
    src = _source([_row()])
    assert src.command_target_matches(account_ref=UID, device_id=NODE) \
        and len(src.command_target_matches(account_ref=UID, device_id=NODE)) == 1
    assert src.command_target(account_ref=UID, device_id=NODE) is not None

    empty = _source([_row(account_ref="usr_" + "b" * 32)])
    assert empty.command_target_matches(account_ref=UID, device_id=NODE) == []
    assert empty.command_target(account_ref=UID, device_id=NODE) is None

    ambiguous = _source([_row(path="a.txt"), _row(path="b.txt")])
    matches = ambiguous.command_target_matches(account_ref=UID, device_id=NODE)
    assert len(matches) == 2
    assert ambiguous.command_target(account_ref=UID, device_id=NODE) is None


def _grant_harness(monkeypatch, *, matches):
    """A request whose every gate passes except the command-target lookup."""
    class _Identity:
        async def resolve_connector_owner_scope(self, session_id=None):
            return {"account_ref": UID}

    class _State:
        oracle_mesh_return_source = SimpleNamespace(
            configured=True, execution_mode="mesh",
            command_target=lambda **kwargs: None,
            command_target_matches=lambda **kwargs: list(matches),
        )
        control_plane_identity_authority = _Identity()

    class _App:
        state = _State()

    request = SimpleNamespace(app=_App())
    session = SimpleNamespace(session_id="session_fixture")
    captured: list[str] = []
    return request, session, captured


@pytest.mark.parametrize("matches,expected", [
    ([], "mesh_command_target_not_found"),
    ([_row(), _row(path="b.txt")], "mesh_command_target_not_unique"),
])
def test_check_mesh_grant_names_the_zero_and_ambiguous_cases(monkeypatch, matches, expected):
    request, session, captured = _grant_harness(monkeypatch, matches=matches)
    ok = asyncio.run(execution._check_mesh_grant(request, session, device_id=NODE,
                                                 denied_reason=captured))
    assert ok is False
    assert captured == [expected]


def test_execute_carries_the_denial_reason_on_the_error(monkeypatch):
    request, session, captured = _grant_harness(monkeypatch, matches=[])
    async def owner(request, uid):
        return session, "sub_" + "a" * 32, "workspace_fixture"
    async def context(request, **kwargs):
        return SimpleNamespace(selected_confirmed=True, tool_available=True,
                               execution_device_id=NODE)
    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)

    with pytest.raises(ChatPCDriveError) as refused:
        asyncio.run(execution.execute_mcp_pc_tool(
            request, {"owner_id": UID, "device_id": NODE, "token_id": "mcp_token_fixture"},
            "pc_list", {"path": "D:\\"}))
    assert refused.value.cause == "mesh_command_target_not_found"


def test_dispatch_logs_deny_reason_in_the_operation_event(caplog):
    class _Store:
        async def audit(self, **kwargs):
            return True

        async def consume_matching_approval(self, **kwargs):
            return None

    async def executor(request, principal, tool_name, arguments, *, approval=None):
        raise ChatPCDriveError("chat_pc_target_unavailable", "이 토큰의 PC에 접근할 수 없습니다.",
                               403, cause="mesh_command_target_not_found")

    class _State:
        # staticmethod: a plain function on a class binds as a method and the
        # dispatch call would lose its first argument to the instance.
        mcp_gateway_store = _Store()
        mcp_gateway_executor = staticmethod(executor)

    request = SimpleNamespace(app=SimpleNamespace(state=_State()))
    principal = {"owner_id": UID, "device_id": "dev_x", "token_id": "mcp_token_fixture"}
    try:
        outcome = asyncio.run(dispatch.dispatch_mcp_tool(
            request, principal, "pc_shell", {"command": "hostname", "cwd": "D:\\"}))
    except Exception as exc:
        print("PROPAGATED:", type(exc).__name__, repr(str(exc))[:120])
        raise
    print("DISPATCH_FILE:", dispatch.__file__)
    print("OUTCOME:", outcome)
    assert outcome["status"] == "unavailable"
    assert outcome["deny_reason"] == "mesh_command_target_not_found"

    events = [json.loads(r.message) for r in caplog.records
              if r.levelno == logging.INFO and r.message.startswith("{")]
    mine = [e for e in events if e.get("event") == "mcp_operation"
            and e.get("status") == "unavailable" and e.get("tool") == "pc_shell"]
    assert mine and mine[-1].get("deny_reason") == "mesh_command_target_not_found"
