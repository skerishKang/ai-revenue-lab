"""#6460 step 2 — typed text that never rests in the record, and open key combos.

The audit row names a typed value only by length, digest prefix and an
unguessable reference; the value is deposited once and taken once by the
executor that claimed that dispatch. These tests use injected fakes only: no
real PC, no real queue, no real browser.
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
CONVERSATION = "chat_" + "c" * 32
SECRET = "synthetic-deployment-channel-secret-261102"
TYPED = "안녕하세요 🙂\n둘째 줄"


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
        self.staged.append({"run_id": run_id, "user_text": user_text})
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


class QueueClient:
    """The one declared store door the Chat side is allowed to use."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method, **arguments):
        self.calls.append((method, arguments))
        if self.fail:
            raise RuntimeError("queue unreachable")
        return True


def _state(*, command_exec: bool = True, queue_client=None):
    source = routes.build_oracle_mesh_return_source(
        _mapping(command_exec), SECRET, routes.EXECUTION_MODE_MESH)
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=Identity(),
        history_store=History(),
        connector_txt_read_source=None,
        queue_client=queue_client,
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


# ── recognition ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("메모장에 '안녕하세요' 입력해 줘", "안녕하세요"),
    ("내 PC에서 “둘째 줄\n셋째 🙂” 입력해 줘", "둘째 줄\n셋째 🙂"),
    ("'영문 text 123' 입력해 줘", "영문 text 123"),
])
def test_a_quoted_value_selects_typing(text, expected):
    matched, op = general._requested_desktop_control(text)
    assert matched is True
    assert op == "desktop:type\n" + expected


@pytest.mark.parametrize("text", [
    "지금 커서 위치에 주소 입력해 줘",   # no value in the sentence
    "내 PC 화면 보여줘",
    "내 PC 파일 목록에서 'x' 입력해 줘",
])
def test_unquoted_or_other_lanes_stay_out(text):
    assert general._requested_desktop_control(text) == (False, None)


def test_a_credential_request_is_asked_before_anything_is_typed(monkeypatch):
    state = _state(queue_client=QueueClient())
    response = _run(monkeypatch, state, "내 PC에서 비밀번호 'abcd1234' 입력해 줘")
    body = response.body.decode("utf-8")
    assert "바로 실행하지 않았습니다" in body
    assert state.history_store.rows == {} and state.history_store.staged == []
    assert state.queue_client.calls == []


# ── the value never lands in the record ─────────────────────────────────────


def test_the_value_is_deposited_once_and_the_row_only_names_it(monkeypatch):
    client = QueueClient()
    state = _state(queue_client=client)
    response = _run(monkeypatch, state, "내 PC에서 '안녕하세요 🙂\n둘째 줄' 입력해 줘")
    body = response.body.decode("utf-8")
    assert response.status_code == 200 and "보내는 중입니다" in body
    # One deposit, with the exact value, under an unguessable reference.
    assert len(client.calls) == 1
    method, arguments = client.calls[0]
    assert method == "deposit_desktop_text"
    assert arguments["text"] == "안녕하세요 🙂\n둘째 줄"
    ref = arguments["ref"]
    assert isinstance(ref, str) and len(ref) == 32
    # The audit row carries the marker, never the value.
    row = next(iter(state.history_store.rows.values()))
    digest = hashlib.sha256("안녕하세요 🙂\n둘째 줄".encode("utf-8")).hexdigest()[:8]
    assert row["command_text"] == "desktop:type\n#%d:%s:%s" % (
        len("안녕하세요 🙂\n둘째 줄"), digest, ref)
    assert "안녕하세요" not in json.dumps(row, ensure_ascii=False)
    assert "안녕하세요" not in body
    # The stored user sentence keeps the request and loses the value.
    staged_text = state.history_store.staged[0]["user_text"]
    assert "안녕하세요" not in staged_text and "…" in staged_text
    # Exactly one dispatch for one request.
    assert len(state.history_store.rows) == 1


def test_without_a_safe_channel_nothing_is_sent_or_recorded(monkeypatch):
    state = _state(queue_client=QueueClient(fail=True))
    response = _run(monkeypatch, state, "내 PC에서 '안녕하세요' 입력해 줘")
    body = response.body.decode("utf-8")
    assert "안전하게 보내는 통로" in body
    assert state.history_store.rows == {}
    assert [status for _run_id, status in state.history_store.statuses] == ["failed"]
    assert "안녕하세요" not in body


# ── the poll hands it over exactly once ────────────────────────────────────


class TextStore:
    def __init__(self, value):
        self.value = value
        self.taken: list[str] = []

    async def take_desktop_text(self, *, ref):
        self.taken.append(ref)
        value, self.value = self.value, None
        return value


class PendingHistory:
    """The one row the poll is allowed to claim."""

    def __init__(self, command_text, ref):
        self.row = {
            "dispatch_id": "dsp_" + "a" * 32, "expires_at": "2099-01-01T00:00:00Z",
            "node_ref": NODE, "file_path": "C:\\work\\x.txt", "account_ref": ACCOUNT,
            "device_id": DEVICE, "binding_ref": None, "root_ref": "root",
            "path_relative": "x.txt", "command_id": "cmd", "run_id": "run",
            "tool_request_ref": "ref", "request_id": "req", "revision_ref": "rev",
            "evidence_ref": None, "request_fingerprint": "fp",
            "kind": "desktop", "command_text": command_text,
        }
        self.ref = ref
        self.claimed = False

    async def oldest_pending_oracle_mesh_dispatch(self):
        return None if self.claimed else dict(self.row)

    async def claim_oracle_mesh_dispatch(self, *, dispatch_id, nonce_sha256):
        del dispatch_id, nonce_sha256
        if self.claimed:
            return False
        self.claimed = True
        return True


def _poll(state):
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    headers = [("content-type", "application/json")]
    if state.oracle_mesh_return_source is not None:
        headers.append((routes.ORACLE_MESH_CHANNEL_HEADER, SECRET))
    request = Request({"type": "http", "method": "POST", "path": routes.ORACLE_MESH_READ_POLL_PATH,
                       "app": SimpleNamespace(state=state), "headers": [
                           (name.lower().encode(), value.encode()) for name, value in headers]})
    return asyncio.run(routes.oracle_mesh_read_poll(request))


def test_the_claim_carries_the_value_once_and_then_it_is_gone():
    ref = "b" * 32
    command_text = "desktop:type\n#5:abc12345:" + ref
    store = TextStore("안녕")
    state = SimpleNamespace(
        oracle_mesh_return_source=routes.build_oracle_mesh_return_source(
            _mapping(), SECRET, routes.EXECUTION_MODE_MESH),
        history_store=PendingHistory(command_text, ref),
        desktop_text_store=store,
    )
    first = json.loads(_poll(state).body)["dispatch"]
    assert first["command_text"] == command_text
    assert first["desktop_text"] == "안녕"
    assert store.taken == [ref]
    # A second claim has no row left; nothing stale can be typed twice.
    second = json.loads(_poll(state).body)
    assert second["dispatch"] is None
