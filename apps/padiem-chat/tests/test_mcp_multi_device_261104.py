"""2026-11-04(대표 요청) — MCP 한 연결로 여러 PC를 고른다.

pc_devices가 소유자의 연결 PC 목록(표시 이름·id6·온라인·기본 PC)을 알려 주고,
모든 pc_* 도구의 ``device`` 인자가 대상 PC를 고른다. 거절 계약:

- 토큰 소유 계정의 연결 PC가 아니면 ``device_not_linked``
- 연결돼 있어도 토큰 범위(동의 화면 결정) 밖이면 ``device_not_in_token_scope``
- 선택한 PC가 꺼져 있으면 ``device_offline`` (인자 없는 기본 경로는 기존
  ``pc_offline`` 그대로 — 하위 호환)
- 두 기기가 같은 id6·이름이면 ``device_ambiguous``

기존 단일 PC 토큰(device_scope NULL)은 토큰의 PC만 허용한다. pc_shell_read/
stop은 작업 ID가 PC를 정한다 — 같은 토큰이 다른 PC에서 시작한 작업도 읽고
중지할 수 있고, 다른 계정·다른 토큰의 작업은 거절된다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.mcp_gateway_dispatch import dispatch_mcp_tool
from app.mcp_gateway_execution import execute_mcp_pc_tool
from app.mcp_device_selection import McpDeviceRefusal

from test_mcp_gateway_account import DEVICE as DEVICE_A, setup, client_for, session
from test_5222_account_model_selection import BASE, build_app
from test_mcp_oauth_261103 import (
    RESOURCE, REDIRECT, _approve, _code_from, _exchange, _params, _register,
)

from app import mcp_gateway_execution as execution_module


@pytest.fixture(autouse=True)
def _system_shell_caller_is_allowed(monkeypatch):
    """#7565: these cases exercise other gates (offline PC, grant, selection)
    with the SYSTEM default mode. The SYSTEM rule itself (administrator +
    managed PC) is covered in test_pc_tool_turn_e2e_261107, so here the caller
    is an allowed SYSTEM caller and each case still reaches its own gate."""
    from app import mcp_gateway_execution as _execution

    async def _allowed(request, *, uid, device_id):
        return True

    monkeypatch.setattr(_execution, "_pc_system_mode_allowed", _allowed)



class RecordingTransport:
    """Engine SDK 전송 대역 — 완료 응답을 고정으로 돌려준다."""

    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        body = json.dumps({"ok": True,
            "orchestration": {"events": [{"event_id": "event_fixture",
                "run_id": "run_fixture", "trace_id": "trace_fixture",
                "app_id": "padiem-chat", "kind": "run_completed", "sequence": 1}],
                "execution": {"answer": json.dumps(
                    {"status": "completed", "answer": "확인했습니다.",
                     "output": {"value": "fixture result"}})}}}).encode()
        from padiem_ai_engine_client import EngineTransportResponse
        return EngineTransportResponse(status=200, headers={}, body=body)


class RecordingHistory:
    def __init__(self):
        self.runs = []

    async def record_chat_pc_drive_run(self, **kwargs):
        self.runs.append(kwargs)
        return "conv_fixture"

DEVICE_B = "node//studio-second"
LABEL_A = "사무실 PC"
LABEL_B = "작업실 PC"


class MultiPairing:
    """한 소유자에 두 대: 라벨이 서로 다른 활성 링크 두 개."""

    def __init__(self, owner, devices):
        self.owner = owner
        self.devices = list(devices)
        self.active = True

    def _links(self, user_id):
        if not self.active or user_id != self.owner:
            return []
        return [{"mesh_node_id": device_id, "label": label,
                 "roots": [{"path": "C:/Documents"}]}
                for device_id, label in self.devices]

    async def link_for(self, *, user_id, mesh_node_id):
        if user_id == self.owner and mesh_node_id in dict(self.devices):
            return {"mesh_node_id": mesh_node_id, "roots": [{"path": "C:/Documents"}]}
        return None

    async def links_for_owner(self, *, user_id):
        return self._links(user_id)


class Presence:
    """mesh_device_presence 가짜: online_devices에 담긴 기기만 온라인."""

    def __init__(self, online_devices):
        self.online_devices = set(online_devices)

    async def load(self, device_id):
        if device_id not in self.online_devices:
            return None
        # The receipt must be fresh when the product reads it, not when this
        # module was collected: the full suite can take longer than the
        # 180-second presence window, which made this test order-dependent.
        return {"device_id": device_id, "connected": True, "source": "mesh",
                "credential_generation": None,
                "received_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()}


def app_with(owner, store, *, devices=None, online=()):
    app = build_app(store.db if hasattr(store, "db") else None)
    app.state.mcp_gateway_store = store
    pairing = MultiPairing(owner, devices or [(DEVICE_A, LABEL_A), (DEVICE_B, LABEL_B)])
    app.state.pc_device_pairing_store = pairing
    app.state.mesh_device_presence_store = Presence(online)
    return app, pairing



def _issue_token(store, db, owner, device_id=DEVICE_A, *, scope=None, scope_json=None):
    """실제 토큰 행을 발급한다 — 감사 FK가 토큰 행을 요구한다."""
    token = asyncio.run(store.issue_token(user_id=owner, device_id=device_id, name="시험 AI"))
    if scope is not None:
        asyncio.run(db.prepare(
            "UPDATE padiem_mcp_tokens SET device_scope=?, device_scope_json=? WHERE id=?"
        ).bind(scope, scope_json, token["id"]).run())
    return token["id"]


def principal_for(owner, device_id, token_id, *, scope=None, scope_json=None):
    return {"owner_id": owner, "device_id": device_id, "token_id": token_id,
            "name": "시험 AI", "device_scope": scope, "device_scope_json": scope_json}


def request_for(app):
    return SimpleNamespace(app=app)


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def __call__(self, request, principal, name, arguments, *, approval=None):
        self.calls.append({"principal": dict(principal), "name": name,
                           "arguments": dict(arguments)})
        return {"status": "completed", "answer": "확인했습니다."}


async def _dispatch(app, principal, name, arguments, *, executor=None):
    if executor is None:
        executor = RecordingExecutor()
    app.state.mcp_gateway_executor = executor
    request = request_for(app)
    outcome = await dispatch_mcp_tool(request, principal, name, arguments)
    return outcome, executor


def run_dispatch(app, principal, name, arguments, *, executor=None):
    return asyncio.run(_dispatch(app, principal, name, arguments, executor=executor))


# -- pc_devices: 목록과 온라인 표시 -------------------------------------------

def test_pc_devices_lists_linked_pcs_with_online_and_default_flags():
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store, online=[DEVICE_B])
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner), scope="all")
    outcome = asyncio.run(execute_mcp_pc_tool(
        request_for(app), principal, "pc_devices", {}))
    assert outcome["status"] == "completed"
    devices = outcome["devices"]
    assert [item["name"] for item in devices] == [LABEL_A, LABEL_B]
    by_name = {item["name"]: item for item in devices}
    assert by_name[LABEL_A]["online"] is False and by_name[LABEL_B]["online"] is True
    assert by_name[LABEL_A]["default"] is True and by_name[LABEL_B]["default"] is False
    assert by_name[LABEL_B]["id6"] and len(by_name[LABEL_B]["id6"]) == 6
    # 전체 기기 ID·메시 노드 ID는 어디에도 내려가지 않는다.
    blob = json.dumps(outcome)
    assert DEVICE_A not in blob and DEVICE_B not in blob


# -- device 생략: 기본 PC (하위 호환) -----------------------------------------

def test_omitted_device_keeps_the_token_default_pc():
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner))
    outcome, executor = run_dispatch(app, principal, "pc_list", {"path": "docs"})
    assert outcome["status"] == "completed"
    assert executor.calls[0]["principal"]["device_id"] == DEVICE_A


# -- 다른 PC 지정 성공 (표시 이름과 id6 모두) ----------------------------------

@pytest.mark.parametrize("picker", ["label", "id6"])
def test_a_chosen_linked_pc_replaces_the_target(picker):
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store, online=[DEVICE_B])
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner), scope="all")
    picker_value = LABEL_B if picker == "label" else "second"
    outcome, executor = run_dispatch(app, principal, "pc_list",
                                     {"path": "docs", "device": picker_value})
    assert outcome["status"] == "completed"
    assert executor.calls[0]["principal"]["device_id"] == DEVICE_B


# -- 다른 계정(미연결) PC 거절 -------------------------------------------------

def test_an_unlinked_device_is_refused_as_not_linked():
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner), scope="all")
    outcome, executor = run_dispatch(app, principal, "pc_list",
                                     {"path": "docs", "device": "node//not-mine"})
    assert outcome["status"] == "denied"
    assert outcome["code"] == "device_not_linked"
    assert executor.calls == []


def test_an_ambiguous_identifier_is_refused_not_guessed():
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store, devices=[
        (DEVICE_A, LABEL_A), (DEVICE_B, LABEL_B),
        ("node//studio-third", "third-pc-1"), ("node//studio-fourth", "third-pc-1"),
    ])
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner), scope="all")
    outcome, executor = run_dispatch(app, principal, "pc_list",
                                     {"path": "docs", "device": "third-pc-1"})
    assert outcome["status"] == "denied"
    assert outcome["code"] == "device_ambiguous"
    assert executor.calls == []


# -- 오프라인 거절: device_offline (기본 경로는 pc_offline 유지) ----------------

class _FakeChatPCDriveError(Exception):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _patch_lane(monkeypatch, *, offline, selected_device_id):
    from app import mcp_gateway_execution as execution

    async def fake_resolve_owner(request, uid):
        return SimpleNamespace(session_id="sess_1"), "sub_" + "1" * 32, "ws_1"

    async def fake_check_grant(request, session, *, device_id):
        return True

    async def fake_context(request, **kwargs):
        return SimpleNamespace(
            selection_offline=offline,
            selected_device_id=selected_device_id,
            selected_confirmed=True,
            tool_available=not offline,
            execution_device_id=kwargs.get("selected_device_id"),
        )

    monkeypatch.setattr(execution, "ChatPCDriveError", _FakeChatPCDriveError)
    monkeypatch.setattr(execution, "_resolve_chat_owner", fake_resolve_owner)
    monkeypatch.setattr(execution, "_check_mesh_grant", fake_check_grant)
    monkeypatch.setattr(execution, "resolve_pc_work_context", fake_context)


def test_a_chosen_offline_pc_refuses_with_device_offline(monkeypatch):
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    app.state.settings = SimpleNamespace(mcp_pc_shell_enabled=True)
    app.state.history_store = SimpleNamespace()
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner), scope="all")
    _patch_lane(monkeypatch, offline=True, selected_device_id=DEVICE_B)
    outcome = asyncio.run(execute_mcp_pc_tool(
        request_for(app), principal, "pc_shell",
        {"command": "Get-Date", "device": "second"}))
    assert outcome["status"] == "unavailable" and outcome["code"] == "device_offline"


def test_the_default_path_keeps_the_main_lane_offline_refusal(monkeypatch):
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    app.state.settings = SimpleNamespace(mcp_pc_shell_enabled=True)
    app.state.history_store = SimpleNamespace()
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner))
    _patch_lane(monkeypatch, offline=True, selected_device_id=DEVICE_A)
    outcome = asyncio.run(execute_mcp_pc_tool(
        request_for(app), principal, "pc_shell", {"command": "Get-Date"}))
    # device를 고르지 않은 호출의 오프라인 거절은 기존 pc_offline 코드 그대로 —
    # device_offline은 device를 명시한 호출에만 붙는다(하위 호환).
    assert outcome["status"] == "unavailable" and outcome["code"] == "pc_offline"


# -- 토큰 범위: selected 목록 밖 거절 · 레거시 단일 PC 하위 호환 ------------------

def test_out_of_scope_device_is_refused_for_a_selected_scope_token():
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    token_id = _issue_token(store, db, owner)
    principal = principal_for(owner, DEVICE_A, token_id, scope="selected",
                              scope_json=json.dumps([DEVICE_A]))
    outcome, executor = run_dispatch(app, principal, "pc_list",
                                     {"path": "docs", "device": LABEL_B})
    assert outcome["status"] == "denied"
    assert outcome["code"] == "device_not_in_token_scope"
    assert executor.calls == []


def test_a_legacy_single_pc_token_stays_bound_to_its_own_pc():
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    # device_scope NULL(레거시): 기본 PC는 통과, 다른 연결 PC는 범위 밖 거절.
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner))
    outcome, executor = run_dispatch(app, principal, "pc_list", {"path": "docs"})
    assert outcome["status"] == "completed"
    assert executor.calls[0]["principal"]["device_id"] == DEVICE_A
    outcome, executor = run_dispatch(app, principal, "pc_list",
                                     {"path": "docs", "device": LABEL_B})
    assert outcome["status"] == "denied"
    assert outcome["code"] == "device_not_in_token_scope"


# -- 작업 ID가 PC를 정한다: pc_shell의 device 인자는 대상 PC 선택에만 쓴다 ------
# (#6782 이후 읽기·중지는 공통 작업 영수증 경로로 옮겨갔다 — 이 파일의 shell
#  시나리오는 실행 대상 PC 선택과 오프라인 거절만 검증한다.)

# -- 감사: mcp_operation 로그가 대상 PC 끝 6자를 남긴다 -------------------------

def test_the_operation_log_names_the_target_pc_by_its_last_six(caplog, monkeypatch):
    from app.mcp_gateway_dispatch import _LOGGER
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner), scope="all")
    executor = RecordingExecutor()
    # 앱이 이 로거의 전파를 꺼 두었다 — 시험에서만 되연해 레코드를 읽는다.
    monkeypatch.setattr(_LOGGER, "propagate", True)
    with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
        run_dispatch(app, principal, "pc_list", {"path": "docs", "device": LABEL_B},
                     executor=executor)
    events = [record for record in caplog.records if record.getMessage().find("mcp_operation") >= 0]
    assert events, "the mcp_operation line must be written"
    payload = json.loads(events[-1].getMessage())
    assert payload["device"] == "second"
    assert DEVICE_B not in payload.get("device", "")
    # 감사 행도 대상 PC를 남긴다.
    rows = db.conn.execute(
        "SELECT device_id FROM padiem_mcp_audit ORDER BY created_at DESC LIMIT 1"
    ).fetchall()
    assert rows and rows[0][0] == DEVICE_B


# -- 동의 화면: 범위 선택이 토큰까지 저장된다 -----------------------------------

@pytest.mark.asyncio
async def test_consent_selected_scope_is_stored_on_the_token():
    db, owner, _other, store = setup()
    app = build_app(db)
    app.state.mcp_gateway_store = store
    app.state.pc_device_pairing_store = MultiPairing(
        owner, [(DEVICE_A, LABEL_A), (DEVICE_B, LABEL_B)])
    registered = await _register(client_for(app), name="Multi")
    client_id = registered["client_id"]
    import secrets as _secrets
    verifier = _secrets.token_urlsafe(48)
    params = _params(client_id, verifier)
    async with client_for(app) as owner_ui:
        owner_ui.cookies.update(session(app, owner))
        approved = await _approve(owner_ui, params, device_id=DEVICE_A)
        assert approved.status_code == 200, approved.text
        payload = {**params, "decision": "approve", "device_id": DEVICE_A,
                   "device_scope": "selected", "device_ids": [DEVICE_A]}
        selected = await owner_ui.post("/oauth/authorize", json=payload,
                                       headers={"Origin": BASE})
        assert selected.status_code == 200, selected.text
        code, _ = _code_from(selected.json()["redirect_url"])
    exchanged = await _exchange(client_for(app), client_id, code, verifier)
    assert exchanged.status_code == 200, exchanged.text
    tokens = exchanged.json()
    identity = await store.authenticate(tokens["access_token"])
    assert identity["device_scope"] == "selected"
    assert json.loads(identity["device_scope_json"]) == [DEVICE_A]
    # 범위 밖 PC 요청은 토큰 검증 이후의 선택 단계에서 거절된다.
    principal = principal_for(identity["user_id"], identity["device_id"],
                              identity["token_id"], scope=identity["device_scope"],
                              scope_json=identity["device_scope_json"])
    app2, _ = app_with(identity["user_id"], store,
                       devices=[(DEVICE_A, LABEL_A), (DEVICE_B, LABEL_B)])
    outcome, executor = await _dispatch(app2, principal, "pc_list",
                                        {"path": "docs", "device": LABEL_B})
    assert outcome["status"] == "denied"
    assert outcome["code"] == "device_not_in_token_scope"


@pytest.mark.asyncio
async def test_consent_defaults_to_all_pcs_when_the_field_is_absent():
    db, owner, _other, store = setup()
    app = build_app(db)
    app.state.mcp_gateway_store = store
    app.state.pc_device_pairing_store = MultiPairing(
        owner, [(DEVICE_A, LABEL_A), (DEVICE_B, LABEL_B)])
    registered = await _register(client_for(app), name="Multi")
    client_id = registered["client_id"]
    import secrets as _secrets
    verifier = _secrets.token_urlsafe(48)
    params = _params(client_id, verifier)
    async with client_for(app) as owner_ui:
        owner_ui.cookies.update(session(app, owner))
        approved = await _approve(owner_ui, params, device_id=DEVICE_A)
        assert approved.status_code == 200, approved.text
        code, _ = _code_from(approved.json()["redirect_url"])
    exchanged = await _exchange(client_for(app), client_id, code, verifier)
    assert exchanged.status_code == 200, exchanged.text
    identity = await store.authenticate(exchanged.json()["access_token"])
    assert identity["device_scope"] == "all"
    assert identity["device_scope_json"] is None
    # 'all' 범위 토큰은 다른 연결 PC도 고를 수 있다.
    principal = principal_for(identity["user_id"], identity["device_id"],
                              identity["token_id"], scope=identity["device_scope"],
                              scope_json=identity["device_scope_json"])
    app2, _ = app_with(identity["user_id"], store)
    outcome, executor = await _dispatch(app2, principal, "pc_list",
                                        {"path": "docs", "device": LABEL_B})
    assert outcome["status"] == "completed"
    assert executor.calls[0]["principal"]["device_id"] == DEVICE_B


# -- 마이그레이션: 멱등 적용 -----------------------------------------------------

def test_migration_100_is_idempotent_and_additive():
    import sqlite3
    from pathlib import Path

    sql = Path(__file__).resolve().parents[1] / "migrations" / "100_mcp_token_device_scope.sql"
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE padiem_mcp_tokens (id TEXT PRIMARY KEY, user_id TEXT, device_id TEXT);
        CREATE TABLE padiem_mcp_oauth_codes (code_sha256 TEXT PRIMARY KEY);
    """)
    db.executescript(sql.read_text(encoding="utf-8"))
    columns = {row[1] for row in db.execute("PRAGMA table_info(padiem_mcp_tokens)")}
    assert {"device_scope", "device_scope_json"} <= columns
    code_columns = {row[1] for row in db.execute("PRAGMA table_info(padiem_mcp_oauth_codes)")}
    assert {"device_scope", "device_scope_json"} <= code_columns
    # 같은 파일을 다시 적으면 IF NOT EXISTS가 아닌 ALTER라 실패해야 정상이다 —
    # D1·로컬 레저가 파일을 한 번만 적용하는 것이 계약이라. (원문 재적용 금지 확인)
    try:
        db.executescript(sql.read_text(encoding="utf-8"))
        reapplied = True
    except sqlite3.OperationalError:
        reapplied = False
    assert reapplied is False, "재적용이 조용히 통과하면 레저 이중 기록과 충돌한다"


