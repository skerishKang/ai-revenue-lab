"""End-to-end PC tool turns through the real MCP gateway and shell lane.

The gateway, MCP validation, owner/device gates, dispatch staging, shell wait
loop and result projection are real.  Only the PC agent/queue consumer, the
existing owner-context lookup and the mesh source are boundary doubles.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app import mcp_gateway_shell as shell
from app.mcp_gateway_execution import execute_mcp_pc_tool
from app.mcp_gateway_transport import MCP_GATEWAY_PATH, mcp_gateway_endpoint

OWNER = "usr_" + "a" * 32
DEVICE = "dev_" + "b" * 32
TOKEN = "mcp_" + "c" * 32
TOKEN_ID = "mcp_" + "d" * 32
DISPLAY_NAME = "PADIEM-COMMAND-"
RUN_ID = "chat_pcq_" + "e" * 32
CONVERSATION = "chat_" + "f" * 32
OUTPUT = "PC 명령 출력: 완료"
PREFIX = "io.modelcontextprotocol/"
MODERN = "2026-07-28"


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "dispatch_id", "user_id", "device_id", "run_id", "kind", "state",
            "claimed", "termination", "exit_code", "command_id", "revision_ref",
            "result_sha256", "result_bytes", "user_mode",
        )
    }


class _GatewayStore:
    def __init__(self) -> None:
        self.audit_records: list[dict[str, Any]] = []
        self.receipts: set[str] = set()

    async def authenticate(self, token: str):
        if token != TOKEN:
            return None
        return {"user_id": OWNER, "device_id": DEVICE, "token_id": TOKEN_ID, "name": "시험 AI"}

    async def audit(self, **kwargs: Any) -> None:
        self.audit_records.append(dict(kwargs))
        job_id = kwargs.get("job_receipt_id")
        if isinstance(job_id, str):
            self.receipts.add(job_id)

    async def owns_job_receipt(self, *, identity: dict[str, Any], job_id: str) -> bool:
        return job_id in self.receipts and identity.get("user_id") == OWNER


class _Pairing:
    def __init__(self, *, managed: bool = False) -> None:
        self.managed = managed

    async def is_managed_link(self, *, user_id: str, mesh_node_id: str) -> bool:
        return bool(self.managed and user_id == OWNER and mesh_node_id == DEVICE)

    async def link_for(self, *, user_id: str, mesh_node_id: str):
        if user_id == OWNER and mesh_node_id == DEVICE:
            return {"mesh_node_id": DEVICE, "user_id": OWNER}
        return None

    async def links_for_owner(self, *, user_id: str):
        if user_id != OWNER:
            return []
        return [{"mesh_node_id": DEVICE, "label": DISPLAY_NAME}]


class _Authority:
    async def resolve_connector_owner_scope(self, *, session_id: str):
        assert session_id == "session_fixture"
        return {"account_ref": "account_fixture", "workspace_ref": "workspace_fixture"}


class _Admin:
    def __init__(self, *, admin: bool) -> None:
        self.admin = admin

    async def is_global_model_admin(self, *, user_id: str) -> bool:
        return bool(self.admin and user_id == OWNER)


class _MeshSource:
    configured = True
    execution_mode = "mesh"

    def command_target(self, *, account_ref: str, device_id: str):
        assert account_ref == "account_fixture"
        assert device_id == DEVICE
        return {"device_id": DEVICE, "node_ref": DEVICE}


class _History:
    """The fake PC agent's queue and result store.

    ``complete_after`` is the number of public dispatch reads after which the
    fake consumer finishes the oldest pending job.  Zero leaves it queued for a
    stop test; three exercises two growth intervals before the result.
    """

    def __init__(self, *, complete_after: int = 1) -> None:
        self.complete_after = complete_after
        self.runs: dict[str, dict[str, Any]] = {}
        self.rows: dict[str, dict[str, Any]] = {}
        self.queue: list[dict[str, Any]] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.output_reads: list[dict[str, Any]] = []
        self._public_reads = 0

    async def record_chat_pc_drive_run(self, **kwargs: Any) -> str:
        self.runs[kwargs["run_id"]] = {
            "run_id": kwargs["run_id"],
            "workspace_id": kwargs["workspace_id"],
            "conversation_id": CONVERSATION,
        }
        return CONVERSATION

    async def get_claw_run(self, user_id: str, run_id: str):
        if user_id != OWNER:
            return None
        return self.runs.get(run_id)

    async def get_local_task_correlation(self, user_id: str, run_id: str):
        return None

    async def create_oracle_mesh_dispatch(self, **kwargs: Any) -> dict[str, Any]:
        dispatch_id = "dsp_" + secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        row = {
            **kwargs,
            "dispatch_id": dispatch_id,
            "state": "pending",
            "claimed": False,
            "termination": None,
            "exit_code": None,
            "result_sha256": None,
            "result_bytes": None,
            "expires_at": (now + timedelta(seconds=kwargs.get("ttl_seconds", 60))).isoformat(),
            "output": OUTPUT,
        }
        self.rows[dispatch_id] = row
        self.queue.append(row)
        return dict(row)

    async def get_pc_output_dispatch_for_owner(self, *, user_id: str, dispatch_id: str):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return dict(row)

    async def get_oracle_mesh_dispatch_for_owner(self, *, user_id: str, dispatch_id: str):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id:
            return None
        self._public_reads += 1
        if (self.complete_after and self._public_reads >= self.complete_after
                and row["state"] == "pending"):
            raw = row["output"].encode("utf-8")
            row.update({
                "state": "done",
                "termination": "exited",
                "exit_code": 0,
                "result_sha256": hashlib.sha256(raw).hexdigest(),
                "result_bytes": len(raw),
            })
        return _public_row(row)

    async def read_oracle_mesh_original(self, *, user_id: str, dispatch_id: str,
                                        conversation_id: str, message_id: str):
        row = self.rows.get(dispatch_id)
        if row is None or row.get("user_id") != user_id or row["state"] != "done":
            return None
        raw = row["output"].encode("utf-8")
        return raw, row["result_sha256"]

    async def store_pc_output(self, **kwargs: Any) -> dict[str, Any]:
        row = self.rows[kwargs["dispatch_id"]]
        row["output_ref"] = {
            "handle": "a" * 64,
            "size": len(kwargs["content"].encode("utf-8")),
            "truncated": False,
        }
        return dict(row["output_ref"])

    async def read_pc_output(self, **kwargs: Any):
        self.output_reads.append(dict(kwargs))
        row = next(
            row for row in self.rows.values()
            if row.get("run_id") == kwargs.get("run_id")
        )
        raw = row["output"].encode("utf-8")
        start = kwargs.get("offset", 0)
        return {
            "handle": kwargs["handle"],
            "content": raw[start:start + kwargs.get("length", 65536)].decode("utf-8"),
        }

    async def cancel_oracle_mesh_dispatches_for_run(self, *, user_id: str, run_id: str) -> int:
        self.cancel_calls.append((user_id, run_id))
        count = 0
        for row in self.rows.values():
            if row.get("user_id") == user_id and row.get("run_id") == run_id and row["state"] == "pending":
                row["state"], row["termination"] = "failed", "cancelled"
                count += 1
        return count


def _install_owner_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import mcp_gateway_execution as execution

    async def owner(_request, _uid):
        return SimpleNamespace(session_id="session_fixture", tenant_id="tenant_fixture"), "sub_" + "1" * 32, "workspace_fixture"

    async def context(_request, **_kwargs):
        return SimpleNamespace(
            selection_offline=False,
            selected_device_id=DEVICE,
            selected_confirmed=True,
            tool_available=True,
            execution_device_id=DEVICE,
        )

    async def grant(*_args, **_kwargs):
        return True

    def run_id():
        return RUN_ID

    async def notice(*_args, **_kwargs):
        return None

    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "_new_lane_run_id", run_id)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)


def _app(monkeypatch: pytest.MonkeyPatch, *, user_mode: bool, complete_after: int,
         admin: bool = False, managed: bool = False):
    _install_owner_boundaries(monkeypatch)
    history = _History(complete_after=complete_after)
    gateway_store = _GatewayStore()
    app = Starlette(routes=[
        Route(MCP_GATEWAY_PATH, mcp_gateway_endpoint, methods=["POST", "GET", "DELETE", "OPTIONS"]),
    ])
    app.state.settings = SimpleNamespace(
        public_base_url="https://chat.example.test",
        mcp_pc_shell_enabled=True,
        mcp_pc_shell_user_mode_enabled=user_mode,
    )
    app.state.mcp_gateway_store = gateway_store
    app.state.pc_device_pairing_store = _Pairing(managed=managed)
    app.state.central_model_admin_authorizer = _Admin(admin=admin)
    app.state.history_store = history
    app.state.mcp_gateway_executor = execute_mcp_pc_tool
    app.state.control_plane_identity_authority = _Authority()
    app.state.oracle_mesh_return_source = _MeshSource()
    return app, history, gateway_store


def _call(client: TestClient, name: str, arguments: dict[str, Any]):
    request_id = secrets.randbelow(1_000_000) + 1
    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
            "_meta": {
                PREFIX + "protocolVersion": MODERN,
                PREFIX + "clientCapabilities": {},
            },
        },
    }
    return client.post(
        MCP_GATEWAY_PATH,
        json=body,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MODERN,
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
        },
    )


def test_pc_shell_omitting_mode_with_user_mode_on_queues_user_mode_without_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The requested default: user mode ON + no ``mode`` means the user lane."""
    app, history, _ = _app(monkeypatch, user_mode=True, complete_after=1)
    with TestClient(app) as client:
        response = _call(client, "pc_shell", {"command": "whoami", "wait_seconds": 1})

    assert response.status_code == 200, response.text
    assert len(history.queue) == 1
    queued = history.queue[0]
    assert queued["user_mode"] is True
    assert '"timeout_seconds":0' in queued["command_text"]


