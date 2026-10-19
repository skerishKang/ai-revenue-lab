"""#5015 review: b62 Chat product thin PC drive lane.

The Chat lane reuses the shared Mesh tool contract (same pinned command,
same grant check, same verification vocabulary) under the Chat product
identity — never a Claw run, agent or authority. These tests pin the lane
boundaries: detector scope, model decision validation, agent plan shape and
the Chat/Claw product separation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.chat_pc_drive import (
    CHAT_PC_DRIVE_COMMAND,
    CHAT_PC_QUERY_AGENT_ID,
    CHAT_PC_QUERY_TOOL_ID,
    ChatPCDriveError,
    build_chat_pc_agent_plan,
    execute_chat_pc_drive_lane,
    is_chat_pc_drive_query,
    parse_chat_pc_tool_decision,
)
from app.orchestration_bridge import B62EngineOrchestrationBridge


def test_chat_file_detector_and_two_step_plan():
    """#4976: Chat routes a folder/file task to the shared list/read plan."""
    from app.chat_pc_drive import (
        build_chat_pc_files_agent_plan,
        is_chat_pc_files_query,
    )

    assert is_chat_pc_files_query(
        "내 PC의 테스트 폴더에서 파일 목록을 보고, TXT를 읽어서 내용을 설명해 주세요"
    )
    assert not is_chat_pc_files_query("내 PC에 어떤 드라이브가 있어?")
    assert not is_chat_pc_files_query("내 PC에서 `cmd /c hostname` 실행해줘")
    plan = build_chat_pc_files_agent_plan()
    assert plan["agent_id"] == "agent:padiem:chat-pc-query@1"
    assert [step["tool_id"] for step in plan["steps"]] == [
        "claw.pc.list_files", "claw.pc.read_file",
    ]


def test_chat_owner_uses_the_canonical_b62_session(monkeypatch):
    """The lane must present the same canonical session as the signed endpoint."""
    from app.chat_pc_drive import _resolve_chat_owner

    class _Session:
        product_id = "b62"
        session_id = "session.canonical.chat.1"
        tenant_id = "tenant-1"
        subject = SimpleNamespace(subject_id="sub_" + "a" * 32)

        def is_active(self, *, now=None):
            return True

    class _Authority:
        async def resolve_current_auth_session(self, *, product_id, product_user_id):
            assert product_id == "b62"
            assert product_user_id == "usr_1"
            return _Session()

    async def _workspace(request, uid):
        assert uid == "usr_1"
        return "tenant-ws-1"

    class _B54Session:
        session_id = "session.b54.canonical.1"
        tenant_id = "tenant-1"
        subject = SimpleNamespace(subject_id="sub_" + "a" * 32)

    class _Bridged:
        auth_session = _B54Session()

    async def _bridge(authority, uid):
        assert uid == "usr_1"
        return _Bridged()

    import padiem_control_plane.b54_identity_bridge as bridge_module

    monkeypatch.setattr(
        bridge_module, "resolve_current_b54_canonical_session", _bridge,
    )
    monkeypatch.setattr("app.claw_memory_routes._resolve_memory_workspace", _workspace)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=_Authority(),
    )))
    session, subject_id, workspace_id = asyncio.run(
        _resolve_chat_owner(request, "usr_1")
    )
    # The owner-scope lookup receives the shared B54 session, while the b62
    # subject still identifies the Chat product call to the Engine.
    assert session.session_id == "session.b54.canonical.1"
    assert subject_id == "sub_" + "a" * 32
    assert workspace_id == "tenant-ws-1"


def test_chat_owner_fails_closed_without_the_authority():
    from app.chat_pc_drive import _resolve_chat_owner

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert asyncio.run(_resolve_chat_owner(request, "usr_1")) == (
        None, "", "owner:usr_1",
    )