# ── DC #586: 명시한 device로만 실행한다 — 조용한 폴백 금지 ────────────────────

def test_an_offline_chosen_pc_fails_even_when_the_default_pc_is_online(monkeypatch):
    """Desktop Commander #586: deviceId를 줬는데 다른 온라인 PC에서 실행된 사고.
    기본 PC가 온라인인 상태에서 선택 PC가 꺼져 있으면 device_offline으로
    명시 실패한다 — 기본 PC로 조용히 넘어가지 않는다."""
    db, owner, _other, store = setup()
    # 기본 PC(A)는 온라인, 선택 PC(B)는 오프라인 — 폴백의 조건이 완비된 상태.
    app, _ = app_with(owner, store, online=[DEVICE_A])
    app.state.settings = SimpleNamespace(mcp_pc_shell_enabled=True)
    app.state.history_store = SimpleNamespace()
    principal = principal_for(owner, DEVICE_A, _issue_token(store, db, owner), scope="all")
    _patch_lane(monkeypatch, offline=True, selected_device_id=DEVICE_B)
    outcome = asyncio.run(execute_mcp_pc_tool(
        request_for(app), principal, "pc_shell",
        {"command": "Get-Date", "device": "second"}))
    assert outcome["status"] == "unavailable" and outcome["code"] == "device_offline"