def test_explicit_user_mode_queues_user_mode_and_zero_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, _ = _app(monkeypatch, user_mode=True, complete_after=1)
    with TestClient(app) as client:
        response = _call(
            client,
            "pc_shell",
            {"command": "whoami", "mode": "user", "wait_seconds": 1},
        )

    assert response.status_code == 200, response.text
    queued = history.queue[0]
    assert queued["user_mode"] is True
    assert '"timeout_seconds":0' in queued["command_text"]


def test_explicit_system_stays_system_when_user_mode_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, _ = _app(monkeypatch, user_mode=True, complete_after=1,
                           admin=True, managed=True)
    with TestClient(app) as client:
        response = _call(
            client,
            "pc_shell",
            {"command": "whoami", "mode": "system", "wait_seconds": 1},
        )

    assert response.status_code == 200, response.text
    queued = history.queue[0]
    assert queued["user_mode"] is False
    assert "PADIEM_MCP_COMMAND_B64" in queued["command_text"]
    assert "timeout_seconds" not in queued["command_text"]


def test_pc_shell_with_user_mode_off_keeps_the_existing_system_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #7565: with the switch off the omitted mode is SYSTEM, so this payload is
    # only reached by an administrator on a managed PC.
    app, history, _ = _app(monkeypatch, user_mode=False, complete_after=1,
                           admin=True, managed=True)
    with TestClient(app) as client:
        response = _call(client, "pc_shell", {"command": "whoami", "wait_seconds": 1})

    assert response.status_code == 200, response.text
    assert len(history.queue) == 1
    queued = history.queue[0]
    assert queued["user_mode"] is False
    assert "PADIEM_MCP_COMMAND_B64" in queued["command_text"]
    assert "timeout_seconds" not in queued["command_text"]


