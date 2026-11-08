"""2026-11-09: the dispatch workspace seam is pinned on both sides.

Defect: the engine files lane resolved its dispatch workspace only through
the memory shadow pointer (``control_plane_identity_shadow``). That pointer is
a non-authoritative local cache; when its session was rotated or expired the
dispatch was refused ``503 oracle_mesh_workspace_unavailable`` even though the
canonical authority had already answered for the very session in the request.
The PC lane (``chat_pc_drive._resolve_chat_owner``) already fell back to the
verified session's tenant; the engine lane kept hard-failing on the pointer.

This module pins the Chat side of the seam (the workspace one dispatch is
staged under, and the exact wire code on refusal). The Engine side of the same
wire code — ``oracle_mesh_workspace_unavailable`` -> the reviewed bounded
stage ``pc_files_workspace_unavailable`` — is pinned in
``apps/padiem-ai-engine/tests/test_5015_pc_query_step_driver.py``'s
``test_signed_pc_files_callback_retains_only_reviewed_failure_stage``. Keep
the two pairs in step: a rename on either side is a broken contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

from app import oracle_mesh_read_return_routes as routes

OWNER = "usr_" + "a" * 32
SUBJECT = "sub_" + "b" * 32
ACCOUNT = "account-1"
WORKSPACE = "connector-ws-1"
MEMORY_WORKSPACE = "memory-ws-1"
RUN = "chat_pcq_" + "c" * 24
CONVERSATION = "chat_" + "d" * 32
DEVICE = "device-1"
NODE = "node-1"
SECRET = "s" * 32
CHANNEL_SECRET = "u" * 32
ROOT = "C:/Users/limone/AppData/Local/PADIEM/MeshCentralTrial"
LIST_CALL = RUN + ":list_files:" + "b" * 24
READ_CALL = RUN + ":read_file:" + "a" * 24

WIRE_REFUSAL_CODE = "oracle_mesh_workspace_unavailable"


class _StaleShadowError(Exception):
    """The production refusal shape: a stale pointer is not ``not_linked``."""

    code = "control_plane_session_mismatch"


def _mapping():
    return [{
        "account_ref": ACCOUNT, "device_id": DEVICE, "node_ref": NODE,
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "file_path": ROOT + "/meshcentral-padiem-trial.txt",
        "command_exec": True,
    }]


class _Identity:
    def __init__(self, session):
        self._session = session

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == "b62"
        assert canonical_subject_id == SUBJECT
        return OWNER

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        assert product_id == "b62"
        assert product_user_id == OWNER
        return self._session

    async def resolve_connector_owner_scope(self, *, session_id):
        return {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE}


class _History:
    def __init__(self, *, run_workspace):
        self.rows = {}
        self._seq = 0
        self.run_rows = {
            RUN: {
                "run_id": RUN, "user_id": OWNER, "conversation_id": CONVERSATION,
                "workspace_id": run_workspace, "status": "pending",
                "result_summary": None,
            },
        }

    async def get_claw_run(self, user_id, run_id):
        row = self.run_rows.get(run_id)
        if user_id != OWNER or row is None:
            return None
        return dict(row)

    async def get_local_task_correlation(self, user_id, run_id):
        return None

    async def get_pc_run_scope(self, *, user_id, run_id):
        return None

    async def pin_pc_run_scope(self, *, user_id, run_id, claim):
        return None

    async def create_oracle_mesh_dispatch(self, **fields):
        self._seq += 1
        dispatch_id = "dsp-%d" % self._seq
        row = {
            **fields, "dispatch_id": dispatch_id, "state": "pending",
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

    async def read_oracle_mesh_original(
        self, *, user_id, dispatch_id, conversation_id, message_id,
    ):
        return None


class _SignedRequest:
    def __init__(self, state, payload):
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        stamp = str(int(time.time()))
        proof = hmac.new(
            SECRET.encode("utf-8"), stamp.encode("ascii") + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        self.app = SimpleNamespace(state=state)
        self.headers = {
            "X-Claw-Engine-Time": stamp,
            "X-Claw-Engine-Proof": proof,
        }
        self._raw = raw

    async def body(self):
        return self._raw


def _session(*, tenant_id=WORKSPACE):
    return SimpleNamespace(
        session_id="sess-seam", product_id="b62",
        subject=SimpleNamespace(subject_id=SUBJECT),
        tenant_id=tenant_id, is_active=lambda *, now: True,
    )


def _state(monkeypatch, session, history, memory_workspace):
    import padiem_control_plane.b54_identity_bridge as bridge

    async def fake_bridge(_identity, uid):
        assert uid == OWNER
        return SimpleNamespace(auth_session=session)

    async def memory(request, uid):
        if isinstance(memory_workspace, Exception):
            raise memory_workspace
        return memory_workspace

    monkeypatch.setattr(bridge, "resolve_current_b54_canonical_session", fake_bridge)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", memory)
    source = routes.build_oracle_mesh_return_source(
        _mapping(), CHANNEL_SECRET, routes.EXECUTION_MODE_MESH,
    )
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=_Identity(session),
        history_store=history,
        claw_engine_desktop_secret=SECRET,
        pc_device_pairing_store=None,
    )


def _dispatch(state, payload):
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(
        _SignedRequest(state, payload),
    ))
    return response.status_code, json.loads(response.body)


def _payload(**overrides):
    payload = {
        "subject_id": SUBJECT, "run_id": RUN, "device_id": None,
        "op": "list", "path": ".", "tool_call_ref": LIST_CALL,
        "mode": "dispatch",
    }
    payload.update(overrides)
    return payload


def test_engine_dispatch_stages_when_the_shadow_pointer_is_stale(monkeypatch):
    """A stale memory shadow pointer must not refuse a dispatch the canonical
    session (the one this request already verified) can underwrite."""
    session = _session(tenant_id=WORKSPACE)
    history = _History(run_workspace=WORKSPACE)
    state = _state(monkeypatch, session, history, _StaleShadowError())

    status, body = _dispatch(state, _payload())
    assert status == 200, body
    assert body["dispatch"]["kind"] == "command"
    assert history.rows[body["dispatch"]["dispatch_id"]]["tool_call_ref"] == LIST_CALL

    status, body = _dispatch(state, _payload(
        op="read", path="notes.txt", tool_call_ref=READ_CALL,
    ))
    assert status == 200, body
    assert body["dispatch"]["kind"] == "read"
    row = history.rows[body["dispatch"]["dispatch_id"]]
    assert row["tool_request_ref"] == READ_CALL
    assert row["path_relative"] == "notes.txt"


def test_engine_owner_gate_still_refuses_a_tenantless_session(monkeypatch):
    """Fail-closed stays fail-closed on the engine lane: a canonical session
    with no tenant is refused before any dispatch is staged (401), exactly as
    ``_engine_pc_files_owner`` has always required."""
    session = _session(tenant_id=None)
    history = _History(run_workspace=WORKSPACE)
    state = _state(monkeypatch, session, history, _StaleShadowError())

    status, body = _dispatch(state, _payload())
    assert status == 401
    assert body["error"]["code"] == "canonical_session_required"
    assert history.rows == {}


def test_read_intent_refuses_with_the_exact_wire_code_without_any_workspace(
    monkeypatch,
):
    """The reviewed wire code itself stays pinned: with neither pointer nor
    tenant the read intent refuses ``oracle_mesh_workspace_unavailable`` — the
    exact code the Engine maps to ``pc_files_workspace_unavailable`` (pinned
    engine-side in test_5015_pc_query_step_driver)."""
    session = _session(tenant_id=None)
    history = _History(run_workspace=WORKSPACE)
    state = _state(monkeypatch, session, history, _StaleShadowError())

    async def verified(request):
        return session, None

    monkeypatch.setattr(routes, "_verified_owner_request", verified)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    request = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace())
    wire = {
        "device_id": DEVICE, "run_id": RUN, "root_ref": "meshcentral_private_trial",
        "path_relative": "notes.txt", "confirmed": True,
    }
    response = asyncio.run(routes.dispatch_oracle_mesh_read_intent(request, wire))
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == WIRE_REFUSAL_CODE
    assert history.rows == {}


def test_the_memory_workspace_still_decides_when_it_answers(monkeypatch):
    """Fresh-pointer behaviour is unchanged: the pointer's workspace wins and
    the run-row equality the Engine side depends on is the pointer's value."""
    session = _session(tenant_id=WORKSPACE)
    aligned = _History(run_workspace=MEMORY_WORKSPACE)
    state = _state(monkeypatch, session, aligned, MEMORY_WORKSPACE)

    status, body = _dispatch(state, _payload())
    assert status == 200, body
    assert aligned.rows

    # ... and a run row written under a different workspace stays refused, so
    # this test proves the memory value (not the tenant) is what was compared.
    mismatched = _History(run_workspace=WORKSPACE)
    state = _state(monkeypatch, session, mismatched, MEMORY_WORKSPACE)
    status, body = _dispatch(state, _payload())
    assert status != 200
    assert mismatched.rows == {}
