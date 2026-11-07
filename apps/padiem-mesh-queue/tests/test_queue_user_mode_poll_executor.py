"""#7076d — a `mode=user` dispatch keeps its mode from the queue row to the executor.

The COM2 queue poll is the only producer the production executor reads, and `user_mode`
is the one field it must never have to infer: absent, the parser reads the default and
that default is the SYSTEM lane. So this drives the REAL queue store, the REAL poll
route and the REAL executor parser together, and proves two things:

* a row stored with `user_mode=1` arrives as `user_mode: true` and the executor then
  builds the user-helper pipe client instead of the SYSTEM shell command;
* a row whose mode cannot be stated is not handed out at all (no claim, no dispatch),
  so a user request can never fall through to a SYSTEM execution.
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
):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from app.oracle_mesh_read_return_routes import oracle_mesh_read_poll  # noqa: E402
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor  # noqa: E402
from schema import apply  # noqa: E402
from service import create_app  # noqa: E402

SECRET = "queue-channel-secret-value-261029"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node-ABC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]
DISPATCH_ID = "dsp_" + "a" * 32
RUN_ID = "chat_pcq_" + "a" * 24
#: The helper request material the executor unwraps for a user-mode command.
MATERIAL = json.dumps({"shell": "whoami", "command": "whoami", "cwd": None,
                       "timeout_seconds": 30, "distro": None})


def _moment(seconds=0):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


class _Headers(dict):
    """Starlette headers are case-insensitive; the route names one in Mixed-Case."""

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state, payload, *, secret=SECRET):
        self.app = SimpleNamespace(state=state)
        self.headers = _Headers({
            "content-type": "application/json",
            "x-oracle-mesh-secret": secret,
        })
        self._body = json.dumps(payload).encode("utf-8")

    async def body(self):
        return self._body


class _FakePort:
    """The command port: records what the executor actually asked the PC to run."""

    def __init__(self, output=b""):
        self.calls = []
        self.output = output

    def run_command(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(termination="exited", exit_code=0,
                               output=self.output, line_blocked=0, line_cleared=0)


def _connection():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    return connection


def _state(*, user_mode=1, with_mode_key=True):
    app = create_app(connection=_connection(), channel_secret=SECRET,
                     ownership_map=json.dumps(OWNERSHIP), mode="mesh")
    asyncio.run(_stage(app.state, user_mode=user_mode))
    return app.state


async def _stage(state, *, user_mode):
    await state.history_store._run(
        "INSERT INTO oracle_mesh_dispatch (dispatch_id, user_id, run_id, command_id, "
        "tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint, "
        "account_ref, workspace_ref, device_id, binding_ref, node_ref, root_ref, "
        "path_relative, file_path, kind, command_text, state, expires_at, created_at, "
        "claimed_until, nonce_sha256, user_mode) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        DISPATCH_ID, "usr_" + "b" * 32, RUN_ID, "cmd-1", "tool-1", "req-1",
        "rev-1", "evid-1", "fp-1", "acct-1", "ws-1", "device-1", "bind-1",
        "node-ABC", "C:", "p.txt", "C:/p.txt", "command", MATERIAL, "pending",
        _moment(600), _moment(), None, None, user_mode,
    )


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def _poll(state):
    return asyncio.run(oracle_mesh_read_poll(_Request(state, {})))


def _polling_executor(answer):
    """The executor's poll leg, with only the transport replaced by the route's answer."""
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


def _helper_reply(stdout: bytes) -> bytes:
    return json.dumps({
        "request_id": "req_" + "0" * 32, "status": "ok", "exit_code": 0,
        "stdout_b64": base64.b64encode(stdout).decode("ascii"),
        "stderr_b64": "", "duration_ms": 5,
    }).encode("utf-8")


def test_queue_poll_carries_user_mode_and_the_executor_takes_the_user_path():
    state = _state(user_mode=1)
    answer = _json(_poll(state))
    assert answer["ok"] is True
    assert answer["dispatch"]["user_mode"] is True
    assert answer["dispatch"]["kind"] == "command"

    dispatch = _polling_executor(answer).poll_once()
    assert dispatch is not None
    assert dispatch.user_mode is True

    port = _FakePort(output=_helper_reply(b"padiem-pc\\limone\r\n"))
    outcome = _command_executor(port).execute(dispatch)

    # Exactly one PC command, and it is the user-helper pipe client — not the
    # SYSTEM shell command the material itself would have produced.
    assert len(port.calls) == 1
    sent = port.calls[0]["command"]
    assert "padiem-user-helper-" in sent
    assert "NamedPipeClientStream" in sent
    assert b"padiem-pc\\limone" in outcome.body
    assert outcome.exit_code == 0


def test_a_row_whose_mode_cannot_be_stated_is_never_handed_out():
    state = _state(user_mode=1)
    store = state.history_store

    truthful = store.oldest_pending_oracle_mesh_dispatch

    async def blind():
        """A store that answers the row but cannot say which mode it is."""
        row = await truthful()
        if row is None:
            return None
        row = dict(row)
        row.pop("user_mode", None)
        return row

    claims = []
    original_claim = store.claim_oracle_mesh_dispatch

    async def recording_claim(**arguments):
        claims.append(arguments)
        return await original_claim(**arguments)

    store.oldest_pending_oracle_mesh_dispatch = blind
    store.claim_oracle_mesh_dispatch = recording_claim

    response = _poll(state)
    assert response.status_code == 503
    assert _json(response)["error"]["code"] == "oracle_mesh_dispatch_mode_unavailable"

    # No claim was ever written and nothing was handed out, so the executor has
    # no dispatch to fall back on: the user command cannot run as SYSTEM.
    assert claims == []
    row = asyncio.run(store._first(
        "SELECT state, nonce_sha256, claimed_until FROM oracle_mesh_dispatch "
        "WHERE dispatch_id=?", DISPATCH_ID))
    assert row["state"] == "pending"
    assert row["nonce_sha256"] is None
    assert row["claimed_until"] is None
    assert _polling_executor({"ok": True, "dispatch": None}).poll_once() is None
