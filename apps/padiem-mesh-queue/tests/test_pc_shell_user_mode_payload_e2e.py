"""#7076d — one payload from MCP `pc_shell(mode=user)` to the user-helper client.

The defect this fixes is a contract mismatch: the MCP layer sent the SYSTEM lane's
PowerShell dispatcher as `command_text`, while the executor unwraps the #7065
stage-1 helper request material. The test therefore starts where the model starts
— `execute_pc_shell_start` — and follows the one value through the real dispatch
intent, the real queue store and poll route, the real executor poll parser, and
the real pipe-client PowerShell generation.

The pipe connection itself is faked (one helper reply frame), which is the only
thing this lane cannot open on a build machine.
"""
from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import sqlite3
import sys
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
_REPO = QUEUE.parents[1]
for _root in (
    _REPO / "apps" / "padiem-chat",
    QUEUE,
    _REPO / "apps" / "korean-ai-code-agent" / "src",
    _REPO / "apps" / "claw-connect",
):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from app import mcp_gateway_shell as shell  # noqa: E402
from app import oracle_mesh_read_return_routes as routes  # noqa: E402
from claw_connect import user_session_helper as helper  # noqa: E402
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor  # noqa: E402
from schema import apply  # noqa: E402
from service import create_app  # noqa: E402

SECRET = "deployment-channel-secret-value-261017"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
OWNER = "product-user-1"
ACCOUNT = "account-oracle-1"
WORKSPACE = "connector-ws-1"
TENANT_WS = "tenant-ws-1"
DEVICE = "device-oracle-1"
RUN = "run-user-mode-1"
CONVERSATION = "chat_" + "b" * 32
DISPATCH_ID = "dsp_" + "a" * 32
OWNERSHIP = [{
    "account_ref": ACCOUNT, "device_id": DEVICE, "node_ref": NODE,
    "root_ref": "meshcentral_private_trial",
    "path_relative": "meshcentral-padiem-trial.txt",
    "file_path": "C:\\Users\\limone\\meshcentral-padiem-trial.txt",
    "command_exec": True,
}]


def _moment(seconds=0):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


class _Headers(dict):
    def __init__(self, values):
        super().__init__((str(name).lower(), value) for name, value in values.items())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state):
        self.app = SimpleNamespace(state=state)
        self.headers = _Headers({
            "content-type": "application/json",
            routes.ORACLE_MESH_CHANNEL_HEADER: SECRET,
        })

    async def body(self):
        return b"{}"


class _Identity:
    async def resolve_connector_owner_scope(self, *, session_id):
        del session_id
        return {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE}


class _History:
    """Stands in for the conversation-side store the intent route reads."""

    def __init__(self):
        self.created = []

    async def get_claw_run(self, user_id, run_id):
        if user_id != OWNER or run_id != RUN:
            return None
        return {"run_id": RUN, "conversation_id": CONVERSATION,
                "workspace_id": TENANT_WS, "status": "waiting"}

    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return None

    async def create_oracle_mesh_dispatch(self, **fields):
        self.created.append(fields)
        return {**fields, "dispatch_id": DISPATCH_ID, "state": "pending",
                "expires_at": fields["expires_at"]}