def test_chat_owner_refuses_an_inactive_session():
    from app.chat_pc_drive import _resolve_chat_owner

    class _Session:
        product_id = "b62"
        session_id = "session.canonical.chat.1"
        tenant_id = "tenant-1"
        subject = SimpleNamespace(subject_id="sub_" + "a" * 32)

        def is_active(self, *, now=None):
            return False

    class _Authority:
        async def resolve_current_auth_session(self, *, product_id, product_user_id):
            return _Session()

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=_Authority(),
    )))
    with pytest.raises(ChatPCDriveError):
        asyncio.run(_resolve_chat_owner(request, "usr_1"))


def test_detector_matches_only_drive_questions():
    assert is_chat_pc_drive_query("내 PC 드라이브 목록을 알려줘") is True
    assert is_chat_pc_drive_query("내 컴퓨터 디스크 용량 확인해줘") is True
    assert is_chat_pc_drive_query("my pc drive 확인해줘") is True
    # Explicit command lane stays explicit.
    assert is_chat_pc_drive_query("내 PC에서 `Get-PSDrive` 실행해줘") is False
    # Other nouns are out of scope for this lane.
    assert is_chat_pc_drive_query("내 PC에 데이터베이스가 있나?") is False
    assert is_chat_pc_drive_query("내 PC 호스트네임을 알려줘") is False
    # Screen/desktop verbs are a different lane.
    assert is_chat_pc_drive_query("내 PC 화면을 보여줘") is False
    assert is_chat_pc_drive_query("오늘 날씨 어때?") is False
    assert is_chat_pc_drive_query("") is False


def test_tool_decision_validation_mirrors_shared_contract():
    tool = json.dumps({
        "action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {},
    })
    assert parse_chat_pc_tool_decision(tool)["action"] == "tool"
    complete = json.dumps({"action": "complete", "answer": "연결된 PC가 없습니다."})
    assert parse_chat_pc_tool_decision(complete)["action"] == "complete"
    for bad in (
        "not json",
        json.dumps({"action": "tool"}),
        json.dumps({"action": "tool", "tool_id": "claw.desktop.capture", "arguments": {}}),
        json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {"x": 1}}),
        json.dumps({"action": "complete", "answer": 42}),
        json.dumps(["tool"]),
    ):
        with pytest.raises(ChatPCDriveError):
            parse_chat_pc_tool_decision(bad)


def test_chat_command_matches_shared_mesh_contract():
    # The Chat lane must dispatch byte-for-byte the same Mesh command the
    # Claw lane pins; the signed Chat endpoint re-checks this same string.
    assert CHAT_PC_DRIVE_COMMAND == (
        "Get-PSDrive -PSProvider FileSystem | "
        "Select-Object Name,Root,Used,Free | ConvertTo-Json"
    )


def test_chat_agent_plan_uses_shared_tool_under_chat_agent():
    plan = build_chat_pc_agent_plan()
    assert plan["agent_id"] == CHAT_PC_QUERY_AGENT_ID
    assert plan["agent_id"] != "agent:padiem:claw-pc-query@1"
    assert plan["steps"][0]["tool_id"] == CHAT_PC_QUERY_TOOL_ID


def test_bridge_request_carries_chat_agent_plan_and_subject():
    request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="usr_chat_1",
        messages=[{"role": "user", "content": "내 PC 드라이브 알려줘"}],
        skill=SimpleNamespace(id="chat", title="t", description="d",
                              system_instruction=None, task_type="general",
                              optimize_for="balanced", max_tokens=None),
        model_id="model-x",
        conversation_id="chat_" + "c" * 32,
        subject_id="sub_" + "a" * 32,
        session_id="chat_pcq_session1",
        agent_plan=build_chat_pc_agent_plan(),
    )
    assert request["subject_id"] == "sub_" + "a" * 32
    assert request["session_id"] == "chat_pcq_session1"
    assert request["agent_plan"]["agent_id"] == CHAT_PC_QUERY_AGENT_ID
    # Default path unchanged: product-local owner key and conversation session.
    plain = B62EngineOrchestrationBridge.build_engine_request(
        user_id="usr_chat_1",
        messages=[{"role": "user", "content": "hello"}],
        skill=SimpleNamespace(id="chat", title="t", description="d",
                              system_instruction=None, task_type="general",
                              optimize_for="balanced", max_tokens=None),
        model_id="model-x",
        conversation_id="chat_" + "c" * 32,
    )
    assert plain["subject_id"] == "usr_chat_1"
    assert plain["session_id"] == "chat_" + "c" * 32
    assert "agent_plan" not in plain


