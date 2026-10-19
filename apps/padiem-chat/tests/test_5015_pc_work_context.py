"""#5015: a new Chat/Claw turn recognizes the verified PC *and* its target.

The context reads two different authorities and keeps them separate:

* the canonical Broker directory (what the account registered / what the UI
  shows), and
* the deployment-owned Mesh command target (which PC may actually execute).

An empty Broker list never demotes a working Mesh target to "unregistered",
an online badge never becomes tool permission, and a selected device is used
only when it resolves to the exact Mesh target that dispatch will receive.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from starlette.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session_token
from app.chat_pc_drive import CHAT_PC_QUERY_TOOL_ID, ChatPCDriveError, execute_chat_pc_drive_lane
from app.config import Settings
from app.main import create_app
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.pc_work_context import (
    MAX_RENDERED_CHARS,
    PC_DRIVE_TOOL_ID,
    PC_WORK_CONTEXT_VERSION,
    SAVED_SELECTION_NONE,
    SAVED_SELECTION_SELECTED,
    SAVED_SELECTION_UNAVAILABLE,
    SAVED_SELECTION_UNCONFIGURED,
    build_pc_work_context_text,
    load_saved_device_selection,
    read_saved_device_selection,
    render_pc_work_context,
    resolve_pc_work_context,
)

OWNER = "usr_" + "7" * 32
OTHER_OWNER = "usr_" + "8" * 32
WORKSPACE = "tenant-5015"
SESSION = "sess-5015"
CONNECTOR_ACCOUNT = "acct-5015"
BASE = "https://chat.example.test"


def device(device_id="office-pc", *, name="Office PC", state="CONNECTED", usable=None, paused=None):
    row = {
        "deviceId": device_id,
        "deviceName": name,
        "state": state,
        "usable": (state == "CONNECTED") if usable is None else usable,
    }
    if paused is not None:
        row["usagePaused"] = paused
    return row


class Directory:
    configured = True

    def __init__(self, rows=None, *, raises=False):
        self.rows = list(rows or [])
        self.raises = raises
        self.calls: list[dict] = []

    async def list_devices(self, *, owner_id, workspace_id, now):
        self.calls.append({"owner_id": owner_id, "workspace_id": workspace_id})
        if self.raises:
            raise RuntimeError("SECRET_BROKER_PATH")
        return list(self.rows)


class Identity:
    def __init__(self, account_ref=CONNECTOR_ACCOUNT, *, raises=False):
        self.account_ref = account_ref
        self.raises = raises
        self.calls: list[str] = []

    async def resolve_connector_owner_scope(self, *, session_id):
        self.calls.append(session_id)
        if self.raises:
            raise RuntimeError("SECRET_SCOPE_PATH")
        return {"account_ref": self.account_ref, "workspace_ref": "ws-connector"}


class Mesh:
    """Mirror of ``OracleMeshReturnSource.command_target`` matching rules."""

    configured = True

    def __init__(
        self, rows=None, *, execution_mode="mesh", configured=True, raises=False,
    ):
        self.rows = list(rows or [])
        self.execution_mode = execution_mode
        self.configured = configured
        self.raises = raises
        self.calls: list[dict] = []

    def command_target(self, *, account_ref, device_id=None):
        self.calls.append({"account_ref": account_ref, "device_id": device_id})
        if self.raises:
            raise RuntimeError("SECRET_MESH_PATH")
        matches = [
            row for row in self.rows
            if row["account_ref"] == account_ref
            and row.get("command_exec", True) is True
            and (
                device_id is None
                or row.get("device_id") == device_id
                or row.get("device_id") is None
                or row["node_ref"] == device_id
            )
        ]
        return dict(matches[0]) if len(matches) == 1 else None


def mesh_row(device_id="office-pc", *, node_ref="node-office", account=CONNECTOR_ACCOUNT, command=True):
    return {
        "account_ref": account,
        "device_id": device_id,
        "node_ref": node_ref,
        "command_exec": command,
    }


def request_for(source, *, mesh=None, identity=None, owner_state=None):
    state = SimpleNamespace(
        claw_device_directory_source=source,
        oracle_mesh_return_source=mesh,
        control_plane_identity_authority=identity,
    )
    if owner_state is not None:
        for name, value in owner_state.items():
            setattr(state, name, value)
    return SimpleNamespace(app=SimpleNamespace(state=state), cookies={"padiem_session": "x"})


def resolve(source, *, mesh=None, identity=None, owner=OWNER, workspace=WORKSPACE,
            session=SESSION, selected=None):
    return asyncio.run(resolve_pc_work_context(
        request_for(source, mesh=mesh, identity=identity),
        owner_id=owner, workspace_id=workspace, session_id=session,
        selected_device_id=selected,
    ))


def text_for(source, *, mesh=None, identity=None, selected=None):
    return asyncio.run(build_pc_work_context_text(
        request_for(source, mesh=mesh, identity=identity),
        owner_id=OWNER, workspace_id=WORKSPACE, session_id=SESSION,
        selected_device_id=selected,
    ))


def ready(**kwargs):
    kwargs.setdefault("mesh", Mesh([mesh_row()]))
    kwargs.setdefault("identity", Identity())
    return resolve(Directory([device()]), **kwargs)


# --- one explicit target, never first-of-many -------------------------------


def test_single_online_broker_with_matching_mesh_target_is_confirmed():
    context = ready()
    assert context.broker_status == "ready"
    assert context.execution.status == "ready"
    assert context.execution_device_id == "office-pc"
    assert context.mapping == "confirmed"
    assert context.tool_available is True
    rendered = render_pc_work_context(context)
    assert PC_WORK_CONTEXT_VERSION in rendered
    assert "현재 작업 대상 PC: Office PC (등록 기기와 일치)" in rendered
    assert PC_DRIVE_TOOL_ID in rendered
    assert "이 대상 PC에서만 실행됩니다" in rendered


def test_two_online_devices_are_ambiguous_and_never_first_of_many():
    context = resolve(
        Directory([device("aaa-first", name="First"), device("zzz-second", name="Second")]),
        mesh=Mesh([mesh_row("aaa-first", node_ref="node-first")]),
        identity=Identity(),
    )
    assert context.execution.status == "ready"
    assert context.mapping == "unmapped"
    assert context.broker_target_device_id is None
    rendered = render_pc_work_context(context)
    assert "현재 작업 대상 PC" not in rendered
    assert "등록 기기와 일치" not in rendered


def test_offline_broker_heartbeat_stays_separate_from_execution_target():
    # The Broker heartbeat is offline, but the deployment still maps a valid
    # command target. That is not "no tools" and not "online".
    context = resolve(
        Directory([device(state="OFFLINE")]),
        mesh=Mesh([mesh_row()]), identity=Identity(),
    )
    assert context.broker_status == "offline"
    assert context.execution.status == "ready"
    assert context.mapping == "unmapped"
    rendered = render_pc_work_context(context)
    assert "온라인 상태가 확인되지 않았습니다" in rendered
    assert "서버 실행 대상 PC: office-pc" in rendered


def test_paused_usage_offers_no_tool_even_with_a_ready_target():
    context = resolve(
        Directory([device(paused=True)]),
        mesh=Mesh([mesh_row()]), identity=Identity(),
    )
    assert context.broker_status == "paused"
    # Identity may still be confirmed; permission is what paused removes.
    assert context.mapping == "confirmed"
    assert context.tool_available is False
    rendered = render_pc_work_context(context)
    assert "일시중지" in rendered
    assert PC_DRIVE_TOOL_ID not in rendered


def test_revoked_device_never_becomes_a_target():
    context = resolve(
        Directory([device(state="REVOKED")]),
        mesh=Mesh([mesh_row()]), identity=Identity(),
    )
    assert context.broker_status == "offline"
    assert context.execution.status == "ready"
    assert context.broker_target_device_id is None


# --- Broker and Mesh disagreement ------------------------------------------


def test_empty_broker_list_with_a_valid_mesh_target_is_not_unregistered():
    context = resolve(Directory([]), mesh=Mesh([mesh_row()]), identity=Identity())
    assert context.broker_status == "no_device"
    assert context.execution.status == "ready"
    assert context.execution_device_id == "office-pc"
    assert context.mapping == "unmapped"
    assert context.tool_available is True
    rendered = render_pc_work_context(context)
    assert "등록 기기 목록에서 확인된 PC가 없습니다" in rendered
    assert "서버 실행 대상 PC: office-pc" in rendered
    assert "등록되지 않았다고 단정하지 마세요" in rendered
    assert PC_DRIVE_TOOL_ID in rendered
    assert "이 대상 PC에서만 실행됩니다" not in rendered


def test_unreadable_broker_does_not_become_no_tools_when_mesh_is_ready():
    context = resolve(Directory(raises=True), mesh=Mesh([mesh_row()]), identity=Identity())
    assert context.broker_status == "read_failed"
    assert context.execution.status == "ready"
    assert context.tool_available is True
    rendered = render_pc_work_context(context)
    assert "등록 기기 목록 조회에 실패" in rendered
    assert "서버 실행 대상 PC: office-pc" in rendered
    assert PC_DRIVE_TOOL_ID in rendered


def test_online_broker_without_a_mesh_target_has_no_tool_claim():
    for mesh in (
        None,
        Mesh([], configured=False),
        Mesh([], execution_mode="off"),
        Mesh([], execution_mode="native"),
        Mesh([mesh_row(command=False)]),
    ):
        context = resolve(Directory([device()]), mesh=mesh, identity=Identity())
        assert context.execution.status in ("unconfigured", "no_target"), mesh
        assert context.tool_available is False
        rendered = render_pc_work_context(context)
        assert PC_DRIVE_TOOL_ID not in rendered
        assert "실행" in rendered, "the refusal must name execution, not connection"
    # An online badge alone never names the tool.
    rendered = render_pc_work_context(resolve(Directory([device()]), mesh=None, identity=Identity()))
    assert "실행 권한" in rendered or "실행 구성" in rendered


def test_broker_and_mesh_id_mismatch_does_not_claim_this_pc_only():
    context = resolve(
        Directory([device("broker-pc", name="Broker PC")]),
        mesh=Mesh([mesh_row(None, node_ref="mesh-node")]),
        identity=Identity(),
    )
    assert context.execution_device_id == "mesh-node"
    assert context.mapping == "identity_unconfirmed"
    rendered = render_pc_work_context(context)
    assert "직접적인 식별자 대응은 확인되지 않았습니다" in rendered
    assert "이 대상 PC에서만 실행됩니다" not in rendered


# --- explicit selection round-trip -----------------------------------------


def test_selected_device_equal_to_the_mesh_target_is_confirmed():
    context = resolve(
        Directory([device("office-pc")]),
        mesh=Mesh([mesh_row()]), identity=Identity(), selected="office-pc",
    )
    assert context.selected_confirmed is True
    assert context.mapping == "confirmed"
    assert context.execution_device_id == "office-pc"
    assert context.tool_available is True


def test_selected_device_mismatch_is_refused_not_retargeted():
    # The Mesh row is unpinned, so command_target structurally matches any
    # selection; identity is still unproven and must not be claimed.
    context = resolve(
        Directory([device("selected-pc", name="Selected")]),
        mesh=Mesh([mesh_row(None, node_ref="mesh-node")]),
        identity=Identity(), selected="selected-pc",
    )
    assert context.selected_confirmed is False
    assert context.mapping == "mismatch"
    assert context.tool_available is False
    rendered = render_pc_work_context(context)
    assert "일치하지 않습니다" in rendered
    assert PC_DRIVE_TOOL_ID not in rendered


def test_selected_device_without_any_target_is_refused():
    context = resolve(
        Directory([device("selected-pc")]), mesh=Mesh([]), identity=Identity(),
        selected="selected-pc",
    )
    assert context.execution.status == "no_target"
    assert context.selected_confirmed is False
    assert context.tool_available is False


# --- fail closed on malformed or foreign input -----------------------------


def test_unverified_owner_never_reads_either_authority():
    source, mesh, identity = Directory([device()]), Mesh([mesh_row()]), Identity()
    context = resolve(source, mesh=mesh, identity=identity, owner=None)
    assert context.broker_status == "unverified_owner"
    assert source.calls == [] and mesh.calls == [] and identity.calls == []


def test_malformed_broker_rows_fail_closed():
    for row in (
        {"deviceId": "bad/path", "state": "CONNECTED", "usable": True},
        {"deviceId": "a", "state": "CONNECTED", "usable": False},
        {"deviceId": "a", "state": "MAGIC", "usable": False},
        {"deviceId": "a", "state": "CONNECTED", "usable": "true"},
        "not-a-row",
    ):
        assert resolve(Directory([row]), mesh=Mesh([mesh_row()]), identity=Identity()).broker_status == "read_failed", row


def test_conflicting_pause_flags_fail_closed():
    assert resolve(
        Directory([device("a", paused=True), device("b", paused=False)]),
        mesh=Mesh([mesh_row("a", node_ref="n-a")]), identity=Identity(),
    ).broker_status == "read_failed"


def test_malformed_mesh_target_fails_closed():
    for rows in (
        [{"account_ref": CONNECTOR_ACCOUNT, "device_id": None, "node_ref": "bad node", "command_exec": True}],
        [{"account_ref": CONNECTOR_ACCOUNT, "device_id": "bad*path", "node_ref": "n", "command_exec": True}],
    ):
        context = resolve(Directory([device()]), mesh=Mesh(rows), identity=Identity())
        assert context.execution.status == "no_target"
        assert context.tool_available is False


def test_owner_scope_failure_is_not_a_tool_claim():
    context = resolve(
        Directory([device()]), mesh=Mesh([mesh_row()]), identity=Identity(raises=True),
    )
    assert context.execution.status == "owner_unavailable"
    assert context.tool_available is False
    assert "SECRET_SCOPE_PATH" not in render_pc_work_context(context)


# --- owner isolation and bounded rendering ---------------------------------


def test_each_request_resolves_its_own_owner_and_workspace():
    first_source, second_source = Directory([device("first")]), Directory([device("second")])
    first = resolve(first_source, mesh=Mesh([mesh_row("first", node_ref="first")]), identity=Identity())
    second = resolve(second_source, owner=OTHER_OWNER, mesh=Mesh([mesh_row("second", node_ref="second")]), identity=Identity())
    assert first.execution_device_id == "first"
    assert second.execution_device_id == "second"
    assert first_source.calls == [{"owner_id": OWNER, "workspace_id": WORKSPACE}]
    assert second_source.calls == [{"owner_id": OTHER_OWNER, "workspace_id": WORKSPACE}]


def test_render_is_bounded_and_carries_no_secret_identifier():
    rows = [device(f"pc-{index}", name="긴 이름 " * 20) for index in range(23)]
    for row in rows:
        row["state"] = "OFFLINE"
        row["usable"] = False
    rows.append(device("target", name="Target"))
    rendered = render_pc_work_context(resolve(
        Directory(rows), mesh=Mesh([mesh_row("target", node_ref="target")]), identity=Identity(),
    ))
    assert len(rendered) <= MAX_RENDERED_CHARS
    assert "Target" in rendered
    assert OWNER not in rendered and WORKSPACE not in rendered
    assert CONNECTOR_ACCOUNT not in rendered and SESSION not in rendered
    assert "외 18대" in rendered


def test_device_name_control_characters_are_stripped():
    rendered = render_pc_work_context(resolve(
        Directory([device("pc", name="Office\r\nPC\x00")]),
        mesh=Mesh([mesh_row("pc", node_ref="pc")]), identity=Identity(),
    ))
    assert "OfficePC" in rendered
    assert "\r" not in rendered and "\x00" not in rendered


# --- the context and the target reach the actual model/dispatch ------------


def _claw_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": BASE,
        "google_client_id": "claw-pc-context.apps.googleusercontent.com",
        "google_client_secret": "claw-pc-context-google-secret",
        "session_secret": "claw-pc-context-session-secret-not-a-real-credential",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


class _AuthStore:
    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        return None


def _claw_outcome():
    status_mock = MagicMock()
    status_mock.value = "completed"
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = "run_general"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = "P01 결과"
    outcome.p01_run_id = "p01_general"
    outcome.p01_event_count = 1
    return outcome


@contextmanager
def _claw_client(source, *, mesh=None, identity=None, selection_store=None):
    adapter = MagicMock()
    adapter.subject_identity_lane = False
    adapter.execute = AsyncMock(return_value=_claw_outcome())
    config = _claw_settings()
    app = create_app(
        settings=config, history_store=_AuthStore(),
        claw_p01_adapter=adapter, claw_device_directory_source=source,
        claw_pc_device_selection_store=selection_store,
    )
    app.state.oracle_mesh_return_source = mesh
    app.state.control_plane_identity_authority = identity
    client = TestClient(app, base_url=BASE)
    client.cookies.set(
        SESSION_COOKIE, create_session_token(config, OWNER),
        domain="chat.example.test", path="/",
    )
    with client:
        yield client, adapter


def test_claw_general_dispatch_carries_the_verified_pc_context():
    source = Directory([device()])
    # Both identity components absent keeps the compatibility workspace, so the
    # Broker directory is really read; the Mesh owner scope stays unverified.
    with _claw_client(source, mesh=Mesh([mesh_row()]), identity=None) as (client, adapter):
        response = client.post(
            "/api/claw/general",
            headers={"Origin": BASE},
            json={"messages": [{"role": "user", "content": "일반 질문입니다."}], "tier": "plus"},
        )
    assert response.status_code == 200, response.text
    adapter.execute.assert_awaited_once()
    context = adapter.execute.await_args.kwargs["additional_system_context"]
    assert PC_WORK_CONTEXT_VERSION in context
    # No canonical Mesh owner scope in this stub harness, so execution is
    # truthfully unverified: the context must NOT name the tool.
    assert PC_DRIVE_TOOL_ID not in context
    assert "실행" in context
    assert source.calls and source.calls[0]["owner_id"] == OWNER


def test_claw_general_refuses_a_selected_device_without_a_verified_target():
    source = Directory([device("selected-pc")])
    with _claw_client(source, mesh=None, identity=Identity()) as (client, adapter):
        # "드라이브" also matches the Google Drive grounding intent; this test
        # isolates the PC target guard, not Drive grounding.
        with patch(
            "app.claw_general_routes.drive_general_grounding",
            new=AsyncMock(return_value=(None, ())),
        ):
            response = client.post(
                "/api/claw/general",
                headers={"Origin": BASE},
                json={
                    "messages": [{"role": "user", "content": "내 PC 드라이브 알려줘"}],
                    "tier": "plus",
                    "device_id": "selected-pc",
                },
            )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "pc_target_unavailable"
    adapter.execute.assert_not_awaited()


class _CaptureClient:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append(dict(kwargs))
        return {"answer": "확인했습니다.", "runtime": "test"}


class _NoopAutoGrounding:
    def decide(self, messages, *, skill):
        return None

    async def prepare(self, messages, *, skill, additional_system_context):
        return None


def test_chat_model_call_carries_the_verified_pc_context():
    source = Directory([device()])
    config = _claw_settings()
    app = create_app(settings=config, history_store=_AuthStore(),
                     claw_device_directory_source=source)
    app.state.oracle_mesh_return_source = Mesh([mesh_row()])
    app.state.control_plane_identity_authority = Identity()
    app.state.b14_client = _CaptureClient()
    app.state.auto_grounding = _NoopAutoGrounding()
    app.state.usage_gate_enforced = False

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE,
        ) as client:
            client.cookies.set(
                SESSION_COOKIE, create_session_token(config, OWNER),
                domain="chat.example.test", path="/",
            )
            return await client.post("/api/chat", json={
                "mode": "auto",
                "messages": [{"role": "user", "content": "드라이브 연결됨?"}],
            })

    response = asyncio.run(perform())
    assert response.status_code == 200, response.text
    model = app.state.b14_client
    assert model.calls, "the model must actually be called"
    context = model.calls[0]["additional_system_context"]
    assert PC_WORK_CONTEXT_VERSION in context
    assert "등록 기기 목록" in context
    # In this harness the canonical session resolves to owner:<uid>, so the
    # Mesh owner scope is unverified; the online badge must not become a tool.
    assert PC_DRIVE_TOOL_ID not in context


class _ChatB14:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def complete(self, messages, skill, additional_system_context=None):
        self.calls.append(additional_system_context)
        return {"answer": self.answers.pop(0)}


class _ChatHistory:
    def __init__(self):
        self.pairs = []
        self.staged = None

    async def append_exchange(self, user_id, conversation_id, user_text, answer, *, product_scope):
        self.pairs.append((user_text, answer))
        return conversation_id or ("chat_" + "n" * 32)

    async def record_chat_pc_drive_run(self, *, user_id, run_id, workspace_id, user_text, conversation_id):
        self.staged = {"run_id": run_id, "workspace_id": workspace_id}
        return conversation_id or ("chat_" + "s" * 32)

    async def get_claw_run(self, user_id, run_id):
        return {
            "run_id": run_id, "conversation_id": "chat_" + "s" * 32,
            "result_summary": "no_exit_code", "workspace_id": WORKSPACE,
        }

    async def append_local_task_result(self, **fields):
        return True


class _ChatBridge(B62EngineOrchestrationBridge):
    def __init__(self, answer="C: 드라이브가 있습니다."):
        # Real base so the lane's type check exercises the production branch.
        super().__init__(client=object(), store=object())
        self.answer = answer
        self.requests = []

    async def start(self, **fields):
        self.requests.append(fields)
        return SimpleNamespace(answer=self.answer, public={"answer": self.answer})


def _chat_pc_request(*, answer, mesh=None, identity=None, bridge=None,
                     selection_store=None, directory=None):
    b14 = _ChatB14([answer])
    history = _ChatHistory()
    state = SimpleNamespace(
        b14_client=b14, history_store=history,
        identity_shadow_store=object(), control_plane_identity_authority=identity,
        oracle_mesh_return_source=mesh,
        settings=SimpleNamespace(auth_mode="mock"),
        claw_device_directory_source=directory or Directory([device("office-pc")]),
        claw_pc_device_selection_store=selection_store,
        orchestration_bridge=bridge,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        cookies={"padiem_session": "signed-" + OWNER},
    )


def _run_chat_lane(request, *, device_id=None):
    import app.chat_pc_drive as lane

    async def fake_owner(req, uid):
        return SimpleNamespace(session_id=SESSION), "sub_" + "a" * 32, WORKSPACE

    old_ready, old_uid = lane.auth_ready, lane.current_user_id
    old_owner = lane._resolve_chat_owner
    lane.auth_ready = lambda req: True
    lane.current_user_id = lambda req: OWNER
    lane._resolve_chat_owner = fake_owner
    try:
        return asyncio.run(execute_chat_pc_drive_lane(
            request, user_text="내 PC 드라이브 목록 알려줘", skill=None,
            model_id="model-x", conversation_id=None, tier="free",
            device_id=device_id,
        ))
    finally:
        lane.auth_ready, lane.current_user_id = old_ready, old_uid
        lane._resolve_chat_owner = old_owner


def test_chat_pc_decision_model_receives_context_and_selection_reaches_the_plan():
    bridge = _ChatBridge()
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        mesh=Mesh([mesh_row("office-pc")]), identity=Identity(), bridge=bridge,
    )
    result = _run_chat_lane(request, device_id="office-pc")
    assert result is not None
    decision_context = request.app.state.b14_client.calls[0]
    assert PC_WORK_CONTEXT_VERSION in decision_context
    assert "현재 작업 대상 PC: Office PC" in decision_context
    assert CHAT_PC_QUERY_TOOL_ID in decision_context
    # The SAME selected id travels to the Engine plan, not a server guess.
    assert bridge.requests[0]["tool_arguments"] == {
        "query_drives": {"device_id": "office-pc"},
    }
    assert bridge.requests[0]["agent_plan"]["agent_id"] == "agent:padiem:chat-pc-query@1"
    assert PC_WORK_CONTEXT_VERSION in bridge.requests[0]["additional_system_context"]


def test_chat_pc_lane_refuses_a_selected_device_mismatch():
    bridge = _ChatBridge()
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        mesh=Mesh([mesh_row(None, node_ref="mesh-node")]), identity=Identity(), bridge=bridge,
    )
    try:
        _run_chat_lane(request, device_id="office-pc")
    except ChatPCDriveError as exc:
        assert exc.code == "chat_pc_target_mismatch"
        assert exc.status_code == 403
    else:
        raise AssertionError("a mismatched selection must be refused")
    assert bridge.requests == []


# --- adapter: the drive plan carries the verified target --------------------


def test_p01_adapter_drive_plan_carries_the_selected_device():
    import inspect

    from kagent.p01_adapter import P01RequestFactory
    from kagent.p01_run_flow import create_claw_run

    factory = P01RequestFactory(allow_subject_identity=True)
    run = create_claw_run("padiem-chat", "내 PC 드라이브 알려줘", model_only_text=True)
    bundle = factory.build(
        run, subject_id="sub_" + "a" * 32,
        pc_drive_query=True, desktop_device_id="office-pc",
    )
    plan = bundle.orchestration_request.agent_plan
    args = bundle.orchestration_request.tool_arguments
    assert plan.steps[0].step_id == "query_drives"
    assert dict(args) == {"query_drives": {"device_id": "office-pc"}}
    # Default path unchanged: no selection means no target argument.
    plain_run = create_claw_run("padiem-chat", "내 PC 드라이브 알려줘", model_only_text=True)
    plain = factory.build(plain_run, subject_id="sub_" + "a" * 32, pc_drive_query=True)
    assert plain.orchestration_request.tool_arguments is None
    assert inspect.signature(P01RequestFactory.build).parameters["desktop_device_id"].default is None


# --- saved target preference: server default, still re-verified ------------


class SavedSelection:
    def __init__(self, value=None, *, raises=False):
        self.value = value
        self.raises = raises
        self.calls = []

    async def load(self, *, owner_id, workspace_id):
        self.calls.append({"owner_id": owner_id, "workspace_id": workspace_id})
        if self.raises:
            raise RuntimeError("SECRET_SELECTION_PATH")
        return self.value


def test_saved_selection_is_owner_workspace_bound_and_fail_closed():
    store = SavedSelection("office-pc")
    request = request_for(Directory([device()]), owner_state={})
    request.app.state.claw_pc_device_selection_store = store
    assert asyncio.run(load_saved_device_selection(
        request, owner_id=OWNER, workspace_id=WORKSPACE,
    )) == "office-pc"
    assert store.calls == [{"owner_id": OWNER, "workspace_id": WORKSPACE}]
    assert asyncio.run(load_saved_device_selection(
        request, owner_id=OTHER_OWNER, workspace_id=WORKSPACE,
    )) == "office-pc"  # the store itself is responsible for the key
    assert asyncio.run(load_saved_device_selection(
        request, owner_id=None, workspace_id=WORKSPACE,
    )) is None
    assert asyncio.run(load_saved_device_selection(
        request, owner_id=OWNER, workspace_id=None,
    )) is None


def test_saved_selection_read_failure_or_bad_value_is_no_preference():
    request = request_for(Directory([device()]), owner_state={})
    for store, expected in (
        (SavedSelection(raises=True), None),
        (SavedSelection("bad/path"), None),
        (SavedSelection(None), None),
        (None, None),
    ):
        request.app.state.claw_pc_device_selection_store = store
        assert asyncio.run(load_saved_device_selection(
            request, owner_id=OWNER, workspace_id=WORKSPACE,
        )) == expected


def test_chat_lane_uses_the_saved_target_when_the_browser_sends_none():
    bridge = _ChatBridge()
    store = SavedSelection("office-pc")
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        mesh=Mesh([mesh_row("office-pc")]), identity=Identity(), bridge=bridge,
        selection_store=store,
    )
    result = _run_chat_lane(request, device_id=None)
    assert result is not None
    assert store.calls == [{"owner_id": OWNER, "workspace_id": WORKSPACE}]
    assert bridge.requests[0]["tool_arguments"] == {
        "query_drives": {"device_id": "office-pc"},
    }
    assert "현재 작업 대상 PC: Office PC" in request.app.state.b14_client.calls[0]


def test_chat_lane_refuses_a_stale_saved_target():
    bridge = _ChatBridge()
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        # Unpinned Mesh row: the structural match still must not claim the
        # saved identifier.
        mesh=Mesh([mesh_row(None, node_ref="office-pc")]), identity=Identity(), bridge=bridge,
        selection_store=SavedSelection("gone"),
    )
    try:
        _run_chat_lane(request, device_id=None)
    except ChatPCDriveError as exc:
        assert exc.code == "chat_pc_target_mismatch"
        assert exc.status_code == 403
    else:
        raise AssertionError("a stale saved target must be refused")
    assert bridge.requests == []


def test_chat_lane_refuses_a_revoked_saved_target():
    bridge = _ChatBridge()
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        mesh=Mesh([mesh_row("office-pc")]), identity=Identity(), bridge=bridge,
        selection_store=SavedSelection("office-pc"),
        directory=Directory([device("office-pc", state="REVOKED")]),
    )
    try:
        _run_chat_lane(request, device_id=None)
    except ChatPCDriveError as exc:
        assert exc.code == "chat_pc_selection_revoked"
        assert exc.status_code == 409
    else:
        raise AssertionError("a revoked saved target must be refused")
    assert bridge.requests == []


def _selection_request(store):
    request = request_for(Directory([device()]), owner_state={})
    request.app.state.claw_pc_device_selection_store = store
    return request


def test_saved_selection_read_status_distinguishes_none_failure_and_value():
    assert asyncio.run(read_saved_device_selection(
        _selection_request(SavedSelection(None)),
        owner_id=OWNER, workspace_id=WORKSPACE,
    )).status == SAVED_SELECTION_NONE
    selected = asyncio.run(read_saved_device_selection(
        _selection_request(SavedSelection("office-pc")),
        owner_id=OWNER, workspace_id=WORKSPACE,
    ))
    assert selected.status == SAVED_SELECTION_SELECTED
    assert selected.device_id == "office-pc"
    assert asyncio.run(read_saved_device_selection(
        _selection_request(SavedSelection(raises=True)),
        owner_id=OWNER, workspace_id=WORKSPACE,
    )).status == SAVED_SELECTION_UNAVAILABLE
    assert asyncio.run(read_saved_device_selection(
        _selection_request(None),
        owner_id=OWNER, workspace_id=WORKSPACE,
    )).status == SAVED_SELECTION_UNCONFIGURED


def test_saved_selection_read_is_cached_within_one_request_only():
    store = SavedSelection("office-pc")
    request = _selection_request(store)
    first = asyncio.run(read_saved_device_selection(
        request, owner_id=OWNER, workspace_id=WORKSPACE,
    ))
    store.value = "home-pc"
    cached = asyncio.run(read_saved_device_selection(
        request, owner_id=OWNER, workspace_id=WORKSPACE,
    ))
    fresh = asyncio.run(read_saved_device_selection(
        _selection_request(SavedSelection("home-pc")),
        owner_id=OWNER, workspace_id=WORKSPACE,
    ))
    assert first.device_id == cached.device_id == "office-pc"
    assert fresh.device_id == "home-pc"


def test_chat_lane_fails_closed_when_saved_selection_cannot_be_read():
    bridge = _ChatBridge()
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        mesh=Mesh([mesh_row("office-pc")]), identity=Identity(), bridge=bridge,
        selection_store=SavedSelection(raises=True),
    )
    try:
        _run_chat_lane(request, device_id=None)
    except ChatPCDriveError as exc:
        assert exc.code == "chat_pc_selection_unavailable"
        assert exc.status_code == 503
    else:
        raise AssertionError("a failed selection lookup must not execute on a default PC")
    assert bridge.requests == []


def test_chat_lane_unique_target_still_works_when_no_preference_exists():
    bridge = _ChatBridge()
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        mesh=Mesh([mesh_row("office-pc")]), identity=Identity(), bridge=bridge,
        selection_store=SavedSelection(None),
    )
    result = _run_chat_lane(request, device_id=None)
    assert result is not None
    assert bridge.requests[0].get("tool_arguments") is None


def test_chat_lane_refuses_a_stale_screen_selection_against_the_saved_target():
    bridge = _ChatBridge()
    request = _chat_pc_request(
        answer=json.dumps({"action": "tool", "tool_id": CHAT_PC_QUERY_TOOL_ID, "arguments": {}}),
        mesh=Mesh([mesh_row("office-pc")]), identity=Identity(), bridge=bridge,
        selection_store=SavedSelection("office-pc"),
    )
    try:
        _run_chat_lane(request, device_id="home-pc")
    except ChatPCDriveError as exc:
        assert exc.code == "chat_pc_selection_stale"
        assert exc.status_code == 409
    else:
        raise AssertionError("a stale screen selection must not override the saved target")
    assert bridge.requests == []


def _drive_post(client, *, device_id=None):
    body = {
        "messages": [{"role": "user", "content": "내 PC 드라이브 알려줘"}],
        "tier": "plus",
    }
    if device_id is not None:
        body["device_id"] = device_id
    return client.post("/api/claw/general", headers={"Origin": BASE}, json=body)


def test_claw_drive_fails_closed_when_saved_selection_cannot_be_read():
    source = Directory([device("office-pc")])
    with _claw_client(
        source, mesh=Mesh([mesh_row("office-pc")]), identity=Identity(),
        selection_store=SavedSelection(raises=True),
    ) as (client, adapter):
        with patch(
            "app.claw_memory_routes._resolve_memory_workspace",
            new=AsyncMock(return_value=WORKSPACE),
        ), patch(
            "app.claw_general_routes.drive_general_grounding",
            new=AsyncMock(return_value=(None, ())),
        ):
            response = _drive_post(client)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "pc_selection_unavailable"
    adapter.execute.assert_not_awaited()


def test_claw_drive_refuses_a_stale_screen_selection_against_the_saved_target():
    source = Directory([device("office-pc"), device("home-pc")])
    with _claw_client(
        source, mesh=Mesh([mesh_row("office-pc"), mesh_row("home-pc")]), identity=Identity(),
        selection_store=SavedSelection("office-pc"),
    ) as (client, adapter):
        with patch(
            "app.claw_memory_routes._resolve_memory_workspace",
            new=AsyncMock(return_value=WORKSPACE),
        ), patch(
            "app.claw_general_routes.drive_general_grounding",
            new=AsyncMock(return_value=(None, ())),
        ):
            response = _drive_post(client, device_id="home-pc")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "pc_selection_stale"
    adapter.execute.assert_not_awaited()


def test_claw_drive_uses_the_saved_target_and_fails_closed_without_a_mesh_scope():
    source = Directory([device("office-pc")])
    with _claw_client(
        source, mesh=Mesh([mesh_row("office-pc")]), identity=Identity(),
        selection_store=SavedSelection("office-pc"),
    ) as (client, adapter):
        with patch(
            "app.claw_memory_routes._resolve_memory_workspace",
            new=AsyncMock(return_value=WORKSPACE),
        ), patch(
            "app.claw_general_routes.drive_general_grounding",
            new=AsyncMock(return_value=(None, ())),
        ):
            response = _drive_post(client)
    # The saved target was applied; with no canonical Mesh session it cannot
    # be verified, so the route refuses instead of using another default PC.
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "pc_target_unavailable"
    adapter.execute.assert_not_awaited()


# --- main/5116 compatibility: broker-only context (no Mesh lane) -----------


class _MainSource:
    configured = True

    def __init__(self, rows):
        self.rows = rows

    async def list_devices(self, *, owner_id, workspace_id, now):
        del owner_id, workspace_id, now
        return self.rows


def _main_request(rows):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            claw_device_directory_source=_MainSource(rows),
        )),
    )


def _main_row(device_id, name, state="CONNECTED", usable=True, **extra):
    return {
        "deviceId": device_id, "deviceName": name, "state": state,
        "usable": usable, **extra,
    }


def _main_resolve(rows, *, owner="usr_owner", workspace="ws-1"):
    return asyncio.run(resolve_pc_work_context(
        _main_request(rows), owner_id=owner, workspace_id=workspace,
        session_id="sess_main",
    ))


def test_single_connected_device_is_the_explicit_target():
    context = _main_resolve([_main_row("device-1", "Padiem-Command-Center")])
    assert context.status == "ready"
    assert context.target_device_id == "device-1"
    text = render_pc_work_context(context)
    assert "Padiem-Command-Center" in text
    assert "온라인" in text
    assert "승인된 폴더 목록" in text


def test_two_usable_devices_are_never_silently_selected():
    context = _main_resolve([_main_row("device-1", "PC-A"), _main_row("device-2", "PC-B")])
    assert context.target_device_id is None
    text = render_pc_work_context(context)
    assert "여러 대" in text and "임의로 하나를 고르지 말고" in text


def test_paused_and_offline_are_distinct_states():
    paused = _main_resolve([_main_row("device-1", "PC-A", usagePaused=True)])
    assert paused.status == "paused"
    assert "일시중지" in render_pc_work_context(paused)

    offline = _main_resolve([_main_row("device-1", "PC-A", state="OFFLINE", usable=False)])
    assert offline.status == "offline"
    assert "온라인 상태가 확인되지 않았습니다" in render_pc_work_context(offline)


def test_unverified_owner_and_unconfigured_source_fail_closed():
    unverified = _main_resolve([], owner=None)
    assert unverified.status == "unverified_owner"
    assert "확인하지 못해" in render_pc_work_context(unverified)

    no_source = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    unconfigured = asyncio.run(resolve_pc_work_context(
        no_source, owner_id="usr_owner", workspace_id="ws-1", session_id="sess_main",
    ))
    assert unconfigured.status == "unconfigured"
    assert "확인하지 못했습니다" in render_pc_work_context(unconfigured)