def test_an_out_of_scope_choice_fails_without_falling_back(monkeypatch):
    """범위 밖 PC를 고르면 device_not_in_token_scope로 거절한다 — 기본 PC가
    온라인이어도 실행 대상을 바꾸지 않는다(실행기 자체에 도달하지 않는다)."""
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store, online=[DEVICE_A, DEVICE_B])
    app.state.settings = SimpleNamespace(mcp_pc_shell_enabled=True)
    app.state.history_store = SimpleNamespace()
    token_id = _issue_token(store, db, owner, scope="selected",
                            scope_json=json.dumps([DEVICE_A]))
    principal = principal_for(owner, DEVICE_A, token_id, scope="selected",
                              scope_json=json.dumps([DEVICE_A]))
    outcome, executor = run_dispatch(app, principal, "pc_list",
                                     {"path": "docs", "device": "second"})
    assert outcome["status"] == "denied"
    assert outcome["code"] == "device_not_in_token_scope"
    assert executor.calls == [], "범위 밖 요청은 실행기에 도달해서는 안 된다"


# ── DC #599: 작업 ID 후속 호출은 그 작업을 만든 PC로 간다 ─────────────────────

SHELL_JOB_ID = "dsp_" + "b" * 32
SHELL_RUN_ID = "run_fixture"
SHELL_SUBJECT = "sub_" + "7" * 32
SHELL_TOKEN = "mcp_" + "f" * 32