class _B14:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def complete(self, messages, skill, additional_system_context=None):
        self.calls.append(additional_system_context)
        return {"answer": self.answers.pop(0)}


class _Bridge(B62EngineOrchestrationBridge):
    def __init__(self, answer):
        super().__init__(client=object(), store=object())
        self.answer = answer
        self.requests = []

    async def start(self, **fields):
        self.requests.append(fields)
        return SimpleNamespace(answer=self.answer, public={"answer": self.answer})


class _History:
    def __init__(self):
        self.pairs = []
        self.staged = None
        self.appended = []

    async def append_exchange(self, user_id, conversation_id, user_text, answer, *, product_scope):
        assert product_scope == "b62-chat"
        self.pairs.append((user_text, answer))
        return conversation_id or ("chat_" + "n" * 32)

    async def record_chat_pc_drive_run(self, *, user_id, run_id, workspace_id, user_text, conversation_id):
        assert run_id.startswith("chat_pcq_")
        self.staged = {"run_id": run_id, "workspace_id": workspace_id}
        return conversation_id or ("chat_" + "s" * 32)

    async def get_claw_run(self, user_id, run_id):
        return {"run_id": run_id, "conversation_id": "chat_" + "s" * 32,
                "result_summary": "no_exit_code", "workspace_id": "tenant-1"}

    async def append_local_task_result(self, **fields):
        assert fields["summary"] == "no_exit_code"
        assert fields["message_id"].endswith("_answer")
        self.appended.append(fields)
        return True


def _request(*, user="usr_chat_1", model_answers, engine_answer="C: 드라이브가 있습니다."):
    b14 = _B14(model_answers)
    bridge = _Bridge(engine_answer)
    history = _History()
    state = SimpleNamespace(
        b14_client=b14, orchestration_bridge=bridge, history_store=history,
        identity_shadow_store=object(), control_plane_identity_authority=object(),
        oracle_mesh_return_source=SimpleNamespace(execution_mode="mesh"),
        settings=SimpleNamespace(auth_mode="mock"),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=state),
        cookies={"padiem_session": "signed-" + user} if user else {},
    )
    return request, b14, bridge, history


def test_lane_falls_through_for_anonymous_or_non_drive():
    import app.chat_pc_drive as lane

    async def run():
        old_ready, old_uid = lane.auth_ready, lane.current_user_id
        lane.auth_ready = lambda req: False
        lane.current_user_id = lambda req: None
        try:
            anon = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
            # No signed-in user falls through.
            assert await lane.execute_chat_pc_drive_lane(
                anon, user_text="내 PC 드라이브 알려줘", skill=None,
                model_id="m", conversation_id=None, tier="free",
            ) is None
        finally:
            lane.auth_ready, lane.current_user_id = old_ready, old_uid
        # A signed-in user asking something else falls through too.
        request, _, _, _ = _request(model_answers=["unused"])
        lane.auth_ready = lambda req: True
        lane.current_user_id = lambda req: "usr_chat_1"
        try:
            assert await lane.execute_chat_pc_drive_lane(
                request, user_text="오늘 날씨 어때?", skill=None,
                model_id="m", conversation_id=None, tier="free",
            ) is None
        finally:
            lane.auth_ready, lane.current_user_id = old_ready, old_uid
    asyncio.run(run())


