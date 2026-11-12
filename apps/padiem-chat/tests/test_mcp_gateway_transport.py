"""HTTP wire contracts and exact-consent dispatch; no live PC or credentials."""
from __future__ import annotations

import base64
import copy
import json
import logging
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app.mcp_gateway_dispatch import APPROVAL_META_KEY
from app.mcp_gateway_transport import (
    LEGACY_PROTOCOL_VERSION as LEGACY,
    MCP_GATEWAY_PATH,
    MODERN_PROTOCOL_VERSION as MODERN,
    mcp_gateway_endpoint,
)


TOKEN = "fixture-only-credential"
OWNER = "usr_" + "a" * 32
DEVICE = "dev_" + "b" * 32
APPROVAL = "mcpa_" + "c" * 32
PREFIX = "io.modelcontextprotocol/"


class Store:
    def __init__(self):
        self.records = []
        self.approvals = []
        self.consumed = []
        self.receipt = None
        self.broken = False
        self.revoked = False

    async def authenticate(self, token):
        if self.broken:
            raise RuntimeError(TOKEN)
        if self.revoked or token != TOKEN:
            return None
        return {"user_id": OWNER, "device_id": DEVICE, "token_id": "mcp_fixture", "name": "시험 AI"}

    async def audit(self, **kwargs):
        self.records.append(copy.deepcopy(kwargs))

    async def create_approval(self, **kwargs):
        self.approvals.append(copy.deepcopy(kwargs))
        return {"id": APPROVAL, "expires_at": "2026-11-02T00:00:00Z"}

    async def consume_approval(self, **kwargs):
        self.consumed.append(copy.deepcopy(kwargs))
        receipt, self.receipt = self.receipt, None
        return receipt

    async def consume_matching_approval(self, **kwargs):
        receipt, self.receipt = self.receipt, None
        return receipt


@pytest.fixture
def gateway():
    store = Store()
    calls = []

    async def paired(**kwargs):
        return {"roots": ["docs"]} if kwargs == {"user_id": OWNER, "mesh_node_id": DEVICE} else None

    async def execute(request, principal, name, arguments, *, approval=None):
        calls.append((copy.deepcopy(principal), name, copy.deepcopy(arguments), approval))
        if name in {"pc_write", "pc_move", "pc_delete"} and approval is None:
            return {"status": "confirmation_required", "answer": "작업 내용을 확인해 주세요."}
        return {"status": "completed", "answer": "확인했습니다.", "output": {"value": "fixture result"}}

    app = Starlette(routes=[Route(MCP_GATEWAY_PATH, mcp_gateway_endpoint, methods=["POST", "GET", "DELETE", "OPTIONS"])])
    app.state.settings = SimpleNamespace(public_base_url="https://chat.example.test",
                                         mcp_pc_shell_enabled=True)
    app.state.mcp_gateway_store = store
    app.state.pc_device_pairing_store = SimpleNamespace(link_for=paired)
    app.state.mcp_gateway_executor = execute
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, store=store, calls=calls, app=app)


def post(gateway, method="tools/list", *, params=None, version=MODERN, request_id=1, headers=None, notification=False):
    params = copy.deepcopy(params or {})
    if version == MODERN:
        meta = params.setdefault("_meta", {})
        meta.setdefault(PREFIX + "protocolVersion", version)
        meta.setdefault(PREFIX + "clientCapabilities", {})
    body = {"jsonrpc": "2.0", "method": method, "params": params}
    if not notification:
        body["id"] = request_id
    sent_headers = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json, text/event-stream"}
    if version:
        sent_headers["MCP-Protocol-Version"] = version
    if version == MODERN:
        sent_headers["Mcp-Method"] = method
        if method == "tools/call":
            sent_headers["Mcp-Name"] = params["name"]
    sent_headers.update(headers or {})
    return gateway.client.post(MCP_GATEWAY_PATH, json=body, headers=sent_headers)