class ShellJobHistory:
    """pc_shell_start가 PC-B(device 인자)에서 시작한 작업 행."""

    def __init__(self, owner):
        self.owner = owner

    def _row(self):
        raw = b"hello world"
        return {"dispatch_id": SHELL_JOB_ID, "user_id": self.owner,
                "device_id": DEVICE_B, "run_id": SHELL_RUN_ID,
                "kind": "command", "state": "pending", "claimed": True,
                "termination": None, "exit_code": None,
                "command_id": "oracle_mesh_cmd_" + "1" * 32,
                "revision_ref": "rev_1",
                "result_sha256": hashlib.sha256(raw).hexdigest(),
                "result_bytes": len(raw)}

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
        return self._row() if dispatch_id == SHELL_JOB_ID else None

    async def get_pc_output_dispatch_for_owner(self, *, user_id, dispatch_id):
        return await self.get_oracle_mesh_dispatch_for_owner(
            user_id=user_id, dispatch_id=dispatch_id)

    async def get_claw_run(self, user_id, run_id):
        return {"run_id": SHELL_RUN_ID, "conversation_id": "conv_fixture"}

    async def store_pc_output(self, **kwargs):
        assert kwargs["device_id"] == DEVICE_B, "출력은 작업의 PC에 귀속된다"
        return {"handle": "a" * 64, "size": len(kwargs["content"].encode("utf-8")),
                "truncated": False}

    async def read_pc_output(self, **kwargs):
        assert kwargs["device_id"] == DEVICE_B, "읽기도 작업의 PC로 간다"
        return {"handle": kwargs["handle"], "content": "hello world"}

    async def cancel_oracle_mesh_dispatches_for_run(self, *, user_id, run_id):
        assert (user_id, run_id) == (self.owner, SHELL_RUN_ID)
        return 1