def test_lane_tool_path_stages_chat_run_and_records_answer():
    import app.chat_pc_drive as lane

    tool_decision = json.dumps({
        "action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {},
    })
    request, b14, bridge, history = _request(model_answers=[tool_decision])

    async def fake_owner(req, uid):
        session = SimpleNamespace(session_id="sess-b62-1", tenant_id="tenant-1",
                                  subject=SimpleNamespace(subject_id="sub_" + "a" * 32))
        return session, "sub_" + "a" * 32, "tenant-1"

    async def fake_grant(req, session):
        return (object(), "acc-1", "node-1")

    old_ready, old_uid = lane.auth_ready, lane.current_user_id
    old_owner, old_grant = lane._resolve_chat_owner, lane._check_mesh_grant
    lane.auth_ready = lambda req: True
    lane.current_user_id = lambda req: "usr_chat_1"
    lane._resolve_chat_owner, lane._check_mesh_grant = fake_owner, fake_grant
    try:
        result = asyncio.run(lane.execute_chat_pc_drive_lane(
            request, user_text="내 PC 드라이브 목록 알려줘", skill=None,
            model_id="model-x", conversation_id=None, tier="free",
        ))
    finally:
        lane.auth_ready, lane.current_user_id = old_ready, old_uid
        lane._resolve_chat_owner, lane._check_mesh_grant = old_owner, old_grant
    assert result is not None
    answer, conversation_id = result
    assert "C:" in answer
    assert conversation_id == "chat_" + "s" * 32
    # Engine got the Chat product lane: chat agent, chat session, canonical subject.
    sent = bridge.requests[0]
    assert sent["agent_plan"]["agent_id"] == CHAT_PC_QUERY_AGENT_ID
    assert sent["subject_id"] == "sub_" + "a" * 32
    assert sent["session_id"].startswith("chat_pcq_")
    assert sent["user_id"] == "usr_chat_1"
    # Staged run is a Chat run, and the final answer reused the stored summary.
    assert history.staged["run_id"].startswith("chat_pcq_")
    assert history.appended and history.appended[0]["run_id"] == history.staged["run_id"]


class _SignedRequest:
    def __init__(self, state, payload, *, secret):
        import hashlib as _hashlib
        import hmac as _hmac
        import time as _time

        raw = json.dumps(payload).encode("utf-8")
        stamp = str(int(_time.time()))
        proof = _hmac.new(
            secret.encode("utf-8"), stamp.encode("ascii") + b"." + raw,
            _hashlib.sha256,
        ).hexdigest()
        self.app = SimpleNamespace(state=state)
        self.headers = {
            "X-Claw-Engine-Time": stamp,
            "X-Claw-Engine-Proof": proof,
        }
        self._data = raw

    async def body(self):
        return self._data


_CHAT_OWNER = "usr_chat_9"
_CHAT_SUBJECT = "sub_" + "b" * 32
_CHAT_ACCOUNT = "account-chat-9"
_CHAT_WORKSPACE = "tenant-chat-9"
_CHAT_RUN = "chat_pcq_" + "r" * 24
_CHAT_CONVERSATION = "chat_" + "9" * 32
_CHAT_SECRET = "s" * 32
_CHAT_CHANNEL_SECRET = "deployment-channel-secret-value-chat"


class _ChatIdentity:
    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == "b62"
        assert canonical_subject_id == _CHAT_SUBJECT
        return _CHAT_OWNER

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        assert product_id == "b62"
        assert product_user_id == _CHAT_OWNER
        return SimpleNamespace(
            session_id="sess-chat-9",
            product_id="b62",
            subject=SimpleNamespace(subject_id=_CHAT_SUBJECT),
            tenant_id=_CHAT_WORKSPACE,
            is_active=lambda *, now: True,
        )

    async def resolve_connector_owner_scope(self, *, session_id):
        assert session_id == "sess-chat-9"
        return {"account_ref": _CHAT_ACCOUNT, "workspace_ref": _CHAT_WORKSPACE}


