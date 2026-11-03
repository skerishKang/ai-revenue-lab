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

import json

import pytest
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

from app import mcp_gateway_dispatch as dispatch
from app import mcp_gateway_execution as execution
from app.chat_pc_drive import ChatPCDriveError
from app.oracle_mesh_read_return_routes import OracleMeshReturnSource
from app.orchestration_bridge import B62EngineOrchestrationBridge

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


def _grant_harness(*, matches=None, scope_ref=UID, links=None, source=None):
    """A request whose every gate passes except the command-target lookup.

    ``matches`` fixes what the source's command_target_matches answers (the
    real source derives it from the map rows); ``links`` is the owner's
    pc_device_links as the pairing store answers them.
    """

    class _Identity:
        async def resolve_connector_owner_scope(self, session_id=None):
            return {"account_ref": scope_ref, "workspace_ref": "workspace_fixture"}

    class _Pairing:
        async def links_for_owner(self, *, user_id):
            return list(links or [])

    if source is not None:
        class _Mesh(OracleMeshReturnSource):
            execution_mode = "mesh"
        mesh = _Mesh(source._rows, "x" * 32)
    else:
        mesh = SimpleNamespace(
            configured=True, execution_mode="mesh",
            command_target=lambda **kwargs: None,
            command_target_matches=lambda **kwargs: list(matches or []),
        )

    class _RecordingTransport:
        async def request(self, **kwargs):
            return EngineTransportResponse(status=200, headers={}, body=json.dumps(
                {"ok": True, "orchestration": {"events": [], "execution": {"answer": "확인"}}},
            ).encode())

    class _History:
        async def record_chat_pc_drive_run(self, **kwargs):
            return "conv_fixture"

    class _State:
        oracle_mesh_return_source = mesh
        control_plane_identity_authority = _Identity()
        pc_device_pairing_store = _Pairing()
        history_store = _History()
        orchestration_bridge = B62EngineOrchestrationBridge(
            client=PadiemAiEngineClient(transport=_RecordingTransport(),
                app_id="padiem-chat", caller_id="padiem-chat", credential="fixture" * 8),
            store=object())

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
    request, session, captured = _grant_harness(matches=matches)
    ok = asyncio.run(execution._check_mesh_grant(request, session, device_id=NODE,
                                                 denied_reason=captured))
    assert ok is False
    assert captured == [expected]


def test_execute_carries_the_denial_reason_on_the_error(monkeypatch):
    request, session, captured = _grant_harness(matches=[])
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


# ── #6717 재시험 실패의 PC 단위 확정 (a안) ────────────────────────────────────
#
# 대표 계정에 연결 PC가 3대다. 계정 단위 맵 행은 PC를 정하지 못하므로, 요청의
# device(커넥터 토큰에 묶인 PC)가 소유자의 활성 pc_device_links 중 정확히 하나일
# 때 그 PC로 확정하고, 링크에 없는 device는 거절한다. 다른 계정은 계속 거절.

OWNER_LINKS = [
    {"mesh_node_id": NODE, "state": "active", "label": "컴2"},
    {"mesh_node_id": "node_O4VslOUq", "state": "active", "label": "컴1"},
    {"mesh_node_id": "node_7P4oTs4h", "state": "active", "label": "CGI-1"},
    {"mesh_node_id": "node_wYx8HR9O", "state": "revoked", "label": "낡은 PC"},
]


def test_token_device_among_three_pcs_resolves_to_that_pc():
    # 대표 계정에 연결 PC 3대(활성 링크 3). 계정 단위 명령 행이 PC 3대에
    # 걸리는 모양(미지정 행 3)이어도, 요청 device가 소유자 활성 링크 중
    # 정확히 하나면 그 PC로 확정해 통과한다.
    src = _source([_row(path="a.txt"), _row(path="b.txt"), _row(path="c.txt")])
    assert src.command_target(account_ref=UID, device_id=NODE) is None
    assert len(src.command_target_matches(account_ref=UID, device_id=NODE)) == 3

    request, session, _c = _grant_harness(
        source=src, links=OWNER_LINKS, scope_ref="scope-form-" + "x" * 8)
    ok = asyncio.run(execution._check_mesh_grant(
        request, session, device_id=NODE, owner_ref=UID))
    assert ok is True

    # 현재 운영 형태(미지정 행 하나)도 같은 경로로 통과한다.
    request2, session2, _c2 = _grant_harness(
        source=_source([_row()]), links=OWNER_LINKS, scope_ref="scope-form-" + "x" * 8)
    assert asyncio.run(execution._check_mesh_grant(
        request2, session2, device_id=NODE, owner_ref=UID)) is True