class StartReceiptStore:
    """시작 호출(기본 PC가 아닌 PC-B)의 영수증만 소유로 인정한다."""

    def __init__(self, identity):
        self.identity = identity

    async def owns_job_receipt(self, *, identity, job_id):
        return (identity["user_id"] == self.identity["user_id"]
                and identity["token_id"] == self.identity["token_id"]
                and identity["device_id"] == self.identity["device_id"])


def _shell_request(app, receipts, owner):
    state = SimpleNamespace(history_store=ShellJobHistory(owner),
                            mcp_gateway_store=receipts)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_a_job_started_on_another_pc_is_read_and_stopped_by_its_id():
    """Desktop Commander #599: pc_shell_start를 기본이 아닌 PC(B)에서 시작하면,
    그 작업 ID의 pc_shell_read·pc_shell_stop은 B의 작업에 도달한다 — 호출의
    device 인자(기본 PC A)가 달라도 작업이 PC를 정한다."""
    from app.mcp_gateway_shell import execute_pc_shell_read, execute_pc_shell_stop

    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    start_identity = {"user_id": owner, "device_id": DEVICE_B, "token_id": SHELL_TOKEN}
    request = _shell_request(app, StartReceiptStore(start_identity), owner)
    # 호출자의 identity.device는 토큰 기본 PC(A) — 작업은 B에서 시작했다.
    read_identity = {"user_id": owner, "device_id": DEVICE_A, "token_id": SHELL_TOKEN}
    read = asyncio.run(execute_pc_shell_read(
        request, identity=read_identity, subject_id=SHELL_SUBJECT,
        arguments={"job_id": SHELL_JOB_ID, "device": LABEL_A}))
    assert read["status"] != "denied", read
    stop = asyncio.run(execute_pc_shell_stop(request, identity=read_identity,
                                             job_id=SHELL_JOB_ID))
    assert stop["status"] == "stopping", stop