def test_modern_discovery_and_legacy_initialization_are_sessionless(gateway):
    response = post(gateway, "server/discover")
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["supportedVersions"] == [MODERN, LEGACY]
    assert result["resultType"] == "complete"
    assert result["capabilities"] == {"tools": {}}
    assert result["_meta"][PREFIX + "serverInfo"]["name"] == "padiem-pc-gateway"
    legacy = post(gateway, "initialize", version=None, params={"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}})
    assert legacy.status_code == 200
    assert legacy.json()["result"]["protocolVersion"] == LEGACY
    assert "resultType" not in legacy.json()["result"]
    assert "mcp-session-id" not in response.headers
    assert "mcp-session-id" not in legacy.headers


@pytest.mark.parametrize("version", [MODERN, LEGACY])
def test_fifteen_sorted_tools_use_closed_schemas_and_token_bound_device(gateway, version):
    # #7065 adds the fifteenth tool, pc_edit: a find-and-replace that never
    # replaces the whole file, so it is a write-lane tool and its own name.
    response = post(gateway, version=version)
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "pc_browser_act", "pc_browser_open", "pc_browser_read", "pc_browser_screenshot",
        "pc_delete", "pc_devices", "pc_edit", "pc_list", "pc_move", "pc_read", "pc_search",
        "pc_shell", "pc_shell_read", "pc_shell_start", "pc_shell_stop", "pc_write",
    ]
    for tool in tools:
        assert tool["inputSchema"]["additionalProperties"] is False
        assert "device_id" not in tool["inputSchema"]["properties"]
    pc_tools = [tool for tool in tools if tool["name"] != "pc_devices"]
    for tool in pc_tools:
        assert "device" in tool["inputSchema"]["properties"], tool["name"]
    assert "device" not in next(tool for tool in tools if tool["name"] == "pc_devices")["inputSchema"]["properties"]
    shell = next(tool for tool in tools if tool["name"] == "pc_shell")
    assert shell["inputSchema"]["required"] == ["command"]
    assert set(shell["inputSchema"]["properties"]) == {"command", "cwd", "shell", "wait_seconds", "device"}
    assert shell["inputSchema"]["properties"]["shell"]["enum"] == ["powershell", "cmd", "bash"]
    wait = shell["inputSchema"]["properties"]["wait_seconds"]
    assert wait["type"] == "integer" and wait["minimum"] == 1 and wait["maximum"] == 150
    assert gateway.calls == []


@pytest.mark.parametrize("version", [MODERN, LEGACY])
def test_pc_shell_exposes_mode_only_when_user_mode_switch_is_on(gateway, version):
    gateway.app.state.settings.mcp_pc_shell_enabled = True
    gateway.app.state.settings.mcp_pc_shell_user_mode_enabled = True
    response = post(gateway, version=version)
    tools = response.json()["result"]["tools"]
    shell = next(tool for tool in tools if tool["name"] == "pc_shell")
    start = next(tool for tool in tools if tool["name"] == "pc_shell_start")
    assert set(shell["inputSchema"]["properties"]) == {"command", "cwd", "shell", "wait_seconds", "device", "mode"}
    assert shell["inputSchema"]["properties"]["mode"]["enum"] == ["system", "user"]
    assert "mode" in start["inputSchema"]["properties"]
    assert gateway.calls == []


@pytest.mark.parametrize("value", ["false", "0", "", None, "FALSE ", " False"])
def test_pc_shell_flag_off_values_do_not_enable_the_tool(value):
    # Unset and false-ish values keep the arbitrary-command tool dark.
    from app.config import Settings
    assert Settings.from_values(mcp_pc_shell_enabled=value).mcp_pc_shell_enabled is False


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_pc_shell_flag_true_values_enable_it(value):
    from app.config import Settings
    assert Settings.from_values(mcp_pc_shell_enabled=value).mcp_pc_shell_enabled is True


def test_pc_shell_flag_rejects_a_typo_instead_of_guessing():
    # A deployment that misspells the value must not silently decide whether the
    # command tool is live.
    from app.config import ConfigError, Settings
    with pytest.raises(ConfigError):
        Settings.from_values(mcp_pc_shell_enabled="yes")


def test_unset_deployment_flag_leaves_pc_shell_off(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv("PADIEM_MCP_PC_SHELL_ENABLED", raising=False)
    assert Settings.from_env().mcp_pc_shell_enabled is False
    monkeypatch.setenv("PADIEM_MCP_PC_SHELL_ENABLED", "true")
    assert Settings.from_env().mcp_pc_shell_enabled is True
    monkeypatch.setenv("PADIEM_MCP_PC_SHELL_ENABLED", "yes")
    with pytest.raises(Exception) as raised:
        Settings.from_env()
    assert "PADIEM_MCP_PC_SHELL_ENABLED" in str(raised.value)


def test_a_bare_settings_object_leaves_pc_shell_off():
    # Anything built without the deployment environment must not advertise the
    # command tool either.
    from app.config import Settings
    assert Settings().mcp_pc_shell_enabled is False


def test_pc_shell_is_hidden_and_refused_when_the_flag_is_off(gateway):
    gateway.app.state.settings.mcp_pc_shell_enabled = False
    tools = post(gateway, "tools/list").json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "pc_browser_act", "pc_browser_open", "pc_browser_read", "pc_browser_screenshot",
        "pc_delete", "pc_devices", "pc_edit", "pc_list", "pc_move", "pc_read", "pc_search",
        "pc_write",
    ]
    off_calls = [
        ("pc_shell", {"command": "Get-Date"}),
        ("pc_shell_start", {"command": "Get-Date"}),
        ("pc_shell_read", {"job_id": "dsp_" + "a" * 32}),
        ("pc_shell_stop", {"job_id": "dsp_" + "a" * 32}),
    ]
    for name, arguments in off_calls:
        refused = post(gateway, "tools/call", params={"name": name, "arguments": arguments})
        assert refused.status_code == 400
        error = refused.json()["error"]
        assert error["code"] == -32020
        assert "tool_not_enabled" in error["message"]
        assert error["data"] == {"code": "tool_not_enabled", "tool": name}
    malformed = post(gateway, "tools/call", params={"name": "pc_shell", "arguments": {}})
    assert malformed.json()["error"]["data"] == {
        "code": "tool_not_enabled", "tool": "pc_shell",
    }
    # Nothing reached the executor and nothing was written to the audit trail.
    assert gateway.calls == [] and gateway.store.records == []
    # The rest of the gateway keeps working while pc_shell stays dark.
    read = post(gateway, "tools/call", params={"name": "pc_read", "arguments": {"path": "docs/a.txt"}})
    assert read.json()["result"]["structuredContent"]["status"] == "completed"


def test_active_owned_stop_still_reaches_executor_when_switch_is_off(gateway, monkeypatch):
    from app import mcp_gateway_shell

    gateway.app.state.settings.mcp_pc_shell_enabled = False
    async def active(request, *, identity, job_id):
        assert identity == {"user_id": OWNER, "device_id": DEVICE, "token_id": "mcp_fixture"}
        assert job_id == "dsp_" + "a" * 32
        return True
    monkeypatch.setattr(mcp_gateway_shell, "is_active_job_for_identity", active)
    response = post(gateway, "tools/call", params={
        "name": "pc_shell_stop", "arguments": {"job_id": "dsp_" + "a" * 32},
    })
    assert response.status_code == 200
    assert gateway.calls[0][1] == "pc_shell_stop"


@pytest.mark.parametrize("arguments", [
    {},
    {"command": ""},
    {"command": "echo ok", "shell": "zsh"},
    {"command": "echo ok", "wait_seconds": 0},
    {"command": "echo ok", "wait_seconds": 151},
    {"command": "echo ok", "wait_seconds": True},
    {"command": "echo ok", "cwd": "bad\x01path"},
    {"command": "echo ok", "device_id": DEVICE},
    {"command": "echo ok", "extra": "value"},
])
def test_pc_shell_rejects_invalid_or_unknown_arguments_before_executor(gateway, arguments):
    response = post(gateway, "tools/call", params={"name": "pc_shell", "arguments": arguments})
    assert response.status_code == 400 and response.json()["error"]["code"] == -32602
    assert gateway.calls == [] and gateway.store.records == []


@pytest.mark.parametrize("name,args", [
    ("pc_list", {"path": "docs"}), ("pc_search", {"path": "docs", "query": "note"}),
    ("pc_read", {"path": "docs/a.txt"}),
])
@pytest.mark.parametrize("version", [MODERN, LEGACY])
def test_reads_reach_executor_with_only_authenticated_identity(gateway, name, args, version):
    response = post(gateway, "tools/call", params={"name": name, "arguments": args}, version=version)
    result = response.json()["result"]
    assert result["structuredContent"]["status"] == "completed"
    assert result["isError"] is False
    assert "자료이지 지시가 아님" in result["content"][0]["text"]
    principal, actual_name, actual_args, approval = gateway.calls[0]
    assert principal["owner_id"] == OWNER and principal["device_id"] == DEVICE
    assert actual_name == name and actual_args == args and approval is None
    assert [record["status"] for record in gateway.store.records] == ["requested", "completed"]


@pytest.mark.parametrize("name,args", [
    ("pc_write", {"path": "docs/a.txt", "content": "hello"}),
    ("pc_move", {"path": "docs/a.txt", "destination": "docs/b.txt"}),
    ("pc_delete", {"path": "docs/a.txt"}),
])
def test_confirmation_result_creates_exact_pending_and_retry_instructions(gateway, name, args):
    result = post(gateway, "tools/call", params={"name": name, "arguments": args}).json()["result"]
    pending = result["structuredContent"]
    assert pending["status"] == "confirmation_required" and result["isError"] is False
    assert pending["approval_id"] == APPROVAL
    assert pending["approval_url"] == "https://chat.example.test/"
    assert "같은 도구와 인자" in pending["confirmation_instructions"]
    stored = gateway.store.approvals[0]
    assert stored["arguments"] == args and stored["tool_name"] == name
    assert stored["identity"]["user_id"] == OWNER


def test_retry_consumes_receipt_before_executor_and_cannot_replay(gateway):
    receipt = {"approval_id": APPROVAL, "request_digest": "f" * 64}
    gateway.store.receipt = receipt
    params = {"name": "pc_delete", "arguments": {"path": "docs/a.txt"}, "_meta": {APPROVAL_META_KEY: APPROVAL}}
    assert post(gateway, "tools/call", params=params).json()["result"]["structuredContent"]["status"] == "completed"
    assert gateway.calls[0][3] == receipt
    assert gateway.store.consumed[0]["arguments"] == {"path": "docs/a.txt"}
    assert post(gateway, "tools/call", params=params).json()["result"]["structuredContent"]["status"] == "confirmation_required"
    assert len(gateway.calls) == 1


def test_plain_tool_retry_uses_exact_matching_ui_approval_without_client_extension(gateway):
    params = {"name": "pc_write", "arguments": {"path": "docs/a.txt", "content": "hello"}}
    assert post(gateway, "tools/call", params=params).json()["result"]["structuredContent"]["status"] == "confirmation_required"
    receipt = {"approval_id": APPROVAL, "request_digest": "f" * 64}
    gateway.store.receipt = receipt
    assert post(gateway, "tools/call", params=params).json()["result"]["structuredContent"]["status"] == "completed"
    assert gateway.calls[-1][3] == receipt
    assert gateway.store.records[-1]["approval_id"] == APPROVAL


@pytest.mark.parametrize("extra", ["device_id", "owner_id", "approval_id", "approved", "user_intent", "pc_delegation"])
def test_authority_and_unknown_arguments_never_reach_executor(gateway, extra):
    response = post(gateway, "tools/call", params={"name": "pc_delete", "arguments": {"path": "docs/a.txt", extra: "injected"}})
    assert response.status_code == 400 and response.json()["error"]["code"] == -32602
    assert gateway.calls == [] and gateway.store.records == []


@pytest.mark.parametrize("headers,code", [
    ({"Mcp-Method": "tools/call"}, -32020),
    ({"Mcp-Method": ""}, -32020),
    ({"MCP-Protocol-Version": LEGACY}, -32020),
])
def test_modern_mirrored_headers_must_match_body(gateway, headers, code):
    response = post(gateway, headers=headers)
    assert response.status_code == 400 and response.json()["error"]["code"] == code


@pytest.mark.parametrize("header", ["pc_delete", "=?base64?not valid?=", ""])
def test_name_header_mismatch_is_rejected(gateway, header):
    response = post(gateway, "tools/call", params={"name": "pc_read", "arguments": {"path": "a.txt"}}, headers={"Mcp-Name": header})
    assert response.status_code == 400 and response.json()["error"]["code"] == -32020
    assert gateway.calls == []


def test_base64_name_header_is_decoded_before_matching(gateway):
    header = "=?base64?" + base64.b64encode(b"pc_read").decode() + "?="
    result = post(gateway, "tools/call", params={"name": "pc_read", "arguments": {"path": "a.txt"}}, headers={"Mcp-Name": header})
    assert result.status_code == 200


def test_missing_metadata_and_unsupported_version_have_modern_errors(gateway):
    missing = post(gateway, params={"_meta": {PREFIX + "clientCapabilities": None}})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == -32602
    unsupported = post(gateway, version="2099-01-01", params={"_meta": {PREFIX + "protocolVersion": "2099-01-01", PREFIX + "clientCapabilities": {}}}, headers={"Mcp-Method": "tools/list"})
    assert unsupported.status_code == 400 and unsupported.json()["error"]["code"] == -32022
    assert unsupported.json()["error"]["data"]["supported"] == [MODERN, LEGACY]


def test_notifications_never_execute_a_tool_and_unknown_methods_are_protocol_errors(gateway):
    notification = post(gateway, "notifications/initialized", version=LEGACY, notification=True)
    assert notification.status_code == 202 and notification.content == b""
    forged = post(gateway, "tools/call", params={"name": "pc_delete", "arguments": {"path": "a.txt"}}, version=LEGACY, notification=True)
    assert forged.status_code == 202 and gateway.calls == []
    unknown = post(gateway, "not-a-method")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == -32601
    assert post(gateway, "ping").json()["result"]["resultType"] == "complete"


@pytest.mark.parametrize("request_id", [None, True, 1.5, {}, []])
def test_invalid_request_ids_are_rejected(gateway, request_id):
    response = post(gateway, request_id=request_id)
    assert response.status_code == 400 and response.json()["error"]["code"] == -32600


@pytest.mark.parametrize("headers,status", [
    ({"Origin": "https://evil.example"}, 403),
    ({"Origin": "null"}, 403),
    ({"Accept": "application/json"}, 406),
    ({"Accept": "application/json, text/event-stream;q=0"}, 406),
    ({"Content-Type": "text/plain"}, 415),
    ({"Authorization": ""}, 401),
])
def test_http_security_and_media_contract(gateway, headers, status):
    response = post(gateway, headers=headers)
    assert response.status_code == status
    assert "no-store" in response.headers["cache-control"]
    assert gateway.calls == []


@pytest.mark.parametrize("method", ["GET", "DELETE", "OPTIONS"])
def test_no_sse_or_sessions_endpoint(gateway, method):
    response = gateway.client.request(method, MCP_GATEWAY_PATH, headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 405 and response.headers["allow"] == "POST"


def test_revoked_token_and_disconnected_pairing_are_rejected(gateway):
    gateway.store.revoked = True
    assert post(gateway).status_code == 401
    gateway.store.revoked = False

    async def disconnected(**kwargs):
        return None

    gateway.app.state.pc_device_pairing_store.link_for = disconnected
    assert post(gateway).status_code == 401
    assert gateway.calls == []


def test_failure_does_not_echo_credentials_or_exception_text(gateway, caplog):
    gateway.store.broken = True
    result = post(gateway)
    assert result.status_code == 503
    assert TOKEN not in result.text + caplog.text
    gateway.store.broken = False

    async def broken(*args, **kwargs):
        raise RuntimeError(TOKEN)

    gateway.app.state.mcp_gateway_executor = broken
    result = post(gateway, "tools/call", params={"name": "pc_read", "arguments": {"path": "a.txt"}})
    assert result.json()["result"]["isError"] is True
    assert TOKEN not in result.text + caplog.text


def test_no_execution_without_preaction_audit_and_failed_post_audit_preserves_result(gateway):
    original_audit = gateway.store.audit

    async def broken(**kwargs):
        raise RuntimeError("audit unavailable")

    gateway.store.audit = broken
    params = {"name": "pc_read", "arguments": {"path": "a.txt"}}
    assert post(gateway, "tools/call", params=params).json()["result"]["structuredContent"]["status"] == "unavailable"
    assert gateway.calls == []

    async def final_failure(**kwargs):
        if kwargs["status"] != "requested":
            raise RuntimeError("audit unavailable")
        return await original_audit(**kwargs)

    gateway.store.audit = final_failure
    outcome = post(gateway, "tools/call", params=params).json()["result"]["structuredContent"]
    assert outcome["status"] == "completed" and outcome["audit_status"] == "unavailable"


def test_batch_and_malformed_json_are_rejected(gateway):
    headers = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    batch = gateway.client.post(MCP_GATEWAY_PATH, json=[], headers=headers)
    assert batch.status_code == 400 and batch.json()["error"]["code"] == -32600
    malformed = gateway.client.post(MCP_GATEWAY_PATH, content="{", headers=headers)
    assert malformed.status_code == 400 and malformed.json()["error"]["code"] == -32700


def test_existing_request_log_contains_only_bounded_operation_metadata(gateway, caplog):
    from app.mcp_gateway_dispatch import _LOGGER
    _LOGGER.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            post(gateway, "tools/call", params={"name": "pc_write", "arguments": {
                "path": "docs/private-file.txt", "content": "private document content"}})
    finally:
        _LOGGER.removeHandler(caplog.handler)
    events = [json.loads(record.getMessage()) for record in caplog.records if record.name == "padiem_chat.request"]
    assert [event["status"] for event in events] == ["requested", "confirmation_required"]
    assert "token_id" not in events[-1] and events[-1]["tool"] == "pc_write"
    assert events[-1]["approval_id"] == APPROVAL and len(events[-1]["request_digest"]) == 64
    for excluded in (TOKEN, OWNER, DEVICE, "private-file", "private document content"):
        assert excluded not in caplog.text