def test_token_device_not_in_the_owner_links_is_refused():
    request, session, captured = _grant_harness(
        source=_source([_row()]), links=[
            {"mesh_node_id": "node_other_pc", "state": "active", "label": "다른 PC"}],
        scope_ref="scope-form-" + "x" * 8)
    ok = asyncio.run(execution._check_mesh_grant(
        request, session, device_id=NODE, owner_ref=UID, denied_reason=captured))
    assert ok is False
    assert captured == ["mesh_command_target_device_not_linked"]


def test_another_owners_rows_never_serve_this_token():
    rows = [_row(account_ref="usr_" + "b" * 32, path="a.txt")]
    src = _source(rows)
    assert src.command_target(account_ref=UID, device_id=NODE) is None
    assert src.command_target_matches(account_ref=UID, device_id=NODE) == []

    request, session, captured = _grant_harness(
        source=_source(rows), links=OWNER_LINKS,
        scope_ref="scope-form-" + "x" * 8)
    ok = asyncio.run(execution._check_mesh_grant(
        request, session, device_id=NODE, owner_ref=UID, denied_reason=captured))
    assert ok is False
    assert captured == ["mesh_command_target_not_found"]


def test_single_pc_account_still_resolves_as_before():
    rows = [_row()]
    src = _source(rows)
    assert src.command_target(account_ref=UID, device_id=NODE) is not None

    request, session, _c = _grant_harness(source=src, links=OWNER_LINKS)
    ok = asyncio.run(execution._check_mesh_grant(
        request, session, device_id=NODE, owner_ref=UID))
    assert ok is True


def test_shell_start_refusal_carries_the_intent_code(monkeypatch):
    # 큐 투입이 503으로 거절된 경우(예: oracle_mesh_device_directory_unavailable),
    # 소유자 문안은 그대로 두고 분기 코드만 이벤트에 실린다.
    from starlette.responses import JSONResponse

    from app import oracle_mesh_read_return_routes as mesh_routes

    calls: list[str] = []

    async def fake_intent(request, **kwargs):
        calls.append("intent")
        return JSONResponse({"ok": False, "error": {"code": "oracle_mesh_device_directory_unavailable",
            "message": "메시 장치 디렉터리를 사용할 수 없습니다."}}, status_code=503)

    monkeypatch.setattr(mesh_routes, "dispatch_oracle_mesh_command_intent", fake_intent)

    class _Store:
        async def audit(self, **kwargs):
            return True

        async def consume_matching_approval(self, **kwargs):
            return None

        async def cancel_oracle_mesh_dispatches_for_run(self, **kwargs):
            return 0

        async def record_chat_pc_drive_run(self, **kwargs):
            return "conv_fixture"

    async def executor(request, principal, tool_name, arguments, *, approval=None):
        session = SimpleNamespace(session_id="session_fixture")
        return await execution.execute_pc_shell_start(
            request, uid=principal["owner_id"], workspace_id="workspace_fixture",
            device_id=principal["device_id"], run_id="chat_pcq_fixture",
            session=session, conversation_id=None, arguments=arguments)

    class _State:
        mcp_gateway_store = _Store()
        mcp_gateway_executor = staticmethod(executor)
        oracle_mesh_return_source = SimpleNamespace(
            configured=True, execution_mode="mesh",
            command_target=lambda **kwargs: {"account_ref": UID, "command_exec": True},
            command_target_matches=lambda **kwargs: [_row()],
        )
        control_plane_identity_authority = SimpleNamespace(
            resolve_connector_owner_scope=lambda **kwargs: {"account_ref": UID})
        pc_device_pairing_store = SimpleNamespace(
            links_for_owner=lambda **kwargs: [{"mesh_node_id": NODE, "state": "active"}])
        history_store = _Store()
        orchestration_bridge = "unused-in-this-branch"

    request = SimpleNamespace(app=SimpleNamespace(state=_State()))
    principal = {"owner_id": UID, "device_id": NODE, "token_id": "mcp_token_fixture"}
    outcome = asyncio.run(dispatch.dispatch_mcp_tool(
        request, principal, "pc_shell_start", {"command": "hostname", "cwd": "D:\\"}))
    assert calls == ["intent"]
    assert outcome["status"] == "unavailable"
    assert outcome["answer"] == "PC 작업을 시작하지 못했습니다."
    assert outcome["deny_reason"] == "oracle_mesh_device_directory_unavailable"
