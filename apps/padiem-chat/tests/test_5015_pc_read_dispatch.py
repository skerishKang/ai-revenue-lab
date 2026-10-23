"""#5015: Chat PC read_file stages the existing kind=read download lane.

The list tool stays on the PowerShell command lane. The read tool must stage a
kind=read dispatch, carry the server-computed 1 MB bound to the executor, and
return the verified raw body through the existing result store/route. No live
Mesh, Identity or Broker is involved.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes

OWNER = "usr_" + "a" * 32
SUBJECT = "sub_" + "b" * 32
ACCOUNT = "account-1"
WORKSPACE = "connector-ws-1"
RUN = "chat_pcq_" + "c" * 24
CONVERSATION = "chat_" + "d" * 32
DEVICE = "device-1"
NODE = "node-1"
SECRET = "s" * 32
CHANNEL_SECRET = "u" * 32
ROOT = "C:/Users/limone/AppData/Local/PADIEM/MeshCentralTrial"
READ_CALL = RUN + ":read_file:" + "a" * 24
LIST_CALL = RUN + ":list_files:" + "b" * 24
READ_BODY = "PADIEM FILE BODY\nEND_OF_FILE\n"
READ_MARKER = routes.PC_FILES_ERROR_PREFIX + "too_large"


def _mapping():
    return [{
        "account_ref": ACCOUNT, "device_id": DEVICE, "node_ref": NODE,
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "file_path": ROOT + "/meshcentral-padiem-trial.txt",
        "command_exec": True,
    }]


class _Identity:
    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == "b62"
        assert canonical_subject_id == SUBJECT
        return OWNER

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        assert product_id == "b62"
        assert product_user_id == OWNER
        return SimpleNamespace(
            session_id="sess-5015", product_id="b62",
            subject=SimpleNamespace(subject_id=SUBJECT),
            tenant_id=WORKSPACE, is_active=lambda *, now: True,
        )

    async def resolve_connector_owner_scope(self, *, session_id):
        assert session_id == "sess-5015"
        return {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE}


class _History:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.originals: dict[str, bytes] = {}
        self.message_ids: dict[str, str] = {}
        self._seq = 0
        self.scopes = {}

    async def get_pc_run_scope(self, *, user_id, run_id):
        return self.scopes.get((user_id, run_id))

    async def pin_pc_run_scope(self, *, user_id, run_id, claim):
        key = (user_id, run_id)
        if key in self.scopes and self.scopes[key] != claim:
            raise routes.HistoryForbidden("fixed")
        self.scopes[key] = dict(claim)

    async def get_claw_run(self, user_id, run_id):
        if user_id != OWNER or run_id != RUN:
            return None
        return {
            "run_id": RUN, "conversation_id": CONVERSATION,
            "workspace_id": WORKSPACE, "status": "pending",
        }

    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return None

    async def create_oracle_mesh_dispatch(self, **fields):
        self._seq += 1
        dispatch_id = "dsp-%d" % self._seq
        row = {
            **fields, "dispatch_id": dispatch_id, "state": "pending",
            "nonce_sha256": None, "result_sha256": None, "result_bytes": None,
            "termination": None, "exit_code": None,
        }
        self.rows[dispatch_id] = row
        return dict(row)

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return dict(row)

    async def oldest_pending_oracle_mesh_dispatch(self):
        for row in self.rows.values():
            if row.get("state") == "pending" and row.get("nonce_sha256") is None:
                return dict(row)
        return None

    async def claim_oracle_mesh_dispatch(self, *, dispatch_id, nonce_sha256):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("state") != "pending" or row.get("nonce_sha256") is not None:
            return False
        row["nonce_sha256"] = nonce_sha256
        return True

    async def read_oracle_mesh_original(
        self, *, user_id, dispatch_id, conversation_id, message_id,
    ):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        self.message_ids[dispatch_id] = message_id
        data = self.originals.get(dispatch_id)
        if data is None:
            return None
        return data, hashlib.sha256(data).hexdigest()


class _SignedRequest:
    def __init__(self, state, payload, *, secret=SECRET, scope=None):
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        stamp = str(int(time.time()))
        proof = hmac.new(
            secret.encode("utf-8"), stamp.encode("ascii") + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        self.app = SimpleNamespace(state=state)
        self.headers = {
            "X-Claw-Engine-Time": stamp,
            "X-Claw-Engine-Proof": proof,
        }
        self._raw = raw
        if scope is not None:
            encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"))
            self.headers["X-Claw-PC-Scope"] = encoded
            self.headers["X-Claw-PC-Scope-Proof"] = hmac.new(
                secret.encode(), stamp.encode() + b"." + raw + b"." + encoded.encode(),
                hashlib.sha256,
            ).hexdigest()

    async def body(self):
        return self._raw


async def _workspace(request, uid):
    return WORKSPACE if uid == OWNER else None


def _state(monkeypatch, history=None):
    import padiem_control_plane.b54_identity_bridge as bridge

    identity = _Identity()
    session = SimpleNamespace(
        session_id="sess-5015", product_id="b62",
        subject=SimpleNamespace(subject_id=SUBJECT),
        tenant_id=WORKSPACE, is_active=lambda *, now: True,
    )

    async def fake_bridge(_identity, uid):
        assert uid == OWNER
        return SimpleNamespace(auth_session=session)

    monkeypatch.setattr(bridge, "resolve_current_b54_canonical_session", fake_bridge)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)
    source = routes.build_oracle_mesh_return_source(
        _mapping(), CHANNEL_SECRET, routes.EXECUTION_MODE_MESH,
    )
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=identity,
        history_store=history or _History(),
        claw_engine_desktop_secret=SECRET,
    )


def _dispatch(state, payload):
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(
        _SignedRequest(state, payload),
    ))
    return response.status_code, json.loads(response.body)


def _base_payload(**overrides):
    payload = {
        "subject_id": SUBJECT, "run_id": RUN, "device_id": None,
        "op": "list", "path": ".", "tool_call_ref": LIST_CALL,
        "mode": "dispatch",
    }
    payload.update(overrides)
    return payload


def _pending_read_row(*, tool_request_ref=READ_CALL):
    return {
        "dispatch_id": "dsp-read", "user_id": OWNER, "run_id": RUN,
        "kind": "read", "command_id": "oracle_mesh_cmd_read",
        "tool_request_ref": tool_request_ref, "request_id": "req",
        "revision_ref": "rev", "evidence_ref": None,
        "request_fingerprint": "f" * 64, "account_ref": ACCOUNT,
        "workspace_ref": WORKSPACE, "device_id": DEVICE, "binding_ref": None,
        "node_ref": NODE, "root_ref": routes._PC_FILES_READ_ROOT_REF,
        "path_relative": "notes.txt", "file_path": ROOT + "/notes.txt",
        "nonce_sha256": None, "state": "pending",
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "result_sha256": None, "result_bytes": None,
        "termination": None, "exit_code": None,
    }


# --------------------------------------------------------------- dispatch
def test_list_stays_command_and_read_stages_kind_read(monkeypatch):
    state = _state(monkeypatch)

    status, body = _dispatch(state, _base_payload())
    assert status == 200, body
    assert body["dispatch"]["kind"] == "command"
    listed = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert listed["kind"] == "command"
    assert "Get-ChildItem -LiteralPath" in listed["command_text"]
    assert listed["tool_call_ref"] == LIST_CALL

    status, body = _dispatch(state, _base_payload(
        op="read", path="notes.txt", tool_call_ref=READ_CALL,
    ))
    assert status == 200, body
    assert body["dispatch"]["kind"] == "read"
    read = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert read["kind"] == "read"
    assert read.get("command_text") is None
    assert read["node_ref"] == NODE
    assert read["device_id"] == DEVICE
    assert read["root_ref"] == routes._PC_FILES_READ_ROOT_REF
    assert read["path_relative"] == "notes.txt"
    assert read["file_path"] == ROOT + "/notes.txt"
    assert read["tool_request_ref"] == READ_CALL
    assert ":read_file:" in read["tool_request_ref"]


def test_the_read_bound_is_not_a_caller_or_model_field(monkeypatch):
    state = _state(monkeypatch)
    status, body = _dispatch(state, _base_payload(
        op="read", path="notes.txt", tool_call_ref=READ_CALL,
        max_bytes=5_000_000,
    ))
    assert status == 400
    assert body["error"]["code"] == "claw_engine_files_invalid_body"
    assert state.history_store.rows == {}


# ------------------------------------------------------------------- poll
def _poll(state, *, secret=CHANNEL_SECRET):
    request = SimpleNamespace(
        app=SimpleNamespace(state=state),
        headers={routes.ORACLE_MESH_CHANNEL_HEADER: secret},
    )
    response = asyncio.run(routes.oracle_mesh_read_poll(request))
    return response.status_code, json.loads(response.body)


def test_poll_sends_one_mb_for_the_chat_read_and_six_mb_for_other_reads(
    monkeypatch,
):
    history = _History()
    state = _state(monkeypatch, history=history)

    history.rows["dsp-read"] = _pending_read_row()
    status, body = _poll(state)
    assert status == 200, body
    assert body["dispatch"]["kind"] == "read"
    assert body["dispatch"]["max_bytes"] == routes.PC_FILES_READ_MAX_BYTES
    assert body["dispatch"]["max_bytes"] == 1_000_000

    # A browser/other read consumer has no PC-files marker and keeps 6 MB.
    other = _pending_read_row(tool_request_ref="oracle_mesh_tool_" + "e" * 24)
    other["dispatch_id"] = "dsp-other"
    other["root_ref"] = "meshcentral_private_trial"
    history.rows["dsp-other"] = other
    status, body = _poll(state)
    assert status == 200, body
    assert body["dispatch"]["dispatch_id"] == "dsp-other"
    assert body["dispatch"]["max_bytes"] == 6_000_000


def test_the_server_root_decides_the_bound_not_the_caller_reference():
    row = _pending_read_row(tool_request_ref="opaque-call-ref")
    assert routes._oracle_mesh_poll_max_bytes(row) == 1_000_000

    row.pop("root_ref")
    assert routes._oracle_mesh_poll_max_bytes(row) == 6_000_000


def test_poll_still_rejects_a_wrong_channel_secret(monkeypatch):
    state = _state(monkeypatch)
    state.history_store.rows["dsp-read"] = _pending_read_row()
    status, body = _poll(state, secret="not-the-channel-secret")
    assert status == 403
    assert body["error"]["code"] == "oracle_mesh_channel_rejected"


# ----------------------------------------------------------------- result
def _seed_result(state, *, state_name, exit_code, body_bytes, termination):
    dispatch = _pending_read_row()
    dispatch.update({
        "state": state_name,
        "result_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "result_bytes": len(body_bytes),
        "termination": termination, "exit_code": exit_code,
    })
    state.history_store.rows["dsp-read"] = dispatch
    state.history_store.originals["dsp-read"] = body_bytes
    return dispatch


def test_read_result_returns_the_exact_raw_bytes_and_sha(monkeypatch):
    state = _state(monkeypatch)
    _seed_result(
        state, state_name="done", exit_code=0,
        body_bytes=READ_BODY.encode("utf-8"), termination="exited",
    )
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": "dsp-read",
        "mode": "result",
    })
    assert status == 200, body
    row = body["dispatch"]
    assert row["kind"] == "read"
    assert row["output"] == READ_BODY
    assert row["content_sha256"] == hashlib.sha256(
        READ_BODY.encode("utf-8")
    ).hexdigest()
    assert row["content_bytes"] == len(READ_BODY.encode("utf-8"))
    assert row["termination"] == "exited"
    assert row["exit_code"] == 0
    assert state.history_store.message_ids["dsp-read"] == routes.result_message_id(
        conversation_id=CONVERSATION,
        command_id="oracle_mesh_cmd_read", revision_ref="rev",
    )


def test_failed_read_result_still_returns_the_marker_body(monkeypatch):
    state = _state(monkeypatch)
    _seed_result(
        state, state_name="failed", exit_code=1,
        body_bytes=READ_MARKER.encode("utf-8"), termination="exited",
    )
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": "dsp-read",
        "mode": "result",
    })
    assert status == 200, body
    assert body["dispatch"]["kind"] == "read"
    assert body["dispatch"]["state"] == "failed"
    assert body["dispatch"]["output"] == READ_MARKER
    assert body["dispatch"]["exit_code"] == 1


def test_command_result_mode_keeps_its_done_only_contract(monkeypatch):
    state = _state(monkeypatch)
    dispatch = _pending_read_row()
    dispatch.update({
        "kind": "command", "state": "failed", "termination": "exited",
        "exit_code": 1, "result_sha256": hashlib.sha256(b"x").hexdigest(),
        "result_bytes": 1,
    })
    state.history_store.rows["dsp-read"] = dispatch
    state.history_store.originals["dsp-read"] = b"x"
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": "dsp-read",
        "mode": "result",
    })
    assert status == 409
    assert body["error"]["code"] == "oracle_mesh_result_not_ready"

def test_read_result_store_bound_is_one_mb_for_pc_files_and_six_mb_otherwise():
    oversized = "x" * (routes.PC_FILES_READ_MAX_BYTES + 1)
    raw = oversized.encode("utf-8")
    wire = {
        "content_utf8": oversized,
        "content_bytes": len(raw),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert routes._verified_read_result_text(
        {"root_ref": routes._PC_FILES_READ_ROOT_REF}, wire,
    ) is None
    assert routes._verified_read_result_text(
        {"root_ref": "other-read-lane"}, wire,
    ) == oversized


def _scope_claim(plan="files_list"):
    return {"version": 1, "requested": plan, "admitted": plan,
            "source": "declared", "ops": ["list"] if plan == "files_list" else ["list", "read"],
            "app_id": "padiem-chat"}


def _scoped_dispatch(state, payload, claim):
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(
        _SignedRequest(state, payload, scope=claim),
    ))
    return response.status_code, json.loads(response.body)


def test_list_ceiling_refuses_kind_read_at_the_real_dispatch_boundary(monkeypatch):
    state = _state(monkeypatch)
    claim = _scope_claim()
    status, body = _scoped_dispatch(state, _base_payload(), claim)
    assert status == 200 and body["dispatch"]["kind"] == "command"
    status, body = _scoped_dispatch(state, _base_payload(
        op="read", path="notes.txt", tool_call_ref=READ_CALL), claim)
    assert status == 403 and body["error"]["code"] == "pc_scope_denied"
    assert [row["kind"] for row in state.history_store.rows.values()] == ["command"]
    assert state.history_store.scopes[(OWNER, RUN)] == claim


def test_scope_cannot_widen_or_downgrade_to_the_legacy_wire(monkeypatch):
    state = _state(monkeypatch)
    assert _scoped_dispatch(state, _base_payload(), _scope_claim())[0] == 200
    read = _base_payload(op="read", path="notes.txt", tool_call_ref=READ_CALL)
    status, body = _scoped_dispatch(state, read, _scope_claim("files"))
    assert status == 403 and body["error"]["code"] == "pc_scope_frozen"
    status, body = _dispatch(state, read)
    assert status == 403 and body["error"]["code"] == "pc_scope_required"
    assert [row["kind"] for row in state.history_store.rows.values()] == ["command"]


def test_new_chat_accepts_old_engine_wire_with_all_original_guards(monkeypatch):
    state = _state(monkeypatch)
    read = _base_payload(op="read", path="notes.txt", tool_call_ref=READ_CALL)
    request = _SignedRequest(state, read)
    assert "X-Claw-PC-Scope" not in request.headers
    assert "X-Claw-PC-Scope-Proof" not in request.headers
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    assert response.status_code == 200
    assert json.loads(response.body)["dispatch"]["kind"] == "read"
    state = _state(monkeypatch)
    status, body = _dispatch(state, {**read, "path": "../outside.txt"})
    assert status == 422 and state.history_store.rows == {}


def test_scope_proof_binds_claim_to_the_exact_signed_body(monkeypatch):
    state = _state(monkeypatch)
    request = _SignedRequest(state, _base_payload(), scope=_scope_claim())
    request.headers["X-Claw-PC-Scope"] = json.dumps(_scope_claim("files"))
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "pc_scope_proof_invalid"
    assert state.history_store.rows == {}


def test_full_ceiling_keeps_read_and_server_target_path_checks(monkeypatch):
    state = _state(monkeypatch)
    read = _base_payload(op="read", path="notes.txt", tool_call_ref=READ_CALL)
    status, body = _scoped_dispatch(state, read, _scope_claim("files"))
    assert status == 200 and body["dispatch"]["kind"] == "read"
    state = _state(monkeypatch)
    assert _scoped_dispatch(state, {**read, "path": "../outside.txt"}, _scope_claim("files"))[0] == 422
    assert state.history_store.rows == {}
    assert _scoped_dispatch(state, {**read, "device_id": "foreign-pc"}, _scope_claim("files"))[0] == 403
    assert state.history_store.rows == {}
