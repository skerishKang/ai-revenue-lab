"""#6460 — plain-language single desktop action, pre-delegated (#3782).

The desktop input transport already existed. This lane adds the ordinary
sentence in front of it, for the two actions a sentence fully determines: one
reviewed key combo, or one click at coordinates the owner wrote. Everything
else — typing free text, actions that need the screen, the model loop — is not
guessed here.

Owner direction (2026-11-02, 사업방침 04·06 / 운영방침 00): highest authority is
the default, no per-action consent button, the server re-verifies owner, device
and the command grant on every send. Four families are still asked once in the
conversation: credential entry, account/permission changes, irreversible
destruction and anything that sends outside the PC.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import claw_general_routes as general
from app import oracle_mesh_read_return_routes as routes

OWNER = "usr_" + "a" * 32
ACCOUNT = "account-oracle-1"
CONNECTOR_WS = "connector-ws-1"
TENANT_WS = "tenant-ws-1"
DEVICE = "device-oracle-1"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
CONVERSATION = "chat_" + "c" * 32
SECRET = "synthetic-deployment-channel-secret-261102"


def _mapping(command_exec: bool = True) -> list[dict]:
    row = {
        "account_ref": ACCOUNT, "device_id": DEVICE, "node_ref": NODE,
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "file_path": "C:\\work\\meshcentral-padiem-trial.txt",
    }
    if command_exec:
        row["command_exec"] = True
    return [row]


class Identity:
    async def resolve_connector_owner_scope(self, *, session_id):
        del session_id
        return {"account_ref": ACCOUNT, "workspace_ref": CONNECTOR_WS}


class History:
    def __init__(self):
        self.staged: list[dict] = []
        self.rows: dict[str, dict] = {}
        self.statuses: list[tuple[str, str]] = []
        self._seq = 0

    async def record_txt_pending_run(self, *, user_id, run_id, workspace_id,
                                     user_text, conversation_id, action=None):
        del conversation_id
        self.staged.append({"run_id": run_id, "user_text": user_text, "action": action})
        return CONVERSATION

    async def get_claw_run(self, user_id, run_id):
        staged = any(stage["run_id"] == run_id for stage in self.staged)
        if user_id != OWNER or not staged:
            return None
        return {"run_id": run_id, "conversation_id": CONVERSATION,
                "workspace_id": TENANT_WS, "status": "waiting"}

    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return None

    async def create_oracle_mesh_dispatch(self, **fields):
        self._seq += 1
        dispatch_id = "dsp-" + str(self._seq)
        row = {**fields, "dispatch_id": dispatch_id, "state": "pending"}
        self.rows[dispatch_id] = row
        return dict(row)

    async def update_claw_run_status(self, user_id, run_id, status):
        self.statuses.append((run_id, status))
        return True


def _state(*, command_exec: bool = True):
    source = routes.build_oracle_mesh_return_source(
        _mapping(command_exec), SECRET, routes.EXECUTION_MODE_MESH)
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=Identity(),
        history_store=History(),
        connector_txt_read_source=None,
    )


def _run(monkeypatch, state, question):
    def auth_ready(request):
        del request
        return True

    def current_user_id(request):
        del request
        return OWNER

    async def intake(request, data):
        del request, data
        return CONVERSATION, None

    async def workspace(request, uid):
        del request, uid
        return TENANT_WS

    async def verified(request):
        del request
        return SimpleNamespace(session_id="session.canonical.owner.1"), None

    from app import claw_memory_routes

    monkeypatch.setattr(general, "auth_ready", auth_ready)
    monkeypatch.setattr(general, "current_user_id", current_user_id)
    monkeypatch.setattr(general, "_resolve_intake_session_reference", intake)
    monkeypatch.setattr(claw_memory_routes, "_resolve_memory_workspace", workspace)
    monkeypatch.setattr(routes, "_verified_owner_request", verified)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", workspace)

    from starlette.requests import Request

    body = json.dumps({"messages": [{"role": "user", "content": question}]}).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": "POST", "path": "/api/claw/general",
             "app": SimpleNamespace(state=state),
             "headers": [(b"content-type", b"application/json")]}
    return asyncio.run(general.claw_general_execute(Request(scope, receive=receive)))


# ── what the sentence can select ────────────────────────────────────────────


@pytest.mark.parametrize("text,op", [
    ("내 PC 화면 960,540 클릭해 줘", "desktop:click\n960,540"),
    ("내 PC에서 800, 450 눌러 줘", "desktop:click\n800,450"),
    ("내 PC에서 엔터 눌러 줘", "desktop:keys\nenter"),
    ("내 PC에 ctrl+s 눌러 줘", "desktop:keys\nctrl+s"),
    ("내 PC에서 esc 키 눌러 줘", "desktop:keys\nesc"),
    ("내 PC에서 붙여넣기 해 줘", "desktop:keys\nctrl+v"),
])
def test_plain_sentences_select_exactly_one_reviewed_action(text, op):
    assert general._requested_desktop_control(text) == (True, op)


@pytest.mark.parametrize("text", [
    # Typing free text is not this lane (the audited row would keep the text).
    "내 PC에서 메모장 열고 안녕 입력해 줘",
    "내 PC에 타이핑해 줘",
    # Read-only capture belongs to the existing view lane.
    "내 PC 화면 보여줘",
    "내 PC 화면 캡처해 줘",
    # Combos outside the reviewed set, and the other PC lanes.
    "내 PC에서 alt+f4 눌러 줘",
    "내 PC에서 win+r 눌러 줘",
    "내 PC 브라우저에서 클릭해 줘",
    "내 PC 파일 목록 보여줘",
    "내 PC 화면 960,540 클릭해 줘 `capture`",
    "창 닫아 줘",
])
def test_everything_else_stays_out_of_the_single_action_lane(text):
    assert general._requested_desktop_control(text) == (False, None)


# ── the four exceptions are asked once, in the conversation ────────────────


@pytest.mark.parametrize("text", [
    # Each would otherwise be a plain click the lane sends without a button.
    "내 PC에서 비밀번호 칸 960,540 클릭해 줘",
    "내 PC에서 카드번호 칸 700,420 눌러 줘",
    "내 PC에서 계정 변경 800,300 클릭해 줘",
    "내 PC에서 파일 삭제 720,380 눌러 줘",
    "내 PC에서 메일 보내기 640,500 클릭해 줘",
    "내 PC에서 게시 900,620 눌러 줘",
])
def test_exception_families_are_asked_not_run(monkeypatch, text):
    state = _state()
    question = general._desktop_exception_question(text)
    assert question and "바로 실행하지 않았습니다" in question
    response = _run(monkeypatch, state, text)
    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "바로 실행하지 않았습니다" in body
    # Nothing was staged, dispatched or sent to the PC.
    assert state.history_store.rows == {} and state.history_store.staged == []


def test_an_ordinary_action_never_asks_and_never_logs_a_secret(monkeypatch):
    state = _state()
    response = _run(monkeypatch, state, "내 PC 화면 960,540 클릭해 줘")
    body = response.body.decode("utf-8")
    assert response.status_code == 200
    assert "보내는 중입니다" in body and '"pc_pending":true' in body
    row = next(iter(state.history_store.rows.values()))
    assert row["kind"] == "desktop"
    assert row["command_text"] == "desktop:click\n960,540"
    # The stored row carries the op and its two coordinates — no free text.
    assert "비밀번호" not in json.dumps(row, ensure_ascii=False)


def test_a_refused_grant_still_answers_in_korean(monkeypatch):
    state = _state(command_exec=False)
    response = _run(monkeypatch, state, "내 PC에서 엔터 눌러 줘")
    body = response.body.decode("utf-8")
    assert response.status_code == 200
    assert "권한" in body and "oracle_mesh_command_unverified" in body
    assert state.history_store.rows == {}
    assert [status for _run_id, status in state.history_store.statuses] == ["failed"]
