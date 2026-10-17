"""#4139 terminal lane — command dispatch, projection and its refusals.

No live Broker, Identity or MeshCentral: the deployment ownership map, the
canonical account scope and the history state machine are injected, so these
tests exercise the real route wiring and the real result projection.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.history import HistoryError, HistoryForbidden

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\Users\\limone\\AppData\\Local\\Padiem\\MeshCentralTrial\\meshcentral-padiem-trial.txt"
SECRET = "deployment-channel-secret-value-261017"
CONVERSATION = "chat_" + "b" * 32
OWNER = "product-user-1"
ACCOUNT = "account-oracle-1"
WORKSPACE = "connector-ws-1"
TENANT_WS = "tenant-ws-1"
DEVICE = "device-oracle-1"
RUN = "run-command-1"
COMMAND = "hostname.exe"
STDOUT = "Padiem-Command-Center\r\n"


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
        self._seq += 1
        dispatch_id = "dsp-%d" % self._seq
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
        if not isinstance(content_sha256, str) or not content_sha256:
            raise HistoryError("content_sha256 is required")
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

    async def store_oracle_mesh_original(self, *, user_id, dispatch_id,
                                         conversation_id, message_id,
                                         raw, expected_sha256, expected_bytes):
        if self.fail_store:
            raise HistoryError("private store unavailable")
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            raise HistoryForbidden("mesh dispatch is not owned by current user")
        if (row.get("result_sha256") != expected_sha256
                or row.get("result_bytes") != expected_bytes):
            raise HistoryError("mesh original does not match the pinned result")
        data = raw.encode("utf-8")
        if (len(data) != expected_bytes
                or hashlib.sha256(data).hexdigest() != expected_sha256):
            raise HistoryError("mesh original bytes do not match the pinned result")
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


def _dispatch(state, command: str = COMMAND):
    response = asyncio.run(routes.dispatch_oracle_mesh_command_intent(
        Request({"run_id": RUN, "device_id": None, "confirmed": True}, state),
        command=command,
        wire={"run_id": RUN, "device_id": None, "confirmed": True},
    ))
    return response.status_code, json.loads(response.body), response.headers


def _submit(state, dispatch_row, *, termination, exit_code, body: bytes):
    nonce = "n" * 32
    state.history_store.rows[dispatch_row["dispatch_id"]]["nonce_sha256"] = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    )
    payload = {
        "dispatch_id": dispatch_row["dispatch_id"],
        "nonce": nonce,
        "termination": termination,
        "exit_code": exit_code,
        "content_utf8": body.decode("utf-8"),
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "content_bytes": len(body),
    }
    return call(routes.oracle_mesh_read_result, Request(payload, state, secret=SECRET))


def test_command_dispatch_requires_the_separate_deployment_grant(monkeypatch):
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
    assert row["kind"] == "command"
    assert row["command_text"] == COMMAND
    # The file columns carry the documented sentinel, never a real path.
    assert row["root_ref"] == routes._COMMAND_ROOT_REF
    assert row["path_relative"] == routes._COMMAND_PATH_RELATIVE
    assert row["file_path"] == routes._COMMAND_FILE_SENTINEL


def test_poll_hands_the_command_to_the_executor(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _dispatch(state)
    status, body, _ = call(
        routes.oracle_mesh_read_poll, Request({}, state, secret=SECRET))
    assert status == 200, body
    dispatch = body["dispatch"]
    assert dispatch["kind"] == "command"
    assert dispatch["command_text"] == COMMAND


def test_clean_command_result_is_delivered_once_with_its_output(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]

    status, body, _ = _submit(state, row, termination="exited", exit_code=0,
                              body=STDOUT.encode("utf-8"))
    assert status == 200, body
    assert len(state.history_store.appended) == 1
    appended = state.history_store.appended[0]
    assert appended["status"] == "completed"
    assert appended["preserve_edges"] is True
    assert "종료 코드: 0" in appended["content"]
    assert "PowerShell" in appended["content"]
    # The PC output is preserved byte-for-byte inside the delimiters.
    assert STDOUT in appended["content"]

    # A duplicate submit is refused and appends nothing a second time.
    status, body, _ = _submit(state, row, termination="exited", exit_code=0,
                              body=STDOUT.encode("utf-8"))
    assert status == 409
    assert len(state.history_store.appended) == 1


def test_nonzero_exit_is_reported_as_a_real_failure(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(state, row, termination="exited", exit_code=3,
                              body=b"denied")
    assert status == 200, body
    appended = state.history_store.appended[0]
    assert appended["status"] == "failed"
    assert "종료 코드: 3" in appended["content"]
    assert state.history_store.finished[-1][1] == "failed"


def test_no_reply_never_invents_an_exit_code(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(state, row, termination="no_reply", exit_code=None,
                              body=b"")
    assert status == 200, body
    appended = state.history_store.appended[0]
    assert appended["status"] == "failed"
    assert "확인되지 않음" in appended["content"]
    assert "종료 코드: 0" not in appended["content"]


def test_exit_code_is_required_for_every_other_termination(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(state, row, termination="exited", exit_code=None,
                              body=b"")
    assert status == 400
    assert body["error"]["code"] == "oracle_mesh_invalid_body"


def test_read_lane_projection_is_unchanged(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    text = "PADIEM TXT\n"
    row = asyncio.run(state.history_store.create_oracle_mesh_dispatch(
        user_id=OWNER, run_id=RUN, command_id="c", tool_request_ref="t",
        request_id="r", revision_ref="rev", evidence_ref=None,
        request_fingerprint="f", account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        device_id=DEVICE, binding_ref=None, node_ref=NODE,
        root_ref="meshcentral_private_trial",
        path_relative="meshcentral-padiem-trial.txt", file_path=FILE_PATH,
        expires_at="2099-01-01T00:00:00.000Z",
    ))
    status, body, _ = _submit(state, row, termination="exited", exit_code=0,
                              body=text.encode("utf-8"))
    assert status == 200, body
    appended = state.history_store.appended[0]
    assert appended["status"] == "completed"
    # The read lane is wrapped in the same markers as a command result so its
    # own edges survive the shared history projection.
    assert appended["content"] == (
        "PC 파일 읽기 결과\n--- 출력 1/1 시작 ---\n" + text + "\n--- 출력 끝 ---"
    )
    assert appended["preserve_edges"] is False


def test_intent_requires_an_explicit_delimited_command():
    from app.claw_general_routes import _requested_local_command

    assert _requested_local_command("내 PC에서 `hostname.exe` 실행해줘") == (True, "hostname.exe")
    assert _requested_local_command("COM1에서 `hostname.exe` 실행해 주세요") == (True, "hostname.exe")
    # Prose about running something is not an execution order.
    assert _requested_local_command("내 PC에서 실행 계획을 알려줘") == (False, None)
    # No delimiter, two commands, or no PC marker: not this lane.
    assert _requested_local_command("내 PC에서 hostname.exe 실행해줘") == (False, None)
    assert _requested_local_command("내 PC에서 `a.exe` `b.exe` 실행해줘") == (False, None)
    assert _requested_local_command("`hostname.exe` 실행해줘") == (False, None)
    # A command is ordinary text: Korean, spaces and quotes are allowed.
    assert _requested_local_command("내 PC에서 `type 보고서.txt` 실행해줘") == (True, "type 보고서.txt")
    assert _requested_local_command('내 PC에서 `echo "한글 경로 테스트"` 실행해줘') == (
        True, 'echo "한글 경로 테스트"',
    )
    # NUL and carriage return never reach the PC.
    assert _requested_local_command("내 PC에서 `host\x00name` 실행해줘") == (False, None)
    assert _requested_local_command("내 PC에서 `host\rname` 실행해줘") == (False, None)


def test_timeout_is_stored_without_an_exit_code(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(state, row, termination="timed_out", exit_code=None,
                              body=b"partial output")
    assert status == 200, body
    appended = state.history_store.appended[0]
    assert appended["status"] == "failed"
    assert "대기 시간 초과" in appended["content"]
    assert "확인되지 않음" in appended["content"]
    assert "종료 코드: 0" not in appended["content"]
    assert state.history_store.finished[-1][1] == "failed"


def test_output_too_large_is_an_explicit_result(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, body, _ = _submit(state, row, termination="output_too_large", exit_code=0,
                              body=b"")
    assert status == 200, body
    appended = state.history_store.appended[0]
    assert appended["status"] == "completed"
    assert "전송 한도를 초과" in appended["content"]
    assert "종료 코드: 0" in appended["content"]
    assert "출력 시작" not in appended["content"]


def test_a_large_output_is_split_into_several_messages(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    lines = []
    for index in range(1500):
        lines.append("line-%04d" % index + "x" * 12)
    big = ("\n".join(lines) + "\n").encode("utf-8")
    status, body, _ = _submit(state, row, termination="exited", exit_code=0, body=big)
    assert status == 200, body
    appended = state.history_store.appended
    assert len(appended) > 1
    ids = [item["message_id"] for item in appended]
    assert len(set(ids)) == len(ids)
    assert all(item["message_id"].startswith("msg_ltr_") for item in appended)
    assert all(len(item["content"]) <= 8000 for item in appended)
    rebuilt = "\n".join(
        item["content"].split(" 시작 ---\n", 1)[1].rsplit("\n--- 출력 끝 ---", 1)[0]
        for item in appended
    )
    # Nothing is dropped or truncated: the parts rebuild the whole output.
    assert rebuilt == big.decode("utf-8")


def test_a_long_txt_read_is_split_and_preserved(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    row = asyncio.run(state.history_store.create_oracle_mesh_dispatch(
        user_id=OWNER, run_id=RUN, command_id="c", tool_request_ref="t",
        request_id="r", revision_ref="rev", evidence_ref=None,
        request_fingerprint="f", account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        device_id=DEVICE, binding_ref=None, node_ref=NODE,
        root_ref="meshcentral_private_trial",
        path_relative="보고서.txt", file_path="C:\\사용자\\보고서.txt",
        expires_at="2099-01-01T00:00:00.000Z",
    ))
    text = ("한글 문서 라인 " * 900 + "\n")
    status, body, _ = _submit(state, row, termination="exited", exit_code=0,
                              body=text.encode("utf-8"))
    assert status == 200, body
    appended = state.history_store.appended
    assert len(appended) > 1
    assert all(item["content"].startswith("PC 파일 읽기 결과") for item in appended)


def test_a_duplicate_submit_still_appends_nothing(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    big = ("y" * 9000 + "\n").encode("utf-8")
    _submit(state, row, termination="exited", exit_code=0, body=big)
    first = len(state.history_store.appended)
    status, body, _ = _submit(state, row, termination="exited", exit_code=0, body=big)
    assert status in (200, 409)
    assert len(state.history_store.appended) == first


def _big_body(parts=300, width=7380):
    lines = []
    for index in range(parts):
        lines.append("LINE-%06d-" % index + "x" * width)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _retrieve(state, dispatch_id):
    req = Request({}, state)
    req.path_params = {"dispatch_id": dispatch_id}
    response = asyncio.run(routes.oracle_mesh_read_original(req))
    return response.status_code, response.body, dict(response.headers)


def test_over_budget_output_is_stored_with_preview_and_retrievable(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    body = _big_body()
    digest = hashlib.sha256(body).hexdigest()
    status, payload, _ = _submit(state, row, termination="exited", exit_code=0, body=body)
    assert status == 200, payload
    # The original is stored before any completion is reported.
    assert state.history_store.originals.get(row["dispatch_id"]) == body
    assert state.history_store.finished[-1] == (row["dispatch_id"], "done")
    # The conversation carries one preview message with the retrieval ref.
    assert len(state.history_store.appended) == 1
    notice = state.history_store.appended[0]
    assert notice["status"] == "completed"
    assert notice["message_id"].startswith("msg_ltr_")
    assert "_p" not in notice["message_id"]
    assert "미리보기" in notice["content"]
    assert digest in notice["content"]
    assert str(len(body)) in notice["content"]
    assert ("/api/claw/connector/mesh-results/" + row["dispatch_id"]) in notice["content"]
    assert "dispatch에 그대로 보관" not in notice["content"]
    # The owner reads the whole original back: full bytes and digest match.
    status, raw, headers = _retrieve(state, row["dispatch_id"])
    assert status == 200
    assert raw == body
    assert headers.get("x-oracle-mesh-content-sha256") == digest
    assert headers.get("content-type", "").startswith("text/plain")


def test_original_retrieval_refuses_foreign_and_unknown_ids(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    body = _big_body()
    status, payload, _ = _submit(state, row, termination="exited", exit_code=0, body=body)
    assert status == 200, payload
    monkeypatch.setattr(routes, "current_user_id", lambda request: "foreign-user")
    status, _, _ = _retrieve(state, row["dispatch_id"])
    assert status == 404
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    status, _, _ = _retrieve(state, "dsp-unknown")
    assert status == 404


def test_original_store_failure_parks_and_retry_recovers(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    body = _big_body()
    state.history_store.fail_store = True
    status, payload, _ = _submit(state, row, termination="exited", exit_code=0, body=body)
    assert status == 503
    assert payload["error"]["code"] == "oracle_mesh_original_unavailable"
    assert row["state"] == "store_failed"
    assert state.history_store.appended == []
    assert state.history_store.finished == []
    # The resend carries the SAME bytes; the PC command is not re-run and no
    # completion was ever reported for the parked attempt.
    state.history_store.fail_store = False
    status, payload, _ = _submit(state, row, termination="exited", exit_code=0, body=body)
    assert status == 200, payload
    assert state.history_store.finished[-1] == (row["dispatch_id"], "done")
    assert state.history_store.originals[row["dispatch_id"]] == body
    assert len(state.history_store.appended) == 1


def test_withheld_output_states_non_delivery(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    status, payload, _ = _submit(state, row, termination="output_too_large", exit_code=0,
                                body=b"")
    assert status == 200, payload
    appended = state.history_store.appended[0]
    assert appended["status"] == "completed"
    assert "전송 한도를 초과" in appended["content"]
    assert "다시 조회할 수 없습니다" in appended["content"]
    assert "출력 시작" not in appended["content"]
    assert row["dispatch_id"] not in state.history_store.originals


def test_duplicate_over_budget_submit_appends_nothing(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    body = _big_body()
    status, payload, _ = _submit(state, row, termination="exited", exit_code=0, body=body)
    assert status == 200, payload
    status, payload, _ = _submit(state, row, termination="exited", exit_code=0, body=body)
    assert status == 409
    assert len(state.history_store.appended) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
