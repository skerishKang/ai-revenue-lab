"""Shared PC file-read dispatch test fixtures (#5015)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app import oracle_mesh_read_return_routes as routes

OWNER = "usr_" + "a" * 32

SUBJECT = "sub_" + "b" * 32

ACCOUNT = "account-1"

WORKSPACE = "connector-ws-1"

RUN = "chat_pcq_" + "c" * 24

CONVERSATION = "chat_" + "d" * 32

DEVICE = "device-1"

NODE = "node-1"

SECOND_NODE = "node-2"

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
        self.status_writes: list[tuple[str, str, str]] = []
        self.run_rows = {
            RUN: {
                "run_id": RUN, "user_id": OWNER, "conversation_id": CONVERSATION,
                "workspace_id": WORKSPACE, "status": "pending",
                "result_summary": None,
            },
        }
        self._seq = 0
        self.scopes = {}

    async def update_claw_run_status(
        self, user_id, run_id, status, result_summary=None,
    ):
        """Mirror of the guarded D1 settle (#2961), write-for-write.

        Owner + run id address the row, a completed row is never reopened and a
        summary-free call never blanks the run's own terminal summary.
        """
        self.status_writes.append((user_id, run_id, status))
        row = self.run_rows.get(run_id)
        if row is None or row["user_id"] != user_id or row["status"] == "completed":
            return False
        row["status"] = status
        if result_summary is not None:
            row["result_summary"] = result_summary
        return True

    async def get_pc_run_scope(self, *, user_id, run_id):
        return self.scopes.get((user_id, run_id))

    async def pin_pc_run_scope(self, *, user_id, run_id, claim):
        key = (user_id, run_id)
        if key in self.scopes and self.scopes[key] != claim:
            raise routes.HistoryForbidden("fixed")
        self.scopes[key] = dict(claim)

    async def get_claw_run(self, user_id, run_id):
        row = self.run_rows.get(run_id)
        if user_id != OWNER or row is None:
            return None
        return dict(row)

    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return None

    async def create_oracle_mesh_dispatch(self, **fields):
        self._seq += 1
        dispatch_id = "dsp-%d" % self._seq
        row = {
            **fields, "dispatch_id": dispatch_id, "state": "pending",
            # The production SELECT answers the mode for every row.
            "user_mode": 1 if fields.get("user_mode") is True else 0,
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

    async def get_pc_output_dispatch_for_owner(self, *, user_id, dispatch_id):
        return await self.get_oracle_mesh_dispatch_for_owner(
            user_id=user_id, dispatch_id=dispatch_id,
        )

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

class _OwnerLinks:
    def __init__(self, links):
        self._links = list(links)

    async def links_for_owner(self, *, user_id):
        return list(self._links) if user_id == OWNER else []

def _owner_link(node, root_path=ROOT):
    return {
        "mesh_node_id": node, "label": "PC", "state": "active",
        "roots": [{
            "root_ref": "pcroot_test", "label": "MeshCentralTrial",
            "path": root_path, "state": "active",
        }],
    }

def _legacy_mapping():
    rows = _mapping()
    rows[0]["account_ref"] = "legacy-account"
    return rows

def _state(monkeypatch, history=None, *, mapping=None, links=None):
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
        mapping if mapping is not None else _mapping(),
        CHANNEL_SECRET, routes.EXECUTION_MODE_MESH,
    )
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=identity,
        history_store=history or _History(),
        claw_engine_desktop_secret=SECRET,
        pc_device_pairing_store=_OwnerLinks(links) if links is not None else None,
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
        # The production SELECT answers the mode for every row.
        "user_mode": 0,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "result_sha256": None, "result_bytes": None,
        "termination": None, "exit_code": None,
    }

def _context_payload(**overrides):
    payload = {"subject_id": SUBJECT, "run_id": RUN, "device_id": None, "mode": "context"}
    payload.update(overrides)
    return payload
