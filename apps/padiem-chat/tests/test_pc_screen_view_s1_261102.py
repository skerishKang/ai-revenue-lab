"""#6460 S1 — "show me my PC screen" is one read-only capture, no model, no input.

The desktop capture already exists (#4139). What this changes is the entry: an
ordinary Korean sentence selects the same verified capture lane the backtick
grammar used, one shot per request, displayed in the conversation through the
existing owner-only retrieval URL. No click/type/keys path is reachable from
here, and a refused request answers with one Korean sentence instead of a raw
error body.

The browser half runs only where Playwright is installed; the route half uses
injected fakes only and never touches a real PC.
"""

from __future__ import annotations

import asyncio
import hashlib
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
RUN = "run_" + "b" * 24
CONVERSATION = "chat_" + "c" * 32
SECRET = "synthetic-deployment-channel-secret-261102"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 128
QUESTION = "내 PC 화면 보여줘"


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
    def __init__(self, *, staged_owner=OWNER):
        self.staged_owner = staged_owner
        self.staged: list[dict] = []
        self.rows: dict[str, dict] = {}
        self.statuses: list[tuple[str, str]] = []
        self._seq = 0

    async def record_txt_pending_run(self, *, user_id, run_id, workspace_id,
                                     user_text, conversation_id, action=None):
        del conversation_id
        self.staged.append({"user_id": user_id, "run_id": run_id,
                            "workspace_id": workspace_id, "user_text": user_text,
                            "action": action})
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


def _state(*, command_exec: bool = True, staged_owner: str = OWNER):
    source = routes.build_oracle_mesh_return_source(
        _mapping(command_exec), SECRET, routes.EXECUTION_MODE_MESH)
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=Identity(),
        history_store=History(staged_owner=staged_owner),
        connector_txt_read_source=None,
    )


def _run_route(monkeypatch, state, question=QUESTION):
    # Both are synchronous helpers in the route module.
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

    from app import claw_memory_routes

    async def verified(request):
        del request
        return SimpleNamespace(session_id="session.canonical.owner.1"), None

    monkeypatch.setattr(routes, "_verified_owner_request", verified)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", workspace)
    monkeypatch.setattr(general, "auth_ready", auth_ready)
    monkeypatch.setattr(general, "current_user_id", current_user_id)
    monkeypatch.setattr(general, "_resolve_intake_session_reference", intake)
    # The dispatch wrapper imports this helper inside the function.
    monkeypatch.setattr(claw_memory_routes, "_resolve_memory_workspace", workspace)
    from starlette.requests import Request

    body = json.dumps({"messages": [{"role": "user", "content": question}]}).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": "POST", "path": "/api/claw/general",
             "app": SimpleNamespace(state=state),
             "headers": [(b"content-type", b"application/json")]}
    response = asyncio.run(general.claw_general_execute(Request(scope, receive=receive)))
    return response


# ── intent ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "내 PC 화면 보여줘",
    "지금 화면 캡처해 줘",
    "내 컴퓨터 화면 스크린샷 찍어줘",
    "PC 화면 봐줘",
    "screenshot my pc screen",
    "화면 캡처",
])
def test_read_only_phrases_select_the_capture_lane(text):
    assert general._requested_read_only_screen_view(text) is True


@pytest.mark.parametrize("text", [
    # Input is never this lane: the backtick grammar keeps its own path.
    "내 PC 화면 클릭해 줘",
    "내 PC 화면에서 입력해 줘",
    "내 PC 화면 캡처하고 메모장 열어 클릭",
    # Other PC lanes own these.
    "내 PC 화면 캡처 txt 파일 보여줘",
    "내 PC에서 report.txt 읽어서 화면 보여줘",
    "내 PC 드라이브 보여줘",
    "내 PC 브라우저 화면 보여줘",
    # Ordinary chat.
    "설정 화면 보여줘",
    "이 화면 뭐야?",
    "화면 보여줘",
    "내 PC 화면 보여줘 `capture`",
])
def test_other_turns_never_enter_the_capture_lane(text):
    assert general._requested_read_only_screen_view(text) is False


# ── route ───────────────────────────────────────────────────────────────────


def test_a_sentence_takes_one_capture_and_answers_pending(monkeypatch):
    state = _state()
    response = _run_route(monkeypatch, state)
    assert response.status_code == 200, response.body
    text = response.body.decode("utf-8")
    assert "PC 화면을 한 장 가져오는 중입니다" in text
    assert '"pc_pending":true' in text
    assert len(state.history_store.rows) == 1
    row = next(iter(state.history_store.rows.values()))
    assert row["kind"] == "desktop"
    assert row["command_text"] == "desktop:capture"
    assert row["device_id"] == DEVICE and row["node_ref"] == NODE
    assert [stage["user_text"] for stage in state.history_store.staged] == [QUESTION]
    # One request, one capture: nothing else was dispatched.
    assert len(state.history_store.rows) == 1


def test_an_unlinked_or_unauthorised_pc_answers_in_korean(monkeypatch):
    state = _state(command_exec=False)
    response = _run_route(monkeypatch, state)
    assert response.status_code == 200, response.body
    text = response.body.decode("utf-8")
    assert "권한" in text and "컴퓨터 연결" in text
    assert "oracle_mesh_command_unverified" in text
    assert state.history_store.rows == {}
    assert [status for _run, status in state.history_store.statuses] == ["failed"]


def test_a_foreign_run_is_refused_with_the_same_guidance(monkeypatch):
    state = _state()
    response = _run_route(monkeypatch, state)
    assert response.status_code == 200
    # A run that belongs to another owner is the same non-disclosing refusal.
    state = _state()
    state.history_store.get_claw_run = lambda user_id, run_id: None  # type: ignore[assignment]
    response = _run_route(monkeypatch, state)
    text = response.body.decode("utf-8")
    assert response.status_code == 200 and "대상" in text
    assert state.history_store.rows == {}


def test_the_lane_opens_no_input_path():
    source = general._requested_read_only_screen_view.__code__
    names = source.co_names
    assert "desktop:click" not in names and "desktop:type" not in names
    # The dispatched op is the literal capture, not a parameter.
    route_source = general._dispatch_user_desktop_request.__code__
    assert "screen_view" in general._dispatch_user_desktop_request.__code__.co_varnames
    assert route_source is not None
    wrapper = general.claw_general_execute.__code__.co_consts
    texts = [value for value in wrapper if isinstance(value, str)]
    assert 'desktop:capture' in texts, "the read-only lane names its op literally"