class _ChatHistory:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._seq = 0

    async def get_claw_run(self, user_id, run_id):
        if user_id != _CHAT_OWNER or run_id != _CHAT_RUN:
            return None
        return {"run_id": _CHAT_RUN, "conversation_id": _CHAT_CONVERSATION,
                "workspace_id": _CHAT_WORKSPACE, "status": "pending"}

    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return None

    async def create_oracle_mesh_dispatch(self, **fields):
        self._seq += 1
        dispatch_id = "chat-dsp-%d" % self._seq
        row = {**fields, "dispatch_id": dispatch_id, "state": "pending",
               "nonce_sha256": None, "result_sha256": None, "result_bytes": None,
               "termination": None, "exit_code": None}
        self.rows[dispatch_id] = row
        return dict(row)

    async def record_oracle_mesh_first_result(self, *, dispatch_id, content_sha256,
                                              content_bytes, termination=None, exit_code=None):
        row = self.rows.get(dispatch_id)
        if row is None:
            return False
        if row.get("result_sha256") is None:
            row["result_sha256"] = content_sha256
            row["result_bytes"] = content_bytes
            row["termination"] = termination
            row["exit_code"] = exit_code
            return True
        return row["result_sha256"] == content_sha256

    async def mark_oracle_mesh_store_failed(self, *, dispatch_id):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("state") != "received":
            return False
        row["state"] = "store_failed"
        return True

    async def finish_oracle_mesh_dispatch(self, *, dispatch_id, outcome):
        row = self.rows.get(dispatch_id)
        if row is not None:
            row["state"] = outcome
        return True

    async def store_oracle_mesh_command_result(self, *, user_id, dispatch_id,
                                               conversation_id, message_id,
                                               raw, expected_sha256, expected_bytes):
        row = self.rows.get(dispatch_id)
        assert row is not None and row.get("user_id") == user_id
        data = raw.encode("utf-8")
        assert len(data) == expected_bytes
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        self.rows[dispatch_id + ":original"] = data
        return "chat-key"

    async def read_oracle_mesh_original(self, *, user_id, dispatch_id,
                                        conversation_id, message_id):
        data = self.rows.get(dispatch_id + ":original")
        if data is None:
            return None
        return data, hashlib.sha256(data).hexdigest()

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id, dispatch_id):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return dict(row)

    async def consume_oracle_mesh_dispatch(self, *, dispatch_id, nonce):
        import hashlib as _hashlib

        row = self.rows.get(dispatch_id)
        if row is None or not row.get("nonce_sha256"):
            return None
        if _hashlib.sha256(nonce.encode("utf-8")).hexdigest() != row["nonce_sha256"]:
            return None
        if row["state"] != "pending":
            return None
        row["state"] = "received"
        return {**dict(row), "claim": "first"}

    async def store_oracle_mesh_original(self, **fields):
        raise AssertionError("small Chat outputs must use the command-result store")

    async def append_local_task_result(self, **fields):
        self.rows.setdefault("appended", []).append(fields)
        return True


def _chat_mapping():
    # Ownership rows are TXT grants; the command lane reuses the row carrying
    # the command_exec grant, mirroring the Claw lane's deployment shape.
    return [{
        "account_ref": _CHAT_ACCOUNT, "device_id": "chat-device-1",
        "node_ref": "chat-node-1",
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "file_path": "C:\\padiem\\meshcentral-padiem-trial.txt",
        "command_exec": True,
    }]


def _chat_state():
    from app import oracle_mesh_read_return_routes as routes

    source = routes.build_oracle_mesh_return_source(
        _chat_mapping(), _CHAT_CHANNEL_SECRET, routes.EXECUTION_MODE_MESH)
    assert source is not None
    return SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=_ChatIdentity(),
        history_store=_ChatHistory(),
        connector_txt_read_source=None,
        claw_engine_desktop_secret=_CHAT_SECRET,
    ), routes


def _signed_chat_call(state, routes, payload):
    response = asyncio.run(routes.oracle_chat_engine_pc_drive_call(
        _SignedRequest(state, payload, secret=_CHAT_SECRET)))
    return response.status_code, json.loads(response.body)


