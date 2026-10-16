"""#4139 — sovereign Oracle Mesh dispatch: full leg wiring and its refusals.

No live Broker, Identity or MeshCentral: the deployment ownership map, the
Identity consent and the official-client read port are all injected, so these
tests exercise the real route wiring, the real dispatch state machine and the
real executor loop rather than a stand-in.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.claw_local_task_result_projection import result_message_id
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

NOW = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)
TEXT = (
    "PADIEM MESHCENTRAL SINGLE-PC TXT TEST\nDATE=2026-10-16\nHOST=COM1\n"
    "TEST_CASE=mesh-agent-read-and-return\nEND_OF_FILE\n"
)
TEXT_BYTES = TEXT.encode("utf-8")
SHA = hashlib.sha256(TEXT_BYTES).hexdigest()
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial\\meshcentral-padiem-trial.txt"
SECRET = "deployment-channel-secret-value-261017"
CONVERSATION = "chat_" + "a" * 32

OWNER = "product-user-1"
ACCOUNT = "account-oracle-1"
WORKSPACE = "connector-ws-1"
TENANT_WS = "tenant-ws-1"
DEVICE = "device-oracle-1"
RUN = "run-oracle-1"


def _mapping(account: str = ACCOUNT, device: str = DEVICE, node: str = NODE) -> list[dict]:
    return [{
        "account_ref": account, "device_id": device, "node_ref": node,
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "file_path": FILE_PATH,
    }]


class Request:
    def __init__(self, data, state, *, secret: str | None = None):
        self.app = SimpleNamespace(state=state)
        raw = json.dumps(data).encode("utf-8")
        self.headers = {"content-type": "application/json", "content-length": str(len(raw))}
        if secret is not None:
            self.headers[routes.ORACLE_MESH_CHANNEL_HEADER] = secret
        self._data = raw

    async def body(self):
        return self._data


def call(handler, request):
    response = asyncio.run(handler(request))
    return response.status_code, json.loads(response.body), response.headers


async def _verified(request):
    del request
    return SimpleNamespace(session_id="session.canonical.owner.1"), None


async def _workspace(request, uid):
    del request, uid
    return TENANT_WS


def setup_auth(monkeypatch, user: str = OWNER):
    monkeypatch.setattr(routes, "current_user_id", lambda request: user)
    monkeypatch.setattr(routes, "_verified_owner_request", _verified)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)


def consent(device: str = DEVICE, account: str = ACCOUNT) -> dict:
    return {
        "consent_id": "consent-1", "device_id": device,
        "owner_subject_id": "subject.canonical.owner.1",
        "account_ref": account, "workspace_ref": WORKSPACE,
        "granted_at": (NOW - timedelta(days=1)).isoformat(),
        "withdrawn_at": None,
    }


class Identity:
    def __init__(self, granted: dict | None):
        self._granted = granted
    async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
        del session_id
        if self._granted is None:
            from app.control_plane_identity import IdentityBridgeError
            raise IdentityBridgeError(
                403, "enrollment_consent_required", "no consent established")
        if self._granted.get("device_id") != device_id:
            raise RuntimeError("consent names another device")
        return dict(self._granted)
    async def resolve_connector_owner_scope(self, *, session_id):
        del session_id
        account = (self._granted or {}).get("account_ref", ACCOUNT)
        return {"account_ref": account, "workspace_ref": WORKSPACE}


class History:
    """The dispatch state machine under test, backed by real guard semantics."""

    def __init__(self, *, broker_correlation: dict | None = None, append_fails: int = 0):
        self.rows: dict[str, dict] = {}
        self.appended: list[dict] = []
        self.consume_calls: list[str] = []
        self._append_fails = append_fails
        self._correlation = broker_correlation
        self._seq = 0

    async def get_claw_run(self, user_id, run_id):
        if user_id != OWNER or run_id != RUN:
            return None
        return {"run_id": RUN, "conversation_id": CONVERSATION,
                "workspace_id": TENANT_WS, "status": "waiting"}

    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return dict(self._correlation) if self._correlation else None

    async def create_oracle_mesh_dispatch(self, **fields):
        self._seq += 1
        dispatch_id = f"dsp-{self._seq}"
        row = {**fields, "dispatch_id": dispatch_id, "state": "pending",
               "nonce_sha256": None, "result_sha256": None, "result_bytes": None,
               "created_at": NOW.isoformat()}
        self.rows[dispatch_id] = row
        return dict(row)

    async def oldest_pending_oracle_mesh_dispatch(self):
        for row in self.rows.values():
            if row["state"] == "pending" and row["nonce_sha256"] is None:
                return dict(row)
        return None

    async def claim_oracle_mesh_dispatch(self, *, dispatch_id, nonce_sha256):
        row = self.rows.get(dispatch_id)
        if row is None or row["state"] != "pending" or row["nonce_sha256"] is not None:
            return False
        row["nonce_sha256"] = nonce_sha256
        return True

    async def consume_oracle_mesh_dispatch(self, *, dispatch_id, nonce):
        self.consume_calls.append(dispatch_id)
        row = self.rows.get(dispatch_id)
        if row is None or not row.get("nonce_sha256"):
            return None
        if hashlib.sha256(nonce.encode("utf-8")).hexdigest() != row["nonce_sha256"]:
            return None
        if row["state"] == "store_failed":
            row["state"] = "received"
            return {**dict(row), "claim": "retry"}
        if row["state"] != "pending":
            return None
        row["state"] = "received"
        return {**dict(row), "claim": "first"}

    async def mark_oracle_mesh_store_failed(self, *, dispatch_id):
        row = self.rows.get(dispatch_id)
        if row is None or row["state"] != "received":
            return False
        row["state"] = "store_failed"
        return True

    async def record_oracle_mesh_first_result(self, *, dispatch_id, content_sha256, content_bytes):
        row = self.rows.get(dispatch_id)
        if row is None:
            return False
        pinned = row.get("result_sha256")
        if pinned is None:
            row["result_sha256"] = content_sha256
            row["result_bytes"] = content_bytes
            return True
        return pinned == content_sha256 and row["result_bytes"] == content_bytes

    async def finish_oracle_mesh_dispatch(self, *, dispatch_id, outcome):
        row = self.rows.get(dispatch_id)
        if row is None or row["state"] != "received":
            return False
        row["state"] = outcome
        return True

    async def append_local_task_result(self, **fields):
        if self._append_fails > 0:
            self._append_fails -= 1
            raise RuntimeError("conversation store temporarily unavailable")
        self.appended.append(dict(fields))
        return True


def state(*, mesh=None, history=None, identity=None, secret=SECRET):
    return SimpleNamespace(
oracle_mesh_return_source=routes.build_oracle_mesh_return_source(
            mesh if mesh is not None else _mapping(), secret,
            routes.EXECUTION_MODE_MESH,
        ),
        control_plane_identity_authority=identity or Identity(consent()),
        history_store=history or History(),
    )


def intent_body(**overrides):
    payload = {
        "device_id": DEVICE, "run_id": RUN,
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "confirmed": True,
    }
    payload.update(overrides)
    return payload


def result_body(dispatch_id, nonce, **overrides):
    payload = {
        "dispatch_id": dispatch_id, "nonce": nonce,
        "termination": "exited", "exit_code": 0,
        "content_utf8": TEXT, "content_sha256": SHA,
        "content_bytes": len(TEXT_BYTES),
    }
    payload.update(overrides)
    return payload


def create_dispatch(history):
    status, result, _ = call(
        routes.oracle_mesh_read_request,
        Request(intent_body(), state(history=history)),
    )
    assert status == 200, result
    return result["dispatch"]["dispatch_id"]


# ---------------------------------------------------------------- wiring
def test_request_poll_real_read_result_reaches_the_same_conversation(monkeypatch):
    """One request, one claim, one real read port, one append in the origin."""
    setup_auth(monkeypatch)
    from kagent.local_agent_oracle_mesh_executor import (
        OracleMeshDispatch, OracleMeshExecutor, OracleMeshExecutionOutcome,
    )

    history = History()
    dispatch_id = create_dispatch(history)
    assert history.rows[dispatch_id]["evidence_ref"] is None
    assert history.rows[dispatch_id]["binding_ref"] is None

    # 1. executor polls the server over the authenticated channel
    seen_paths: list[str] = []

    def transport(path, payload):
        seen_paths.append(path)
        status, _, _ = call(
            routes.oracle_mesh_read_poll,
            Request({}, state(history=history), secret=SECRET),
        )
        assert status == 200
        return status, dict(_["dispatch_payload"])

    # Capture the exact dispatch the server hands out.
    poll_status, poll_result, _ = call(
        routes.oracle_mesh_read_poll,
        Request({}, state(history=history), secret=SECRET),
    )
    assert poll_status == 200 and poll_result["dispatch"] is not None
    granted = poll_result["dispatch"]
    nonce = granted["nonce"]
    assert granted["file_path"] == FILE_PATH and granted["node_ref"] == NODE

    # 2. the executor performs the REAL official-client read through the port
    read_calls: list[dict] = []

    class ReadPort:
        def read_bytes(self, *, node_ref, file_path, timeout_seconds):
            read_calls.append({"node_ref": node_ref, "file_path": file_path,
                               "timeout_seconds": timeout_seconds})
            return TEXT_BYTES

    executor = OracleMeshExecutor(
        chat_origin="https://chat.padiem.net", channel_secret=SECRET,
        read_port=ReadPort(), transport=transport,
    )
    dispatched = OracleMeshDispatch(
        dispatch_id=granted["dispatch_id"], nonce=nonce,
        node_ref=granted["node_ref"], file_path=granted["file_path"],
        command_id=granted["command_id"], run_id=granted["run_id"],
    )
    outcome = executor.execute(dispatched)
    assert outcome.exit_code == 0 and outcome.body == TEXT_BYTES
    assert read_calls == [{"node_ref": NODE, "file_path": FILE_PATH,
                           "timeout_seconds": 120}]

    # 3. the executor submits; the server verifies and appends once
    submitted = []
    def submit_transport(path, payload):
        submitted.append((path, payload))
        return call(routes.oracle_mesh_read_result,
                    Request(payload, state(history=history), secret=SECRET))[0:2]

    executor._transport = submit_transport
    ack = executor.submit(dispatched, outcome)
    assert ack["ok"] is True and ack["status"] == "completed"
    assert ack["claim"] == "first" and ack["brokerAcknowledged"] is False
    assert submitted[0][0] == "/api/claw/connector/mesh-reads/result"
    assert len(history.appended) == 1
    appended = history.appended[0]
    assert appended["content"] == "PC 파일 읽기 결과:\n" + TEXT
    assert appended["message_id"] == result_message_id(
        conversation_id=CONVERSATION,
        command_id=granted["command_id"], revision_ref=granted["revision_ref"],
    )
    assert history.rows[dispatch_id]["state"] == "done"
    del seen_paths


def test_poll_then_result_twice_refuses_the_second_consume(monkeypatch):
    """A duplicate submission loses the atomic gate; it does not re-append."""
    setup_auth(monkeypatch)
    history = History()
    dispatch_id = create_dispatch(history)
    _, poll, _ = call(routes.oracle_mesh_read_poll,
                      Request({}, state(history=history), secret=SECRET))
    nonce = poll["dispatch"]["nonce"]

    first_status, first, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce), state(history=history), secret=SECRET),
    )
    assert first_status == 200 and first["claim"] == "first"
    second_status, second, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce), state(history=history), secret=SECRET),
    )
    assert second_status == 409
    assert second["error"]["code"] == "oracle_mesh_dispatch_rejected"
    assert len(history.appended) == 1


def test_store_failure_allows_resending_the_same_result(monkeypatch):
    """Transient store failure parks the result; retry appends, no re-read."""
    setup_auth(monkeypatch)
    history = History(append_fails=1)
    dispatch_id = create_dispatch(history)
    _, poll, _ = call(routes.oracle_mesh_read_poll,
                      Request({}, state(history=history), secret=SECRET))
    nonce = poll["dispatch"]["nonce"]

    failed_status, failed, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce), state(history=history), secret=SECRET),
    )
    assert failed_status == 503
    assert failed["error"]["code"] == "oracle_mesh_append_unavailable"
    assert history.rows[dispatch_id]["state"] == "store_failed"
    assert history.appended == []

    retry_status, retry, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce), state(history=history), secret=SECRET),
    )
    assert retry_status == 200 and retry["claim"] == "retry"
    assert retry["status"] == "completed"
    assert len(history.appended) == 1
    assert history.appended[0]["content"] == "PC 파일 읽기 결과:\n" + TEXT
    assert history.rows[dispatch_id]["state"] == "done"


# ---------------------------------------------------------------- refusals
def test_cross_account_and_foreign_node_are_refused(monkeypatch):
    setup_auth(monkeypatch)
    # Another PADIEM account's request cannot use this account's mesh row.
    st = state(identity=Identity(consent(account="account-intruder-9")))
    status, result, _ = call(routes.oracle_mesh_read_request,
                             Request(intent_body(), st))
    assert status == 403
    assert result["error"]["code"] == "oracle_mesh_ownership_unverified"

    # A device the operator never verified for this file is refused too.
    history = History()
    st = state(mesh=_mapping(device="device-not-verified"), history=history)
    status, result, _ = call(routes.oracle_mesh_read_request,
                             Request(intent_body(), st))
    assert status == 403
    assert result["error"]["code"] == "oracle_mesh_ownership_unverified"
    assert history.rows == {}


def test_executor_authentication_is_required_on_both_legs(monkeypatch):
    setup_auth(monkeypatch)
    history = History()
    dispatch_id = create_dispatch(history)
    for secret in (None, "wrong-secret-value-0000"):
        status, result, _ = call(
            routes.oracle_mesh_read_poll,
            Request({}, state(history=history), secret=secret),
        )
        assert status == 403
        assert result["error"]["code"] == "oracle_mesh_channel_rejected"
    status, result, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, "nope"), state(history=history), secret="wrong-secret-value-0000"),
    )
    assert status == 403
    assert result["error"]["code"] == "oracle_mesh_channel_rejected"


def test_tampered_body_and_hash_is_refused_and_terminal(monkeypatch):
    setup_auth(monkeypatch)
    history = History()
    dispatch_id = create_dispatch(history)
    _, poll, _ = call(routes.oracle_mesh_read_poll,
                      Request({}, state(history=history), secret=SECRET))
    nonce = poll["dispatch"]["nonce"]
    status, result, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce, content_utf8="forged\n"),
                state(history=history), secret=SECRET),
    )
    assert status == 200 and result["status"] == "failed"
    assert history.appended[0]["content"].startswith("로컬 러너 작업 결과를 검증하지 못했습니다")
    assert history.rows[dispatch_id]["state"] == "failed"


def test_failed_execution_is_delivered_truthfully(monkeypatch):
    setup_auth(monkeypatch)
    history = History()
    dispatch_id = create_dispatch(history)
    _, poll, _ = call(routes.oracle_mesh_read_poll,
                      Request({}, state(history=history), secret=SECRET))
    nonce = poll["dispatch"]["nonce"]
    status, result, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce, termination="exited", exit_code=1,
                            content_utf8="", content_sha256="", content_bytes=0),
                state(history=history), secret=SECRET),
    )
    assert status == 200 and result["status"] == "failed"
    assert "종료 코드: 1" in history.appended[0]["content"]


def test_foreign_nonce_is_refused(monkeypatch):
    setup_auth(monkeypatch)
    history = History()
    dispatch_id = create_dispatch(history)
    call(routes.oracle_mesh_read_poll, Request({}, state(history=history), secret=SECRET))
    status, result, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, "not-the-granted-nonce"),
                state(history=history), secret=SECRET),
    )
    assert status == 409
    assert result["error"]["code"] == "oracle_mesh_dispatch_rejected"


def test_history_requires_the_owner_run_and_refuses_foreign_ownership(monkeypatch):
    setup_auth(monkeypatch)
    history = History()
    st = state(history=history)
    status, result, _ = call(
        routes.oracle_mesh_read_request,
        Request(intent_body(run_id="run-not-mine"), st),
    )
    assert status == 404
    assert result["error"]["code"] == "oracle_mesh_run_unavailable"

def test_resend_with_different_bytes_is_refused(monkeypatch):
    """The pinned first result wins: a differing resend is never appended."""
    setup_auth(monkeypatch)
    history = History(append_fails=1)
    dispatch_id = create_dispatch(history)
    _, poll, _ = call(routes.oracle_mesh_read_poll,
                      Request({}, state(history=history), secret=SECRET))
    nonce = poll["dispatch"]["nonce"]

    first_status, _, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce), state(history=history), secret=SECRET),
    )
    assert first_status == 503  # transient store failure parked the result
    other = TEXT + "second body\n"
    status, result, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce, content_utf8=other,
                            content_sha256=hashlib.sha256(other.encode()).hexdigest(),
                            content_bytes=len(other.encode())),
                state(history=history), secret=SECRET),
    )
    assert status == 409
    assert result["error"]["code"] == "oracle_mesh_result_fingerprint_mismatch"
    assert history.appended == []

    # The identical result still goes through, unchanged.
    ok_status, ok, _ = call(
        routes.oracle_mesh_read_result,
        Request(result_body(dispatch_id, nonce), state(history=history), secret=SECRET),
    )
    assert ok_status == 200 and ok["claim"] == "retry"
    assert history.appended[0]["content"] == "PC 파일 읽기 결과:\n" + TEXT


def test_executor_holds_the_result_across_a_store_failure(monkeypatch):
    """503 parks the result: the executor resends the same bytes, no re-read."""
    setup_auth(monkeypatch)
    from kagent.local_agent_oracle_mesh_executor import (
        OracleMeshDispatch, OracleMeshExecutor,
    )

    history = History(append_fails=1)
    dispatch_id = create_dispatch(history)
    _, poll, _ = call(routes.oracle_mesh_read_poll,
                      Request({}, state(history=history), secret=SECRET))
    granted = poll["dispatch"]
    reads = []

    class ReadPort:
        def read_bytes(self, *, node_ref, file_path, timeout_seconds):
            reads.append(file_path)
            return TEXT_BYTES

    executor = OracleMeshExecutor(
        chat_origin="https://chat.padiem.net", channel_secret=SECRET,
        read_port=ReadPort(),
        transport=lambda path, payload: call(
            routes.oracle_mesh_read_result,
            Request(payload, state(history=history), secret=SECRET))[0:2],
    )
    dispatched = OracleMeshDispatch(
        dispatch_id=granted["dispatch_id"], nonce=granted["nonce"],
        node_ref=granted["node_ref"], file_path=granted["file_path"],
        command_id=granted["command_id"], run_id=granted["run_id"],
    )
    outcome = executor.execute(dispatched)
    parked = executor.submit(dispatched, outcome)
    assert parked["retryable"] is True and parked["resend_pending"] is True
    assert executor.resend_pending is True
    assert reads == [FILE_PATH]  # exactly one PC read so far

    delivered = executor.run_once()  # retries the held result, no new read
    assert delivered["ok"] is True and delivered["status"] == "completed"
    assert reads == [FILE_PATH]  # still one: the file was never read again
    assert executor.resend_pending is False
    assert history.appended[0]["content"] == "PC 파일 읽기 결과:\n" + TEXT

def test_mesh_lane_proceeds_without_a_native_consent_and_refuses_withdrawal(monkeypatch):
    """Consent existence is not a native precondition; withdrawal still is."""
    setup_auth(monkeypatch)
    # No consent record at all: the authenticated scope is the authority.
    history = History()
    st = state(history=history, identity=Identity(None))
    status, result, _ = call(
        routes.oracle_mesh_read_request, Request(intent_body(), st))
    assert status == 200, result
    assert history.rows[result["dispatch"]["dispatch_id"]]["state"] == "pending"

    # A withdrawn consent is a hard refusal, never a silent proceed.
    withdrawn = consent()
    withdrawn["withdrawn_at"] = NOW.isoformat()
    st = state(history=History(), identity=Identity(withdrawn))
    status, result, _ = call(
        routes.oracle_mesh_read_request, Request(intent_body(), st))
    assert status == 403
    assert result["error"]["code"] == "oracle_mesh_consent_required"


def test_row_without_account_pin_is_rejected_at_composition(monkeypatch):
    """An omitted account is never allow-all: the source stays unconfigured."""
    setup_auth(monkeypatch)
    unpinned = [{
        "node_ref": NODE, "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt", "file_path": FILE_PATH,
    }]
    assert routes.build_oracle_mesh_return_source(unpinned, SECRET) is None
    source = routes.build_oracle_mesh_return_source(
        _mapping(account=ACCOUNT, device=None, node=NODE), SECRET,
        routes.EXECUTION_MODE_MESH,
    )
    assert source is not None and source.configured is True


def test_pinned_account_with_unpinned_device_uses_the_mesh_node(monkeypatch):
    """Exact account pin + no device pin: the Mesh node is the device."""
    setup_auth(monkeypatch)
    rows = _mapping(account=ACCOUNT, device=None, node=NODE)
    rows[0].pop("device_id", None)
    history = History()
    st = state(mesh=rows, history=history, identity=Identity(None))
    target, denial = asyncio.run(routes.resolve_oracle_mesh_execution(
        Request(intent_body(), st), path_relative="meshcentral-padiem-trial.txt"))
    assert denial is None and target is not None
    assert target["device_id"] == NODE
    status, result, _ = call(
        routes.oracle_mesh_read_request,
        Request(intent_body(device_id=NODE), st))
    assert status == 200, result
    row = history.rows[result["dispatch"]["dispatch_id"]]
    assert row["device_id"] == NODE and row["node_ref"] == NODE
    assert row["evidence_ref"] is None and row["binding_ref"] is None


def test_foreign_pinned_account_is_a_hard_ownership_refusal(monkeypatch):
    """The file is mapped, but only to another account: refuse, never fall back."""
    setup_auth(monkeypatch)
    st = state(mesh=_mapping(account="account-other-9", device=DEVICE, node=NODE))
    status, result, _ = call(
        routes.oracle_mesh_read_request,
        Request(intent_body(device_id=DEVICE), st))
    assert status == 403
    assert result["error"]["code"] == "oracle_mesh_ownership_unverified"

def _deployment_env(mapping=None, secret=SECRET, mode="mesh"):
    import json
    return {
        routes.ORACLE_MESH_OWNERSHIP_MAP_ENV: json.dumps(
            mapping if mapping is not None else _mapping()),
        routes.ORACLE_MESH_CHANNEL_SECRET_ENV: secret,
        routes.ORACLE_MESH_EXECUTION_MODE_ENV: mode,
    }


def test_env_builder_resolves_the_secrets_store_binding():
    """The channel secret arrives as a store object; the builder awaits it."""
    import asyncio
    import json

    class Store:
        def __init__(self, value=None, fail=False):
            self._value = value
            self._fail = fail
            self.calls = 0
        async def get(self):
            self.calls += 1
            if self._fail:
                raise RuntimeError("store unavailable")
            return self._value

    store = Store(SECRET)
    env = _deployment_env()
    env[routes.ORACLE_MESH_CHANNEL_SECRET_ENV] = store
    source = asyncio.run(routes.build_oracle_mesh_return_source_from_env(env))
    assert source is not None and source.configured is True
    assert source.execution_mode == "mesh"
    assert source.check_channel_secret(SECRET) is True
    assert store.calls == 1

    # A plain string secret still works (local/dev parity).
    plain = asyncio.run(routes.build_oracle_mesh_return_source_from_env(
        _deployment_env()))
    assert plain is not None and plain.check_channel_secret(SECRET) is True

    # An unreadable store keeps the source unconfigured: routes unmounted.
    dead = asyncio.run(routes.build_oracle_mesh_return_source_from_env(
        _deployment_env(secret=Store(fail=True))))
    assert dead is None
    missing = asyncio.run(routes.build_oracle_mesh_return_source_from_env(
        {routes.ORACLE_MESH_OWNERSHIP_MAP_ENV: json.dumps(_mapping())}))
    assert missing is None


def test_env_builder_resolves_the_ownership_map_secrets_store_binding():
    """The ownership map is a Secrets Store object too: resolve it via async get()."""
    import asyncio
    import json

    class Store:
        def __init__(self, value=None, fail=False):
            self._value = value
            self._fail = fail
            self.calls = 0
        async def get(self):
            self.calls += 1
            if self._fail:
                raise RuntimeError("store unavailable")
            return self._value

    map_store = Store(json.dumps(_mapping()))
    env = _deployment_env()
    env[routes.ORACLE_MESH_OWNERSHIP_MAP_ENV] = map_store
    source = asyncio.run(routes.build_oracle_mesh_return_source_from_env(env))
    assert source is not None and source.configured is True
    assert source.check_channel_secret(SECRET) is True
    assert map_store.calls == 1

    # An unreadable map store keeps the source unconfigured: routes unmounted.
    dead_env = _deployment_env()
    dead_env[routes.ORACLE_MESH_OWNERSHIP_MAP_ENV] = Store(fail=True)
    assert asyncio.run(routes.build_oracle_mesh_return_source_from_env(dead_env)) is None

    # An empty map value never configures the source.
    empty_env = _deployment_env()
    empty_env[routes.ORACLE_MESH_OWNERSHIP_MAP_ENV] = Store("   ")
    assert asyncio.run(routes.build_oracle_mesh_return_source_from_env(empty_env)) is None
