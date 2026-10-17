"""#4139 desktop lane — op intent, dispatch, projection and its refusals.

No live Broker, Identity or MeshCentral: the deployment ownership map, the
canonical account scope and the history state machine are injected, so these
tests exercise the real route wiring and the real result projection. The
screenshot bytes are a small synthetic JPEG; compositing is proven by the
executor-side tests and the live relay probe, never here.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.history import HistoryError, HistoryForbidden, MAX_MESH_ROW_BYTES

OWNER = "product-user-1"
ACCOUNT = "account-oracle-1"
WORKSPACE = "connector-ws-1"
TENANT_WS = "tenant-ws-1"
DEVICE = "device-oracle-1"
RUN = "run-desktop-1"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial\\meshcentral-padiem-trial.txt"
SECRET = "deployment-channel-secret-value-261017"
CONVERSATION = "chat_" + "c" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 128
NOTE = "captured 800x600 jpeg 132B sha256 deadbeef tiles 1"


def _mapping(command_exec: bool = True) -> list[dict]:
    row = {
        "account_ref": ACCOUNT, "device_id": DEVICE, "node_ref": NODE,
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "file_path": FILE_PATH,
    }
    if command_exec:
        row["command_exec"] = True
    return [row]


class Request:
    def __init__(self, data, state, *, secret=None):
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


def setup_auth(monkeypatch):
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    monkeypatch.setattr(routes, "_verified_owner_request", _verified)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)


class Identity:
    async def resolve_connector_owner_scope(self, *, session_id):
        del session_id
        return {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE}


class History:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.appended: list[dict] = []
        self.finished: list[tuple[str, str]] = []
        self.originals: dict[str, bytes] = {}
        self.fail_store = False
        self._seq = 0

    async def get_claw_run(self, user_id, run_id):
        if user_id != OWNER or run_id != RUN:
            return None
        return {"run_id": RUN, "conversation_id": CONVERSATION,
                "workspace_id": TENANT_WS, "status": "waiting"}

    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return None

    async def create_oracle_mesh_dispatch(self, **fields):
        if fields.get("kind") not in ("read", "command", "desktop"):
            raise HistoryError("kind must be read, command or desktop")
        row_bytes = sum(
            len(value.encode("utf-8"))
            for value in fields.values() if isinstance(value, str)
        )
        if row_bytes > MAX_MESH_ROW_BYTES:
            raise HistoryError("oracle mesh dispatch row exceeds the storage row bound")
        self._seq += 1
        dispatch_id = "dsp-%d" % self._seq
        row = {**fields, "dispatch_id": dispatch_id, "state": "pending",
               "nonce_sha256": None, "result_sha256": None, "result_bytes": None}
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
        if row.get("result_sha256") is None:
            row["result_sha256"] = content_sha256
            row["result_bytes"] = content_bytes
            return True
        return row["result_sha256"] == content_sha256

    async def finish_oracle_mesh_dispatch(self, *, dispatch_id, outcome):
        self.finished.append((dispatch_id, outcome))
        row = self.rows.get(dispatch_id)
        if row is not None:
            row["state"] = outcome
        return True

    async def store_oracle_mesh_original(self, **fields):
        raise AssertionError("text store must not serve a desktop capture")

    async def store_oracle_mesh_original_bytes(self, *, user_id, dispatch_id,
                                               conversation_id, message_id,
                                               raw, media_type,
                                               expected_sha256, expected_bytes):
        if self.fail_store:
            raise HistoryError("private store unavailable")
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            raise HistoryForbidden("mesh dispatch is not owned by current user")
        if (row.get("result_sha256") != expected_sha256
                or row.get("result_bytes") != expected_bytes):
            raise HistoryError("mesh original does not match the pinned result")
        data = bytes(raw)
        if (len(data) != expected_bytes
                or hashlib.sha256(data).hexdigest() != expected_sha256):
            raise HistoryError("mesh original bytes do not match the pinned result")
        if media_type != "image/jpeg" or not data.startswith(b"\xff\xd8\xff"):
            raise HistoryError("mesh original is not a JPEG screenshot")
        self.originals[dispatch_id] = data
        return "claw-model-context/v1/%s/%s.utf8" % (conversation_id, message_id)

    async def read_oracle_mesh_original(self, *, user_id, dispatch_id,
                                        conversation_id, message_id):
        del conversation_id, message_id
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        data = self.originals.get(dispatch_id)
        if data is None:
            if row.get("result_sha256"):
                raise HistoryError("mesh original missing from store")
            return None
        return data, row["result_sha256"]

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return dict(row)

    async def append_local_task_result(self, **fields):
        if any(m["message_id"] == fields["message_id"] for m in self.appended):
            return False
        self.appended.append(fields)
        return True


def _state(command_exec: bool = True):
    source = routes.build_oracle_mesh_return_source(
        _mapping(command_exec), SECRET, routes.EXECUTION_MODE_MESH)
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=Identity(),
        history_store=History(),
        connector_txt_read_source=None,
    )


def _dispatch(state, op: str = "desktop:capture"):
    response = asyncio.run(routes.dispatch_oracle_mesh_desktop_intent(
        Request({"run_id": RUN, "device_id": None, "confirmed": True}, state),
        desktop_op=op,
        wire={"run_id": RUN, "device_id": None, "confirmed": True},
    ))
    return response.status_code, json.loads(response.body), response.headers


def _submit(state, dispatch_row, *, termination, note, blob: bytes = b""):
    nonce = "n" * 32
    state.history_store.rows[dispatch_row["dispatch_id"]]["nonce_sha256"] = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    )
    if blob:
        digest = hashlib.sha256(blob).hexdigest()
        size = len(blob)
    else:
        digest = hashlib.sha256(note.encode("utf-8")).hexdigest()
        size = len(note.encode("utf-8"))
    payload = {
        "dispatch_id": dispatch_row["dispatch_id"],
        "nonce": nonce,
        "termination": termination,
        "exit_code": None,
        "content_utf8": note,
        "content_sha256": digest,
        "content_bytes": size,
    }
    if blob:
        payload["content_blob_base64"] = base64.b64encode(blob).decode("ascii")
        payload["content_blob_sha256"] = digest
        payload["content_blob_bytes"] = size
        payload["content_blob_media_type"] = "image/jpeg"
    return call(routes.oracle_mesh_read_result, Request(payload, state, secret=SECRET))


def _retrieve(state, dispatch_id):
    req = Request({}, state)
    req.path_params = {"dispatch_id": dispatch_id}
    response = asyncio.run(routes.oracle_mesh_read_original(req))
    return response.status_code, response.body, dict(response.headers)


def test_desktop_dispatch_reuses_the_command_grant(monkeypatch):
    setup_auth(monkeypatch)
    denied = _state(command_exec=False)
    status, body, _ = _dispatch(denied)
    assert status == 403
    assert body["error"]["code"] == "oracle_mesh_command_unverified"
    assert denied.history_store.rows == {}

    allowed = _state(command_exec=True)
    status, body, _ = _dispatch(allowed)
    assert status == 200, body
    row = allowed.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["kind"] == "desktop"
    assert row["command_text"] == "desktop:capture"
    assert row["root_ref"] == routes._COMMAND_ROOT_REF
    assert row["file_path"] == routes._COMMAND_FILE_SENTINEL


@pytest.mark.parametrize("op,canonical", [
    ("desktop:capture", "desktop:capture"),
    ("desktop:type\nhello", "desktop:type\nhello"),
    ("desktop:keys\nctrl+s", "desktop:keys\nctrl+s"),
    ("desktop:click\n960,540", "desktop:click\n960,540"),
])
def test_desktop_ops_dispatch(monkeypatch, op, canonical):
    setup_auth(monkeypatch)
    state = _state()
    status, body, _ = _dispatch(state, op)
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["command_text"] == canonical


@pytest.mark.parametrize("op", [
    "desktop:explode", "desktop:capture\n800x600", "desktop:type\n",
    "desktop:keys\nctrl+alt+del", "desktop:click\n1,2,3",
    "hostname.exe", "desktop:",
])
def test_malformed_ops_are_refused_before_a_dispatch(monkeypatch, op):
    setup_auth(monkeypatch)
    state = _state()
    status, body, _ = _dispatch(state, op)
    assert status == 422
    assert body["error"]["code"] == "oracle_mesh_desktop_op_invalid"
    assert state.history_store.rows == {}


def test_poll_hands_the_desktop_op_to_the_executor(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _dispatch(state, "desktop:keys\nenter")
    status, body, _ = call(
        routes.oracle_mesh_read_poll, Request({}, state, secret=SECRET))
    assert status == 200, body
    assert body["dispatch"]["kind"] == "desktop"
    assert body["dispatch"]["command_text"] == "desktop:keys\nenter"


def test_capture_is_stored_and_projected_with_its_marker(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    digest = hashlib.sha256(JPEG).hexdigest()

    status, body, _ = _submit(state, row, termination="captured", note=NOTE, blob=JPEG)
    assert status == 200, body
    assert state.history_store.originals[row["dispatch_id"]] == JPEG
    assert state.history_store.finished[-1] == (row["dispatch_id"], "done")
    assert len(state.history_store.appended) == 1
    message = state.history_store.appended[0]
    assert message["status"] == "completed"
    assert "COM1 데스크톱 화면 캡처" in message["content"]
    assert NOTE in message["content"]
    assert digest in message["content"]
    marker = "화면 캡처 원문: GET /api/claw/connector/mesh-results/" + row["dispatch_id"]
    assert marker in message["content"]

    # The owner reads the screenshot back: exact bytes, digest and type.
    status, raw, headers = _retrieve(state, row["dispatch_id"])
    assert status == 200
    assert raw == JPEG
    assert headers.get("x-oracle-mesh-content-sha256") == digest
    assert headers.get("content-type", "").startswith("image/jpeg")

    # A duplicate submit is refused and stores nothing a second time.
    status, body, _ = _submit(state, row, termination="captured", note=NOTE, blob=JPEG)
    assert status == 409
    assert len(state.history_store.appended) == 1


def test_act_is_delivered_without_a_store(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state, "desktop:keys\nctrl+s")
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]

    status, body, _ = _submit(state, row, termination="acted", note="keys ctrl+s")
    assert status == 200, body
    assert state.history_store.originals == {}
    message = state.history_store.appended[0]
    assert message["status"] == "completed"
    assert "키 입력 (ctrl+s)" in message["content"]
    assert "keys ctrl+s" in message["content"]


def test_type_and_click_labels(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state, "desktop:type\nhello")
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(state, row, termination="acted", note="typed 5 characters")
    assert status == 200, body
    assert "문자 입력" in state.history_store.appended[0]["content"]

    state2 = _state()
    _, created2, _ = _dispatch(state2, "desktop:click\n960,540")
    row2 = state2.history_store.rows[created2["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(state2, row2, termination="acted", note="click 960,540")
    assert status == 200, body
    assert "마우스 클릭 (960,540)" in state2.history_store.appended[0]["content"]


def test_tampered_blob_is_refused(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]

    nonce = "n" * 32
    state.history_store.rows[row["dispatch_id"]]["nonce_sha256"] = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest())
    evil = b"\xff\xd8\xff\xe0" + b"\x99" * 128
    payload = {
        "dispatch_id": row["dispatch_id"], "nonce": nonce,
        "termination": "captured", "exit_code": None,
        "content_utf8": NOTE,
        "content_sha256": hashlib.sha256(evil).hexdigest(),
        "content_bytes": len(evil),
        "content_blob_base64": base64.b64encode(JPEG).decode("ascii"),
        "content_blob_sha256": hashlib.sha256(JPEG).hexdigest(),
        "content_blob_bytes": len(JPEG),
        "content_blob_media_type": "image/jpeg",
    }
    status, body, _ = call(
        routes.oracle_mesh_read_result, Request(payload, state, secret=SECRET))
    assert status == 200, body
    assert state.history_store.appended[0]["status"] == "failed"
    assert "무결성 불일치" in state.history_store.appended[0]["content"]
    assert state.history_store.originals == {}
    assert state.history_store.finished[-1] == (row["dispatch_id"], "failed")


def test_desktop_never_reports_an_exit_code(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]

    nonce = "n" * 32
    state.history_store.rows[row["dispatch_id"]]["nonce_sha256"] = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest())
    payload = {
        "dispatch_id": row["dispatch_id"], "nonce": nonce,
        "termination": "acted", "exit_code": 0,
        "content_utf8": "keys enter",
        "content_sha256": hashlib.sha256(b"keys enter").hexdigest(),
        "content_bytes": len(b"keys enter"),
    }
    status, body, _ = call(
        routes.oracle_mesh_read_result, Request(payload, state, secret=SECRET))
    assert status == 200, body
    assert "무결성 불일치" in state.history_store.appended[0]["content"]


def test_unavailable_and_timeout_stay_explicit_failures(monkeypatch):
    setup_auth(monkeypatch)
    for termination in ("desktop_unavailable", "timed_out", "not_executed"):
        state = _state()
        _, created, _ = _dispatch(state)
        row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
        status, body, _ = _submit(
            state, row, termination=termination, note="the PC desktop did not answer")
        assert status == 200, body
        message = state.history_store.appended[0]
        assert message["status"] == "failed"
        assert "도달하지 못했습니다" in message["content"] or "실행되지 않음" in message["content"]
        assert "종료 코드: 0" not in message["content"]


def test_output_too_large_keeps_its_note(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(
        state, row, termination="output_too_large", note="captured 7280x1600 jpeg withheld")
    assert status == 200, body
    message = state.history_store.appended[0]
    assert message["status"] == "failed"
    assert "전송 한도를 초과" in message["content"]
    assert "captured 7280x1600 jpeg withheld" in message["content"]


def test_capture_retrieval_refuses_foreign_and_unknown_ids(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, payload, _ = _submit(state, row, termination="captured", note=NOTE, blob=JPEG)
    assert status == 200, payload
    monkeypatch.setattr(routes, "current_user_id", lambda request: "foreign-user")
    status, _, _ = _retrieve(state, row["dispatch_id"])
    assert status == 404
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    status, _, _ = _retrieve(state, "dsp-unknown")
    assert status == 404


def test_intent_requires_an_explicit_delimited_desktop_op():
    from app.claw_general_routes import _requested_local_desktop

    assert _requested_local_desktop("COM1 화면을 캡처해줘 `capture`") == (True, "desktop:capture")
    assert _requested_local_desktop("내 PC 메모장에 입력해줘 `type:hello`") == (
        True, "desktop:type\nhello")
    assert _requested_local_desktop("COM1에서 `keys:ctrl+s` 눌러줘") == (
        True, "desktop:keys\nctrl+s")
    assert _requested_local_desktop("로컬PC 화면 클릭해줘 `click:960,540`") == (
        True, "desktop:click\n960,540")
    # Prose about the screen is not an operation order.
    assert _requested_local_desktop("내 PC 화면 설정을 알려줘") == (False, None)
    # No delimiter, two spans, no marker, or an unparsable span: not this lane.
    assert _requested_local_desktop("COM1 화면을 캡처해줘") == (False, None)
    assert _requested_local_desktop("COM1 화면 `capture` `click:1,2` 보여줘") == (False, None)
    assert _requested_local_desktop("화면을 캡처해줘 `capture`") == (False, None)
    assert _requested_local_desktop("COM1 화면 보여줘 `screenshot`") == (False, None)
    assert _requested_local_desktop("COM1 화면 보여줘 `capture:extra`") == (False, None)
    # A delimited shell command stays the command lane's business here.
    assert _requested_local_desktop("내 PC에서 `hostname.exe` 실행해줘") == (False, None)



def _signed_engine_request(state, *, subject_id="sub_verified", secret="s" * 32):
    import hmac
    import time

    state.claw_engine_desktop_secret = secret
    request = Request({
        "subject_id": subject_id,
        "run_id": RUN,
        "device_id": DEVICE,
        "desktop_op": "desktop:capture",
    }, state)
    timestamp = str(int(time.time()))
    request.headers["X-Claw-Engine-Time"] = timestamp
    request.headers["X-Claw-Engine-Proof"] = hmac.new(
        secret.encode(), timestamp.encode() + b"." + request._data,
        hashlib.sha256,
    ).hexdigest()
    return request


class EngineIdentity(Identity):
    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == "b54-padiem-claw"
        if canonical_subject_id != "sub_verified":
            raise ValueError("foreign owner")
        return OWNER

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        assert product_id == "b54-padiem-claw"
        assert product_user_id == OWNER
        return SimpleNamespace(
            session_id="s_verified",
            product_id="b54-padiem-claw",
            subject=SimpleNamespace(subject_id="sub_verified"),
            tenant_id=TENANT_WS,
            is_active=lambda *, now: True,
        )


def test_signed_engine_desktop_dispatch_reuses_real_owner_checks():
    state = _state()
    state.control_plane_identity_authority = EngineIdentity()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed_engine_request(state)
    ))
    body = json.loads(response.body)
    assert response.status_code == 200, body
    assert body["dispatch"]["kind"] == "desktop"
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["account_ref"] == ACCOUNT
    assert row["device_id"] == DEVICE
    assert row["run_id"] == RUN


def test_signed_engine_desktop_foreign_subject_rejected():
    state = _state()
    state.control_plane_identity_authority = EngineIdentity()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed_engine_request(state, subject_id="sub_foreign")
    ))
    assert response.status_code == 401
    assert state.history_store.rows == {}


def test_signed_engine_desktop_tampered_proof_rejected():
    state = _state()
    state.control_plane_identity_authority = EngineIdentity()
    request = _signed_engine_request(state)
    request.headers["X-Claw-Engine-Proof"] = "0" * 64
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(request))
    assert response.status_code == 401
    assert state.history_store.rows == {}


def test_signed_engine_desktop_command_grant_off_rejected():
    state = _state(command_exec=False)
    state.control_plane_identity_authority = EngineIdentity()
    response = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed_engine_request(state)
    ))
    assert response.status_code == 403
    assert state.history_store.rows == {}



def test_signed_engine_status_returns_owner_pinned_result():
    import hmac
    import time
    state = _state()
    state.control_plane_identity_authority = EngineIdentity()
    posted = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed_engine_request(state)
    ))
    assert posted.status_code == 200
    dispatch_id = json.loads(posted.body)["dispatch"]["dispatch_id"]
    row = state.history_store.rows[dispatch_id]
    row["state"] = "done"
    row["result_sha256"] = "a" * 64
    request = Request({
        "subject_id": "sub_verified",
        "run_id": RUN, "dispatch_id": dispatch_id, "mode": "status",
    }, state)
    timestamp = str(int(time.time()))
    request.headers["X-Claw-Engine-Time"] = timestamp
    request.headers["X-Claw-Engine-Proof"] = hmac.new(
        ("s" * 32).encode(),
        timestamp.encode() + b"." + request._data, hashlib.sha256,
    ).hexdigest()
    result = asyncio.run(routes.oracle_mesh_engine_desktop_call(request))
    assert result.status_code == 200
    data = json.loads(result.body)
    assert data["dispatch"]["state"] == "done"
    assert data["dispatch"]["result_sha256"] == "a" * 64
    assert data["dispatch"]["run_id"] == RUN



def test_signed_engine_image_fetch_returns_actual_pinned_jpeg():
    """Only the canonical owner/run/dispatch can retrieve real JPEG bytes."""
    import hmac
    import time

    state = _state()
    state.control_plane_identity_authority = EngineIdentity()
    dispatched = asyncio.run(routes.oracle_mesh_engine_desktop_call(
        _signed_engine_request(state)
    ))
    assert dispatched.status_code == 200
    dispatch_id = json.loads(dispatched.body)["dispatch"]["dispatch_id"]
    digest = hashlib.sha256(JPEG).hexdigest()
    row = state.history_store.rows[dispatch_id]
    row["state"] = "done"
    row["result_sha256"] = digest
    row["result_bytes"] = len(JPEG)
    state.history_store.originals[dispatch_id] = JPEG

    def signed_image(subject, run=RUN):
        request = Request({
            "subject_id": subject, "run_id": run,
            "dispatch_id": dispatch_id, "mode": "image",
        }, state)
        stamp = str(int(time.time()))
        request.headers["X-Claw-Engine-Time"] = stamp
        request.headers["X-Claw-Engine-Proof"] = hmac.new(
            ("s" * 32).encode(),
            stamp.encode() + b"." + request._data,
            hashlib.sha256,
        ).hexdigest()
        return asyncio.run(routes.oracle_mesh_engine_desktop_call(request))

    original = signed_image("sub_verified")
    assert original.status_code == 200
    assert original.body == JPEG
    assert original.headers["X-Oracle-Mesh-Content-SHA256"] == digest
    assert signed_image("sub_foreign").status_code == 401
    assert signed_image("sub_verified", "run_foreign").status_code == 404