async def _chat_workspace(request, uid):
    return _CHAT_WORKSPACE if uid == _CHAT_OWNER else None


def test_chat_signed_dispatch_status_result_loop(monkeypatch):
    state, routes = _chat_state()
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _chat_workspace)

    status, body = _signed_chat_call(state, routes, {
        "subject_id": _CHAT_SUBJECT, "run_id": _CHAT_RUN, "device_id": None,
        "command": CHAT_PC_DRIVE_COMMAND, "mode": "dispatch",
    })
    assert status == 200, body
    assert body["dispatch"]["kind"] == "command"
    dispatch_id = body["dispatch"]["dispatch_id"]
    assert state.history_store.rows[dispatch_id]["account_ref"] == _CHAT_ACCOUNT

    status, body = _signed_chat_call(state, routes, {
        "subject_id": _CHAT_SUBJECT, "run_id": _CHAT_RUN,
        "dispatch_id": dispatch_id, "mode": "command_status",
    })
    assert status == 200, body
    assert body["dispatch"]["state"] == "pending"
    assert body["dispatch"]["kind"] == "command"

    # The executor submission path is product-agnostic: the staged Chat run
    # row resolves the conversation exactly like a Claw run row.
    row = state.history_store.rows[dispatch_id]
    row["nonce_sha256"] = hashlib.sha256(b"n" * 32).hexdigest()
    output = json.dumps([{"Name": "C", "Root": "C:\\"}])
    digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
    submit_payload = {
        "dispatch_id": dispatch_id, "nonce": "n" * 32,
        "termination": "no_exit_code", "exit_code": None,
        "content_utf8": output, "content_sha256": digest,
        "content_bytes": len(output.encode("utf-8")),
    }
    submit_raw = json.dumps(submit_payload).encode("utf-8")

    submit_request = SimpleNamespace(
        app=SimpleNamespace(state=state),
        headers={
            "content-type": "application/json",
            "content-length": str(len(submit_raw)),
            routes.ORACLE_MESH_CHANNEL_HEADER: _CHAT_CHANNEL_SECRET,
        },
    )

    async def submit_body():
        return submit_raw

    submit_request.body = submit_body
    response = asyncio.run(routes.oracle_mesh_read_result(submit_request))
    assert response.status_code == 200, response.body
    assert state.history_store.rows[dispatch_id]["termination"] == "no_exit_code"

    status, body = _signed_chat_call(state, routes, {
        "subject_id": _CHAT_SUBJECT, "run_id": _CHAT_RUN,
        "dispatch_id": dispatch_id, "mode": "result",
    })
    assert status == 200, body
    assert body["dispatch"]["output"] == output
    assert body["dispatch"]["termination"] == "no_exit_code"
    assert body["dispatch"]["exit_code"] is None


def test_chat_signed_endpoint_rejects_claw_product_and_wrong_command(monkeypatch):
    state, routes = _chat_state()
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _chat_workspace)

    status, body = _signed_chat_call(state, routes, {
        "subject_id": _CHAT_SUBJECT, "run_id": _CHAT_RUN,
        "dispatch_id": "chat-dsp-9", "mode": "status",
    })
    # Desktop/status modes do not exist on the Chat drive lane.
    assert status == 400

    status, body = _signed_chat_call(state, routes, {
        "subject_id": _CHAT_SUBJECT, "run_id": _CHAT_RUN, "device_id": None,
        "command": "hostname.exe", "mode": "dispatch",
    })
    assert status == 400