def test_pc_shell_stop_accepts_device_and_reaches_the_queued_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, gateway_store = _app(monkeypatch, user_mode=True, complete_after=0)
    with TestClient(app) as client:
        started = _call(client, "pc_shell_start", {"command": "whoami", "mode": "user"})
        assert started.status_code == 200, started.text
        job_id = started.json()["result"]["structuredContent"]["job_id"]
        assert job_id in gateway_store.receipts

        stopped = _call(
            client,
            "pc_shell_stop",
            {"job_id": job_id, "device": DISPLAY_NAME},
        )

    assert stopped.status_code == 200, stopped.text
    result = stopped.json()["result"]["structuredContent"]
    assert result["status"] == "cancelled"
    assert history.cancel_calls == [(OWNER, RUN_ID)]
    assert history.rows[job_id]["state"] == "failed"
    assert history.rows[job_id]["termination"] == "cancelled"


def test_pc_shell_wait_returns_when_the_consumer_result_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, _ = _app(monkeypatch, user_mode=True, complete_after=3)
    sleeps: list[float] = []
    clock = [0.0]

    def now() -> float:
        return clock[0]

    async def recording_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(shell, "_NOW", now)
    monkeypatch.setattr(shell.asyncio, "sleep", recording_sleep)

    with TestClient(app) as client:
        response = _call(
            client,
            "pc_shell",
            {"command": "whoami", "mode": "user", "wait_seconds": 30},
        )

    assert response.status_code == 200, response.text
    result = response.json()["result"]["structuredContent"]
    assert result["status"] == "completed"
    assert result["output"] == OUTPUT
    assert sleeps == [0.5, 1.0]
    assert sum(sleeps) < 30


