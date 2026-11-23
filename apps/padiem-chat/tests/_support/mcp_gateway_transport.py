"""MCP gateway transport shared test preparation (#8061).

Moved out of test_mcp_gateway_transport so the test-to-test import ratchet
does not grow: the hub and its consumers all import these names from here.
The fixture app serves the real transport endpoint with recording fakes for
the store and executor; nothing here calls a real provider.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app.mcp_gateway_transport import (
    LEGACY_PROTOCOL_VERSION as LEGACY,
    MCP_GATEWAY_PATH,
    MODERN_PROTOCOL_VERSION as MODERN,
    mcp_gateway_endpoint,
)

__all__ = [
    "APPROVAL", "DEVICE", "LEGACY", "MODERN", "OWNER", "PREFIX", "TOKEN",
    "Store", "gateway", "post",
]

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


