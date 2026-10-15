"""#4139 narrow Claw conversation entry and canonical pending history checks."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from starlette.responses import JSONResponse

from app import claw_general_routes as general
from app import connector_txt_read_routes as connector
from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT
from test_claw_local_task_result_projection import _accounts, _open_database


def run(coro):
    return asyncio.run(coro)


def test_user_pc_txt_intent_is_narrow_and_does_not_use_model():
    wanted, relative = general._requested_local_txt_path("내 PC의 notes/report.txt 읽어줘")
    assert wanted is True and relative == "notes/report.txt"
    assert general._requested_local_txt_path("내 PC의 notes/report.pdf 읽어줘") == (False, None)
    assert general._requested_local_txt_path("친구가 보낸 report.txt 읽어줘") == (False, None)
    assert general._requested_local_txt_path("내 PC의 a.txt b.txt 읽어줘") == (True, None)


def test_pending_history_binds_original_owner_conversation_without_success(tmp_path):
    history = D1HistoryStore(_open_database(tmp_path / "chat.sqlite3"))
    accounts = _accounts(history)
    owner = next(value for key, value in accounts.items() if "owner" in key)
    run_id = "run_" + "f" * 24
    cid = run(history.record_txt_pending_run(
        user_id=owner, run_id=run_id, workspace_id="tenant.ws.1",
        user_text="내 PC의 notes/report.txt 읽어줘", conversation_id=None,
    ))
    row = run(history.get_claw_run(owner, run_id))
    assert row["status"] == "pending"
    assert row["conversation_id"] == cid and row["workspace_id"] == "tenant.ws.1"
    conversation = run(history.get_conversation(owner, cid, product_scope=PRODUCT_SCOPE_CHAT))
    assert conversation is not None
    assert [message["role"] for message in conversation["messages"]] == ["user"]
    assert run(history.get_claw_run("foreign", run_id)) is None


def test_one_registered_device_auto_target_multi_requires_chooser(monkeypatch):
    async def auth(request):
        return SimpleNamespace(session_id="session.owner"), None
    monkeypatch.setattr(connector, "_verified_owner_request", auth)

    class Identity:
        async def resolve_connector_owner_scope(self, *, session_id):
            assert session_id == "session.owner"
            return {"account_ref": "account.canonical", "workspace_ref": "workspace.canonical"}

    class Broker:
        def __init__(self, names):
            self.names = names
            self.profiles = []
        async def owner_device_directory(self, *, account_ref, workspace_ref):
            assert (account_ref, workspace_ref) == ("account.canonical", "workspace.canonical")
            return {"available": True, "devices": [
                {"canonical_state": "paired_offline", "binding": {
                    "device_id": name, "binding_ref": "binding." + name,
                    "account_ref": account_ref, "workspace_ref": workspace_ref,
                }} for name in self.names
            ]}
        async def resolve_device_binding(self, *, account_ref, workspace_ref, device_id):
            assert device_id in self.names
            return {"binding_ref": "binding." + device_id}
        async def installed_txt_execution_profile(self, **kwargs):
            self.profiles.append(kwargs)
            return r"C:\Python313\python.exe"

    broker = Broker(["pc1"])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=Identity(),
        connector_txt_read_source=broker,
    )))
    device_id, denial = run(connector.choose_verified_txt_device(request))
    assert (device_id, denial) == ("pc1", None)
    assert broker.profiles[0]["device_id"] == "pc1"

    broker.names = ["pc1", "pc2"]
    device_id, denial = run(connector.choose_verified_txt_device(request))
    assert device_id is None and denial.status_code == 409
    assert b"txt_read_device_selection_required" in denial.body
    device_id, denial = run(connector.choose_verified_txt_device(
        request, selected_device_id="pc2",
    ))
    assert device_id == "pc2" and denial is None


def test_absent_installed_profile_fails_closed_before_pending_history(monkeypatch):
    async def auth(request):
        return SimpleNamespace(session_id="session.owner"), None
    monkeypatch.setattr(connector, "_verified_owner_request", auth)

    class Identity:
        async def resolve_connector_owner_scope(self, *, session_id):
            return {"account_ref": "account.canonical", "workspace_ref": "workspace.canonical"}

    class Broker:
        async def owner_device_directory(self, **kwargs):
            return {"available": True, "devices": [{
                "canonical_state": "paired_offline",
                "binding": {"device_id": "pc1", "binding_ref": "binding.pc1",
                            "account_ref": "account.canonical",
                            "workspace_ref": "workspace.canonical"},
            }]}
        async def resolve_device_binding(self, **kwargs):
            return {"binding_ref": "binding.pc1"}
        async def installed_txt_execution_profile(self, **kwargs):
            raise RuntimeError("LOCAL2 supply is absent")

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=Identity(),
        connector_txt_read_source=Broker(),
    )))
    device_id, denial = run(connector.choose_verified_txt_device(request))
    assert device_id is None and denial.status_code == 503
    assert b"txt_read_execution_profile_unavailable" in denial.body

def test_real_claw_general_entry_uses_existing_enqueue_without_model(monkeypatch):
    import json
    from starlette.requests import Request
    from app import claw_memory_routes
    from app import connector_txt_read_routes as route

    async def auth(request):
        return SimpleNamespace(session_id="session.owner"), None
    async def tenant(request, uid):
        assert uid == "owner1"
        return "tenant.ws1"
    async def authorized_session(request, data):
        return None, None

    monkeypatch.setattr(route, "_verified_owner_request", auth)
    monkeypatch.setattr(route, "_resolve_memory_workspace", tenant)
    monkeypatch.setattr(claw_memory_routes, "_resolve_memory_workspace", tenant)
    monkeypatch.setattr(general, "_resolve_intake_session_reference", authorized_session)
    monkeypatch.setattr(general, "auth_ready", lambda r: True)
    monkeypatch.setattr(general, "current_user_id", lambda r: "owner1")
    monkeypatch.setattr(route, "current_user_id", lambda r: "owner1")

    class Identity:
        async def resolve_connector_owner_scope(self, *, session_id):
            return {"account_ref": "canonical.account", "workspace_ref": "canonical.workspace"}
        async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
            return {"consent_id": "consent.pc1", "device_id": device_id,
                    "account_ref": "canonical.account", "workspace_ref": "canonical.workspace",
                    "withdrawn_at": None}
        async def resolve_connector_workspace(self, *, session_id):
            return "canonical.workspace"

    class Broker:
        configured = True
        def __init__(self):
            self.enqueued = []
        async def owner_device_directory(self, *, account_ref, workspace_ref):
            return {"available": True, "devices": [{
                "canonical_state": "paired_offline",
                "binding": {"account_ref": account_ref,
                            "workspace_ref": workspace_ref,
                            "binding_ref": "binding.pc1", "device_id": "pc1"},
            }]}
        async def resolve_device_binding(self, **kwargs):
            return {"binding_ref": "binding.pc1", "credential_generation": 1,
                    "device_id": "pc1"}
        async def installed_txt_execution_profile(self, **kwargs):
            return r"C:\Python313\python.exe"
        async def enqueue_txt_read_command(self, *, command, material):
            self.enqueued.append((command, material))
            return {"command_id": command["command_id"],
                    "revision_ref": "revision.pc1",
                    "request_fingerprint": command["request_fingerprint"]}

    class History:
        def __init__(self):
            self.rows = {}
            self.correlations = []
        async def record_txt_pending_run(self, *, user_id, run_id, workspace_id,
                                         user_text, conversation_id):
            assert user_id == "owner1" and workspace_id == "tenant.ws1"
            assert user_text == "내 PC notes/report.txt 읽어줘"
            self.rows[run_id] = {"run_id": run_id, "conversation_id": "conv.txt",
                                 "workspace_id": workspace_id, "status": "pending"}
            return "conv.txt"
        async def get_claw_run(self, user_id, run_id):
            return self.rows.get(run_id)
        async def record_local_task_correlation(self, **kwargs):
            self.correlations.append(kwargs)
        async def update_claw_run_status(self, user_id, run_id, status):
            self.rows[run_id]["status"] = status

    broker = Broker()
    history = History()
    app = SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=Identity(),
        connector_txt_read_source=broker, history_store=history,
    ))
    body = json.dumps({"messages": [{"role": "user", "content":
                                  "내 PC notes/report.txt 읽어줘"}]}).encode("utf-8")
    scope = {"type": "http", "method": "POST", "path": "/api/claw/general",
             "app": app, "headers": [(b"content-type", b"application/json")]}
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    response = run(general.claw_general_execute(Request(scope, receive=receive)))
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert b"event: done" in response.body
    assert len(broker.enqueued) == 1
    command, material = broker.enqueued[0]
    assert material["argv"] == [r"C:\Python313\python.exe", "-V"]
    assert material["root_ref"] == "root.3140"
    assert material["p01_approval_payload"]["exact_tool_arguments"]["path_relative"] == "notes\\report.txt"
    assert len(history.correlations) == 1
    assert history.correlations[0]["command_id"] == command["command_id"]
    assert history.rows[command["run_id"]]["status"] == "pending"