def test_lane_complete_decision_answers_without_engine():
    import app.chat_pc_drive as lane

    request, b14, bridge, history = _request(
        model_answers=[json.dumps({"action": "complete", "answer": "연결된 PC가 없습니다."})],
        engine_answer="unused",
    )

    async def fake_owner(req, uid):
        session = SimpleNamespace(session_id="sess-b62-1", tenant_id="tenant-1",
                                  subject=SimpleNamespace(subject_id="sub_" + "a" * 32))
        return session, "sub_" + "a" * 32, "tenant-1"

    async def fake_grant(req, session):
        return (object(), "acc-1", "node-1")

    old_ready, old_uid = lane.auth_ready, lane.current_user_id
    old_owner, old_grant = lane._resolve_chat_owner, lane._check_mesh_grant
    lane.auth_ready = lambda req: True
    lane.current_user_id = lambda req: "usr_chat_1"
    lane._resolve_chat_owner, lane._check_mesh_grant = fake_owner, fake_grant
    try:
        result = asyncio.run(lane.execute_chat_pc_drive_lane(
            request, user_text="내 PC 드라이브 알려줘", skill=None,
            model_id="model-x", conversation_id=None, tier="free",
        ))
    finally:
        lane.auth_ready, lane.current_user_id = old_ready, old_uid
        lane._resolve_chat_owner, lane._check_mesh_grant = old_owner, old_grant
    assert result is not None
    assert result[0] == "연결된 PC가 없습니다."
    assert bridge.requests == []
    assert history.staged is None

def test_5015_mesh_grant_internal_diagnostics_are_fixed_codes_only(caplog):
    """Observe which existing gate refused, without exposing account/session values."""
    import app.chat_pc_drive as lane

    private_session = "PRIVATE_SESSION_DO_NOT_LOG"
    private_account = "PRIVATE_ACCOUNT_DO_NOT_LOG"
    session = SimpleNamespace(session_id=private_session)

    class Identity:
        async def resolve_connector_owner_scope(self, *, session_id):
            assert session_id == private_session
            return {"account_ref": private_account}

    class BrokenIdentity:
        async def resolve_connector_owner_scope(self, *, session_id):
            raise RuntimeError("SENSITIVE_PROVIDER_FAILURE_DO_NOT_LOG")

    class NoAccount:
        async def resolve_connector_owner_scope(self, *, session_id):
            return {"account_ref": ""}

    class Source:
        execution_mode = "mesh"
        configured = True

        def __init__(self, result=None, fail=False):
            self.result = result
            self.fail = fail

        def command_target(self, *, account_ref, device_id):
            assert account_ref == private_account and device_id is None
            if self.fail:
                raise RuntimeError("SENSITIVE_LOOKUP_FAILURE_DO_NOT_LOG")
            return self.result

    def check(reason, *, sess=session, source=None, identity=None):
        state = SimpleNamespace(
            oracle_mesh_return_source=source,
            control_plane_identity_authority=identity,
        )
        caplog.clear()
        result = asyncio.run(lane._check_mesh_grant(
            SimpleNamespace(app=SimpleNamespace(state=state)), sess,
        ))
        assert result is False
        assert caplog.messages == ["chat_pc_mesh_grant_denied=" + reason]
        assert "PRIVATE_" not in caplog.text
        assert "SENSITIVE_" not in caplog.text

    caplog.set_level("WARNING", logger="app.chat_pc_drive")
    check("canonical_session_absent", sess=None)
    check("mesh_source_unconfigured")
    check("mesh_source_unconfigured", source=SimpleNamespace(configured=False))
    check("mesh_mode_unavailable", source=SimpleNamespace(execution_mode="off"))
    check("identity_authority_unavailable", source=Source())
    check("owner_scope_resolution_failed", source=Source(), identity=BrokenIdentity())
    check("owner_scope_account_unavailable", source=Source(), identity=NoAccount())
    check("mesh_command_target_lookup_failed", source=Source(fail=True), identity=Identity())
    check("mesh_command_target_not_unique", source=Source(), identity=Identity())

    caplog.clear()
    ok_state = SimpleNamespace(
        oracle_mesh_return_source=Source(result={"node_ref": "node"}),
        control_plane_identity_authority=Identity(),
    )
    assert asyncio.run(lane._check_mesh_grant(
        SimpleNamespace(app=SimpleNamespace(state=ok_state)), session,
    )) is True
    assert caplog.messages == []
