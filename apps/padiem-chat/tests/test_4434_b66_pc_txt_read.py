"""#4434 B66 PC TXT: product-scoped dispatch + terminal result in B66 chat.

Load-bearing contract for the first real B66 PC slice:

* dispatch stages a run only for an existing B66 conversation and only with
  an explicit B66 ``file.read`` product grant (default-off fails closed);
* the server fixes the TXT root and mints the run id; the browser never does;
* the result leg only touches runs marked ``channel=b66`` / ``action=b66_txt_read``
  and only lands in the run's own B66 conversation after a ``task.result``
  grant check;
* no broker, device, or file secret ever leaves in a response.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from padiem_control_plane.local_agent_pc_access import (
    PcAccessOperation,
    ProductPcAccessGrant,
    ProductPcAccessPolicy,
)

import app.b66_pc_txt_read_routes as routes
from app.b66_pc_txt_read_routes import (
    B66_PC_RESULT_PATH,
    B66_PC_TXT_READ_PATH,
)

OWNER = "usr_4434_b66_pc_txt"
OTHER = "usr_4434_b66_pc_other"
WORKSPACE = "owner:" + OWNER
BASE = "https://chat.example.test"
CID = "chat_" + "c" * 32
RUN = "run_" + "d" * 24


class FakeHistory:
    def __init__(self):
        self.runs = {}
        self.marked = []

    async def record_claw_run(self, **kwargs):
        self.runs[kwargs["run_id"]] = dict(kwargs)
        self.runs[kwargs["run_id"]]["conversation_id"] = kwargs["conversation_id"]
        return None

    async def get_claw_run(self, user_id, run_id):
        row = self.runs.get(run_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return dict(row)

    async def update_claw_run_status(self, user_id, run_id, status, result_summary=None):
        self.marked.append((run_id, status))
        if run_id in self.runs:
            self.runs[run_id]["status"] = status
        return True


class FakeDialogueStore:
    async def list_recent(self, *args, **kwargs):
        return []

    async def search(self, *args, **kwargs):
        return []

    async def load(self, owner_id, conversation_id):
        if owner_id == OWNER and conversation_id == CID:
            return {"conversation_id": CID, "messages": []}
        return None

    async def delete(self, owner_id, conversation_id):
        return False


class FakeSource:
    configured = True

    def __init__(self, decision=None):
        self.decision = decision

    async def project_local_runner_result(self, **kwargs):
        return self.decision


def policy(*ops, workspace=WORKSPACE):
    return ProductPcAccessPolicy(grants=(
        ProductPcAccessGrant(
            product_id="b66", operations=frozenset(ops), workspace_ref=workspace,
        ),
    ))


def client(app_state, dispatch=None):
    app = Starlette(routes=[
        Route(B66_PC_TXT_READ_PATH, routes.b66_pc_txt_read_request, methods=["POST"]),
        Route(B66_PC_RESULT_PATH, routes.b66_pc_run_result, methods=["POST"]),
    ])
    for key, value in app_state.items():
        setattr(app.state, key, value)
    test = TestClient(app, base_url=BASE)
    if dispatch is not None:
        test.app.state  # keep TestClient portal state in sync
    return test


def base_state(history=None, member="off", ops=(PcAccessOperation.FILE_READ,)):
    state = {
        "b66_pc_access_policy": policy(*ops),
        "history_store": history or FakeHistory(),
        "b66_membership_enforced": member == "on",
        "b66_member_admin_store": _Members("approved" if member == "on" else None),
    }
    return state


class _Members:
    def __init__(self, status):
        self.status = status

    async def runtime_access(self, uid):
        assert uid == OWNER
        return {"status": self.status}


def dispatch_ok(body=None):
    async def run(request, wire):
        return JSONResponse({"ok": True, "command": {"command_id": "cmd_x", "run_id": wire["run_id"]}})
    return run


def test_request_requires_authentication(monkeypatch):
    history = FakeHistory()
    test = client({"b66_pc_access_policy": policy(PcAccessOperation.FILE_READ),
                   "history_store": history})
    monkeypatch.setattr(routes, "_owner", lambda request: None)
    response = test.post(B66_PC_TXT_READ_PATH, json={"conversation_id": CID, "path_relative": "a.txt"})
    assert response.status_code == 401
    assert history.runs == {}


def test_default_off_policy_dispatches_nothing(monkeypatch):
    history = FakeHistory()
    test = client({"b66_pc_access_policy": ProductPcAccessPolicy.default_off(),
                   "history_store": history})
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(routes, "b66_dialogue_store", lambda request: FakeDialogueStore())
    called = []
    async def fail_dispatch(request, wire):
        called.append(wire)
        raise AssertionError("must not dispatch without a grant")
    monkeypatch.setattr(routes, "dispatch_verified_txt_read", fail_dispatch)
    response = test.post(B66_PC_TXT_READ_PATH, json={"conversation_id": CID, "path_relative": "a.txt"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "b66_pc_txt_read_unavailable"
    assert called == [] and history.runs == {}


async def _no_member(request, uid):
    return None, None


async def _workspace(request, uid):
    return WORKSPACE


def test_invalid_shapes_are_refused_before_any_staging(monkeypatch):
    history = FakeHistory()
    test = client(base_state(history))
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(routes, "b66_dialogue_store", lambda request: FakeDialogueStore())
    monkeypatch.setattr(routes, "dispatch_verified_txt_read", dispatch_ok())
    bad = [
        {},
        {"conversation_id": "nope", "path_relative": "a.txt"},
        {"conversation_id": CID},
        {"conversation_id": CID, "path_relative": "a.pdf"},
        {"conversation_id": CID, "path_relative": "a.txt", "device_id": ""},
        {"conversation_id": CID, "path_relative": "a.txt", "owner": "mallory"},
    ]
    for payload in bad:
        response = test.post(B66_PC_TXT_READ_PATH, json=payload)
        assert response.status_code in (400, 422), payload
    assert history.runs == {}


def test_unknown_b66_conversation_is_not_found(monkeypatch):
    history = FakeHistory()
    test = client(base_state(history))
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(routes, "b66_dialogue_store", lambda request: FakeDialogueStore())
    monkeypatch.setattr(routes, "dispatch_verified_txt_read", dispatch_ok())
    response = test.post(B66_PC_TXT_READ_PATH,
                         json={"conversation_id": "chat_" + "e" * 32, "path_relative": "a.txt"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"
    assert history.runs == {}


def test_exact_grant_stages_b66_run_and_dispatches_server_fixed_root(monkeypatch):
    history = FakeHistory()
    test = client(base_state(history))
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(routes, "b66_dialogue_store", lambda request: FakeDialogueStore())
    seen = {}

    async def ok(request, wire):
        seen.update(wire)
        return JSONResponse({"ok": True, "command": {"command_id": "cmd_1", "run_id": wire["run_id"]}})

    monkeypatch.setattr(routes, "dispatch_verified_txt_read", ok)
    response = test.post(B66_PC_TXT_READ_PATH,
                         json={"conversation_id": CID, "path_relative": "memo.txt"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["conversation_id"] == CID
    assert body["run_id"].startswith("run_")
    # The browser never chooses the TXT root, the run id or the approval wire.
    assert seen["root_ref"] == "root.3140"
    assert seen["run_id"] == body["run_id"]
    assert seen["confirmed"] is True
    row = history.runs[body["run_id"]]
    assert row["conversation_id"] == CID
    assert row["channel"] == "b66" and row["action"] == "b66_txt_read"
    assert row["status"] == "pending"
    assert "DO_NOT_LEAK" not in response.text and "PRIVATE" not in response.text


def test_dispatch_failure_marks_run_failed_and_passes_error_through(monkeypatch):
    history = FakeHistory()
    test = client(base_state(history))
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(routes, "b66_dialogue_store", lambda request: FakeDialogueStore())

    async def denied(request, wire):
        return JSONResponse({"ok": False, "error": {"code": "txt_read_no_usable_device"}},
                            status_code=409)

    monkeypatch.setattr(routes, "dispatch_verified_txt_read", denied)
    response = test.post(B66_PC_TXT_READ_PATH,
                         json={"conversation_id": CID, "path_relative": "memo.txt"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "txt_read_no_usable_device"
    assert history.marked and history.marked[0][1] == "failed"


def test_result_requires_task_result_grant(monkeypatch):
    history = FakeHistory()
    test = client(base_state(history, ops=(PcAccessOperation.FILE_READ,)))
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    response = test.post("/api/b66/runs/" + RUN + "/pc-result")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "b66_pc_result_unavailable"


def test_result_rejects_non_b66_run_without_disclosure(monkeypatch):
    history = FakeHistory()
    history.runs[RUN] = {"user_id": OWNER, "run_id": RUN, "status": "completed",
                         "conversation_id": CID, "workspace_id": WORKSPACE,
                         "channel": "web", "action": "txt_read"}
    state = base_state(history, ops=(PcAccessOperation.TASK_RESULT,))
    state["local_task_result_source"] = FakeSource({"appended": True, "status": "x", "reason": "y"})
    test = client(state)
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(routes, "b66_dialogue_store", lambda request: FakeDialogueStore())
    response = test.post("/api/b66/runs/" + RUN + "/pc-result")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


def test_result_workspace_mismatch_is_a_conflict(monkeypatch):
    history = FakeHistory()
    history.runs[RUN] = {"user_id": OWNER, "run_id": RUN, "status": "completed",
                         "conversation_id": CID, "workspace_id": "owner:other",
                         "channel": "b66", "action": "b66_txt_read"}
    state = base_state(history, ops=(PcAccessOperation.TASK_RESULT,))
    test = client(state)
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    response = test.post("/api/b66/runs/" + RUN + "/pc-result")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "b66_pc_run_workspace_mismatch"


def test_result_projects_into_the_origin_b66_conversation(monkeypatch):
    history = FakeHistory()
    history.runs[RUN] = {"user_id": OWNER, "run_id": RUN, "status": "completed",
                         "conversation_id": CID, "workspace_id": WORKSPACE,
                         "channel": "b66", "action": "b66_txt_read"}
    decision = {"appended": True, "status": "completed", "reason": "terminal observation",
                "runId": RUN, "commandId": "cmd_9"}
    state = base_state(history, ops=(PcAccessOperation.TASK_RESULT,))
    state["local_task_result_source"] = FakeSource(decision)
    test = client(state)
    monkeypatch.setattr(routes, "_owner", lambda request: OWNER)
    monkeypatch.setattr(routes, "_member_access", _no_member)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(routes, "b66_dialogue_store", lambda request: FakeDialogueStore())
    response = test.post("/api/b66/runs/" + RUN + "/pc-result")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["conversation_id"] == CID
    assert body["status"] == "completed" and body["appended"] is True


def test_routes_are_registered_in_the_worker_app():
    from app.app_factory import create_app
    from app.config import Settings
    from app.b66_pc_txt_read_routes import B66_PC_TXT_READ_PATH, B66_PC_RESULT_PATH

    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password",
        public_base_url=BASE,
        session_secret="4434-b66-pc-txt-read-route-secret",
        session_max_age_seconds=3600,
        b66_quote_base_url="https://quote.example.test",
    )
    app = create_app(settings=settings, history_store=MagicMock())
    table = {(getattr(item, "path", ""), frozenset(item.methods or ()))
             for item in app.routes if hasattr(item, "methods")}
    assert (B66_PC_TXT_READ_PATH, frozenset({"POST"})) in table
    assert (B66_PC_RESULT_PATH, frozenset({"POST"})) in table