def test_system_mode_runs_for_an_admin_on_a_managed_pc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, gateway_store = _app(
        monkeypatch, user_mode=True, complete_after=1, admin=True, managed=True,
    )
    with TestClient(app) as client:
        response = _call(
            client,
            "pc_shell",
            {"command": "whoami", "mode": "system", "wait_seconds": 1},
        )

    assert response.status_code == 200, response.text
    queued = history.queue[0]
    assert queued["user_mode"] is False
    assert "PADIEM_MCP_COMMAND_B64" in queued["command_text"]
    assert [row["status"] for row in gateway_store.audit_records] == ["requested", "completed"]
    assert all(row.get("command_bytes") == len("whoami") for row in gateway_store.audit_records)


def test_system_mode_is_denied_for_an_admin_on_an_unmanaged_pc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, gateway_store = _app(
        monkeypatch, user_mode=True, complete_after=1, admin=True, managed=False,
    )
    with TestClient(app) as client:
        response = _call(
            client,
            "pc_shell",
            {"command": "whoami", "mode": "system", "wait_seconds": 1},
        )

    assert response.status_code == 200, response.text
    result = response.json()["result"]["structuredContent"]
    assert result["status"] == "denied"
    assert result["deny_reason"] == "pc_shell_system_denied"
    assert result["answer"] == "SYSTEM 실행은 관리자와 관리(계약) PC에서만 허용됩니다."
    assert history.queue == []
    assert [row["status"] for row in gateway_store.audit_records] == ["requested", "denied"]
    assert all(row.get("command_bytes") == len("whoami") for row in gateway_store.audit_records)


def test_system_mode_is_denied_for_a_non_admin_on_a_managed_pc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, gateway_store = _app(
        monkeypatch, user_mode=True, complete_after=1, admin=False, managed=True,
    )
    with TestClient(app) as client:
        response = _call(
            client,
            "pc_shell",
            {"command": "whoami", "mode": "system", "wait_seconds": 1},
        )

    result = response.json()["result"]["structuredContent"]
    assert result["status"] == "denied"
    assert result["deny_reason"] == "pc_shell_system_denied"
    assert history.queue == []
    assert [row["status"] for row in gateway_store.audit_records] == ["requested", "denied"]


def test_pc_shell_start_uses_the_same_system_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, _ = _app(
        monkeypatch, user_mode=True, complete_after=0, admin=False, managed=False,
    )
    with TestClient(app) as client:
        response = _call(client, "pc_shell_start", {"command": "whoami", "mode": "system"})

    assert response.status_code == 200, response.text
    result = response.json()["result"]["structuredContent"]
    assert result["status"] == "denied"
    assert result["deny_reason"] == "pc_shell_system_denied"
    assert history.queue == []


# #7565: the SYSTEM rule must not depend on the user-mode switch. With the
# switch off the default (omitted) mode is SYSTEM, which is exactly the case
# the switch-on tests above never reached.
@pytest.mark.parametrize("tool, arguments", [
    ("pc_shell", {"command": "whoami", "wait_seconds": 1}),
    ("pc_shell_start", {"command": "whoami"}),
])
@pytest.mark.parametrize("admin, managed", [(False, False), (False, True), (True, False)])
def test_system_rule_applies_with_user_mode_off(
    monkeypatch: pytest.MonkeyPatch, tool, arguments, admin, managed,
) -> None:
    app, history, gateway_store = _app(
        monkeypatch, user_mode=False, complete_after=1, admin=admin, managed=managed,
    )
    with TestClient(app) as client:
        response = _call(client, tool, arguments)

    assert response.status_code == 200, response.text
    result = response.json()["result"]["structuredContent"]
    assert result["status"] == "denied"
    assert result["deny_reason"] == "pc_shell_system_denied"
    assert history.queue == []
    assert [row["status"] for row in gateway_store.audit_records] == ["requested", "denied"]


def test_system_default_runs_for_an_admin_on_a_managed_pc_with_user_mode_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, history, _ = _app(monkeypatch, user_mode=False, complete_after=0,
                           admin=True, managed=True)
    with TestClient(app) as client:
        response = _call(client, "pc_shell_start", {"command": "whoami"})

    assert response.status_code == 200, response.text
    assert response.json()["result"]["structuredContent"]["status"] == "running"
    assert len(history.queue) == 1
    assert history.queue[0]["user_mode"] is False
