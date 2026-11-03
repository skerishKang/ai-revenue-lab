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

from test_mcp_gateway_account import DEVICE as DEVICE_A, setup, client_for, session
from test_5222_account_model_selection import BASE, build_app
from test_mcp_oauth_261103 import (
    RESOURCE, REDIRECT, _approve, _code_from, _exchange, _params, _register,
)

DEVICE_B = "node//studio-second"
LABEL_A = "사무실 PC"
LABEL_B = "작업실 PC"
NOW = datetime.now(timezone.utc)


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
        return {"device_id": device_id, "connected": True, "source": "mesh",
                "credential_generation": None,
                "received_at": (NOW - timedelta(seconds=10)).isoformat()}


def app_with(owner, store, *, devices=None, online=()):
    app = build_app(store.db if hasattr(store, "db") else None)
    app.state.mcp_gateway_store = store
    pairing = MultiPairing(owner, devices or [(DEVICE_A, LABEL_A), (DEVICE_B, LABEL_B)])
    app.state.pc_device_pairing_store = pairing
    app.state.mesh_device_presence_store = Presence(online)
    return app, pairing



def _issue_token(store, owner, device_id=DEVICE_A, *, scope=None, scope_json=None):
    """실제 토큰 행을 발급한다 — 감사 FK가 토큰 행을 요구한다."""
    token = asyncio.run(store.issue_token(user_id=owner, device_id=device_id, name="시험 AI"))
    if scope is not None:
        asyncio.run(store.db.prepare(
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
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner), scope="all")
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
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner))
    outcome, executor = run_dispatch(app, principal, "pc_list", {"path": "docs"})
    assert outcome["status"] == "completed"
    assert executor.calls[0]["principal"]["device_id"] == DEVICE_A


# -- 다른 PC 지정 성공 (표시 이름과 id6 모두) ----------------------------------

@pytest.mark.parametrize("picker", ["label", "id6"])
def test_a_chosen_linked_pc_replaces_the_target(picker):
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store, online=[DEVICE_B])
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner), scope="all")
    picker_value = LABEL_B if picker == "label" else "second"
    outcome, executor = run_dispatch(app, principal, "pc_list",
                                     {"path": "docs", "device": picker_value})
    assert outcome["status"] == "completed"
    assert executor.calls[0]["principal"]["device_id"] == DEVICE_B


# -- 다른 계정(미연결) PC 거절 -------------------------------------------------

def test_an_unlinked_device_is_refused_as_not_linked():
    db, owner, _other, store = setup()
    app, _ = app_with(owner, store)
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner), scope="all")
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
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner), scope="all")
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
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner), scope="all")
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
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner))
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
    token_id = _issue_token(store, owner)
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
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner))
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
    principal = principal_for(owner, DEVICE_A, _issue_token(store, owner), scope="all")
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