class _FakePort:
    """The command port: records exactly what the executor asked the PC to run."""

    def __init__(self, output=b""):
        self.calls = []
        self.output = output

    def run_command(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(termination="exited", exit_code=0,
                               output=self.output, line_blocked=0, line_cleared=0)


def _helper_reply(stdout: bytes) -> bytes:
    return json.dumps({
        "request_id": "req_" + "a" * 32, "status": "ok", "exit_code": 0,
        "stdout_b64": base64.b64encode(stdout).decode("ascii"),
        "stderr_b64": "", "duration_ms": 5,
    }).encode("utf-8")


def _session():
    return SimpleNamespace(session_id="session.canonical.owner.1", tenant_id="tenant-1")


def _mcp_state(history):
    return SimpleNamespace(
        oracle_mesh_return_source=routes.build_oracle_mesh_return_source(
            OWNERSHIP, SECRET, routes.EXECUTION_MODE_MESH),
        control_plane_identity_authority=_Identity(),
        history_store=history,
    )


def _stage_user_command_state(created):
    """The real queue app, holding the row the MCP lane just staged."""
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    state = create_app(connection=connection, channel_secret=SECRET,
                       ownership_map=json.dumps(OWNERSHIP), mode="mesh").state
    fields = created[0]
    asyncio.run(state.history_store._run(
        "INSERT INTO oracle_mesh_dispatch (dispatch_id, user_id, run_id, command_id, "
        "tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint, "
        "account_ref, workspace_ref, device_id, binding_ref, node_ref, root_ref, "
        "path_relative, file_path, kind, command_text, state, expires_at, created_at, "
        "claimed_until, nonce_sha256, user_mode) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        DISPATCH_ID, fields["user_id"], fields["run_id"], fields["command_id"],
        fields["tool_request_ref"], fields["request_id"], fields["revision_ref"],
        fields["evidence_ref"], fields["request_fingerprint"], fields["account_ref"],
        fields["workspace_ref"], fields["device_id"], fields["binding_ref"],
        fields["node_ref"], fields["root_ref"], fields["path_relative"],
        fields["file_path"], fields["kind"], fields["command_text"], "pending",
        _moment(600), _moment(), None, None, 1 if fields["user_mode"] else 0,
    ))
    return state


def _poll(state):
    return asyncio.run(routes.oracle_mesh_read_poll(_Request(state)))


def _polling_executor(answer):
    executor = object.__new__(OracleMeshExecutor)
    executor._origin = "https://chat.example.invalid"
    executor._queue_origin = "http://127.0.0.1:8797"
    executor._presence_provider = None
    executor._pairing_provider = None
    executor._carried_pairing_tags = []
    executor._reported_pairing_tags = set()
    executor._post = lambda path, payload: (200, answer)
    return executor


def _command_executor(port):
    executor = object.__new__(OracleMeshExecutor)
    executor._command_port = port
    return executor


def test_mcp_user_mode_material_survives_dispatch_queue_and_reaches_the_pipe_client():
    history = _History()
    started = asyncio.run(shell.execute_pc_shell_start(
        _Request(_mcp_state(history)),
        uid=OWNER, workspace_id=TENANT_WS, device_id=DEVICE, run_id=RUN,
        session=_session(), conversation_id=CONVERSATION,
        arguments={"command": "whoami", "mode": "user"},
    ))
    assert started["status"] == "running", started
    assert started["job_id"] == DISPATCH_ID

    staged = history.created[0]
    # The dispatch carries the helper's contract, not the SYSTEM dispatcher.
    assert staged["user_mode"] is True
    assert staged["kind"] == "command"
    material = json.loads(staged["command_text"])
    # #7111: the user helper has no execution deadline — timeout_seconds 0
    # means the command runs until it ends and the owner stops it.
    assert material == {"shell": "whoami", "command": "whoami", "cwd": None,
                        "timeout_seconds": 0, "distro": None}
    assert "PADIEM_MCP_COMMAND_B64" not in staged["command_text"]

    # ... and it still is, after the real queue store and poll route.
    state = _stage_user_command_state(history.created)
    answer = json.loads(_poll(state).body)
    assert answer["ok"] is True, answer
    assert answer["dispatch"]["user_mode"] is True
    assert answer["dispatch"]["command_text"] == staged["command_text"]

    dispatch = _polling_executor(answer).poll_once()
    assert dispatch is not None and dispatch.user_mode is True

    port = _FakePort(output=_helper_reply(b"padiem-pc\\limone\r\n"))
    outcome = _command_executor(port).execute(dispatch)

    # The PC is asked to run the pipe client, and the request material it signs
    # is exactly the helper's own material for this dispatch — one contract.
    assert len(port.calls) == 1
    sent = port.calls[0]["command"]
    request_id = "req_" + DISPATCH_ID[len("dsp_"):][:32]
    expected = helper.HelperRequest(
        request_id=request_id, nonce="", shell="whoami", command="whoami",
        timeout_seconds=0,
    ).material()
    assert base64.b64encode(expected).decode("ascii") in sent
    assert helper.pipe_name(DEVICE) in sent
    assert "NamedPipeClientStream" in sent
    assert "PADIEM_MCP_COMMAND_B64" not in sent
    assert b"padiem-pc\\limone" in outcome.body
    assert outcome.exit_code == 0


def test_bash_maps_to_the_helpers_wsl_shell_and_never_to_a_system_shell():
    material = json.loads(shell.build_pc_shell_user_material(
        {"command": "systemctl is-active padiem", "shell": "bash"}))
    assert material["shell"] == "wsl"
    assert material["command"] == "systemctl is-active padiem"
    assert material["distro"] is None

    # #7105: powershell and cmd are the helper's own stage-2 shells, so they are
    # passed through as the shell the user session runs.
    for name in ("powershell", "cmd"):
        passthrough = json.loads(shell.build_pc_shell_user_material(
            {"command": "hostname", "shell": name}))
        assert passthrough["shell"] == name
        assert passthrough["command"] == "hostname"