def test_a_foreign_token_or_user_job_id_is_refused_with_ownership_error():
    from app.mcp_gateway_shell import execute_pc_shell_read, execute_pc_shell_stop

    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    start_identity = {"user_id": owner, "device_id": DEVICE_B, "token_id": SHELL_TOKEN}
    request = _shell_request(app, StartReceiptStore(start_identity), owner)
    for identity in (
            {"user_id": "usr_" + "d" * 32, "device_id": DEVICE_B, "token_id": SHELL_TOKEN},
            {"user_id": owner, "device_id": DEVICE_B, "token_id": "mcp_" + "0" * 32}):
        read = asyncio.run(execute_pc_shell_read(
            request, identity=identity, subject_id=SHELL_SUBJECT,
            arguments={"job_id": SHELL_JOB_ID}))
        stop = asyncio.run(execute_pc_shell_stop(request, identity=identity,
                                                 job_id=SHELL_JOB_ID))
        assert read["status"] == "denied" and stop["status"] == "denied"
        assert read["answer"] == "이 작업을 확인할 수 없습니다."
        assert stop["answer"] == "이 작업을 중지할 수 없습니다."


# ── #6801 핀: 저장된 Chat 선택과 무관하게 device가 실행 대상을 정한다 ──────────

def test_the_saved_screen_selection_does_not_block_a_chosen_device(monkeypatch):
    """저장된 Chat 선택이 컴1(A)이어도 device로 컴2(B)를 고르면 그 PC가 실행
    대상이 된다(#6801의 execution_device_id 핀 계약) — 저장 선택은 화면
    기본값일 뿐이다. 범위·링크·온라인·grant 검사는 그대로 통과해야 한다."""
    from app.orchestration_bridge import B62EngineOrchestrationBridge
    from padiem_ai_engine_client import PadiemAiEngineClient

    db, owner, _other, store = setup()
    app, _ = app_with(owner, store, online=[DEVICE_A, DEVICE_B])
    token_id = _issue_token(store, db, owner, scope="all")
    principal = principal_for(owner, DEVICE_A, token_id, scope="all")

    captured = []

    async def fake_context(request, **kwargs):
        captured.append(dict(kwargs))
        saved_selection = DEVICE_A  # Chat 화면에 저장된 선택(컴1)
        pin = kwargs.get("execution_device_id")
        return SimpleNamespace(
            selected_confirmed=True, tool_available=True,
            selection_offline=False,
            selected_device_id=saved_selection,
            execution_device_id=pin or saved_selection)

    async def owner(request, uid):
        return SimpleNamespace(session_id="sess_6801"), "sub_" + "6" * 32, "ws_6801"

    async def grant(request, session, **kwargs):
        return True

    async def delegation(request, uid):
        return {"version": 1, "rules": []}

    async def notice(*args, **kwargs):
        return True

    monkeypatch.setattr(execution_module, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution_module, "resolve_pc_work_context", fake_context)
    monkeypatch.setattr(execution_module, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution_module, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution_module, "_append_lane_notice", notice)
    transport = RecordingTransport()
    bridge = B62EngineOrchestrationBridge(client=PadiemAiEngineClient(
        transport=transport, app_id="padiem-chat", caller_id="padiem-chat",
        credential="fixture" * 8), store=object())
    app.state.orchestration_bridge = bridge
    app.state.history_store = RecordingHistory()

    # 실제 흐름대로 dispatch가 device를 해석해 principal.device_id를 바꾸고
    # execute에 넘긴다 — execute 단독 호출이면 해석이 생략된다.
    app.state.mcp_gateway_executor = execute_mcp_pc_tool
    outcome = asyncio.run(dispatch_mcp_tool(
        request_for(app), principal, "pc_list",
        {"path": "docs", "device": "second"}))
    assert outcome["status"] == "completed", outcome
    # 핀 인자에 선택 PC(컴2)가 전달됐고, 저장 선택(컴1)이 실행을 막지 않았다.
    assert captured[0]["execution_device_id"] == DEVICE_B
    assert captured[0]["selected_device_id"] == DEVICE_B
