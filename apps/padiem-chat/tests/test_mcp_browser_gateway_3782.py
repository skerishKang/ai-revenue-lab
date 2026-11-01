"""Browser MCP continuity and ordinary questions reuse existing authorities."""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from app.local_r2 import LocalDiskR2
from app.mcp_browser_context import load_browser_context, save_browser_context
from app.mcp_gateway_dispatch import dispatch_mcp_tool
from padiem_ai_core.pc_gateway import parse_pc_gateway
from test_mcp_gateway_transport import gateway, post


OWNER = "usr_" + "a" * 32
DEVICE = "dev_" + "b" * 32
CONVERSATION = "chat_" + "c" * 32
PRINCIPAL = {"owner_id": OWNER, "device_id": DEVICE, "token_id": "mcp_" + "d" * 32}


def wire(tool, arguments, **extra):
    return {"version": 1, "source": "mcp", "token_id": PRINCIPAL["token_id"],
            "request_id": "mcp_request", "tool_id": "claw.pc." + tool,
            "arguments": arguments, **extra}


@pytest.mark.parametrize("tool,args", [
    ("browser_open", {"url": "https://example.com/"}), ("browser_read", {}),
    ("browser_screenshot", {}), ("browser_act", {"action": "click", "name": "More information"}),
])
def test_closed_gateway_browser_provenance(tool, args):
    result = parse_pc_gateway(wire(tool, args, browser_context={"url": "https://example.com/"}))
    assert result["browser_context"] == {"url": "https://example.com/"}
    for extra in ({"approval_id": "mcpa_fake"}, {"search_query": "fake"}):
        with pytest.raises(ValueError):
            parse_pc_gateway(wire(tool, args, **extra))


@pytest.mark.parametrize("args", [
    {"url": "https://example.com/"}, {"approved": "true"},
    {"page_url": "https://evil.example/"}, {"confirmation": "yes"},
])
def test_read_cannot_choose_url_or_consent(args):
    with pytest.raises(ValueError):
        parse_pc_gateway(wire("browser_read", args))


def test_private_browser_context_cannot_escape_public_url_contract():
    for url in ("http://127.0.0.1/", "file:///C:/secret", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            parse_pc_gateway(wire("browser_read", {}, browser_context={"url": url}))
    with pytest.raises(ValueError):
        parse_pc_gateway(wire("read_file", {"path": "notes.txt"}, browser_context={"url": "https://example.com/"}))


class History:
    def __init__(self, bucket):
        self.full_context_bucket = bucket
        self.deleted = False

    async def get_conversation(self, owner, conversation, *, product_scope):
        assert product_scope == "b62-chat"
        if not self.deleted and owner == OWNER and conversation == CONVERSATION:
            return {"id": conversation}
        return None


def test_context_survives_new_object_and_isolates_owner_token_device(tmp_path):
    async def scenario():
        history = History(LocalDiskR2(tmp_path))
        assert await load_browser_context(history, PRINCIPAL) is None
        assert await save_browser_context(history, PRINCIPAL, url="https://example.com/", conversation_id=CONVERSATION)
        restored = History(LocalDiskR2(tmp_path))
        assert await load_browser_context(restored, PRINCIPAL) == {"url": "https://example.com/", "conversation_id": CONVERSATION}
        for field in PRINCIPAL:
            assert await load_browser_context(restored, {**PRINCIPAL, field: "foreign"}) is None
        restored.deleted = True
        assert await load_browser_context(restored, PRINCIPAL) is None
    asyncio.run(scenario())


def test_context_unavailable_never_fabricates_page(tmp_path):
    async def scenario():
        assert await load_browser_context(History(None), PRINCIPAL) is None
        assert not await save_browser_context(History(None), PRINCIPAL, url="https://example.com/", conversation_id=CONVERSATION)
        with pytest.raises(ValueError):
            await save_browser_context(History(LocalDiskR2(tmp_path)), PRINCIPAL, url="http://127.0.0.1", conversation_id=CONVERSATION)
    asyncio.run(scenario())


@pytest.mark.parametrize("approval", [None, "mcpa_" + "e" * 32])
def test_browser_question_never_creates_or_consumes_approval_buttons(approval):
    calls = []
    class Store:
        async def audit(self, **kwargs):
            calls.append(("audit", kwargs["status"]))
        async def consume_matching_approval(self, **kwargs):
            raise AssertionError("browser must not consume file approvals")
        async def consume_approval(self, **kwargs):
            raise AssertionError("browser must not consume file approvals")
        async def create_approval(self, **kwargs):
            raise AssertionError("browser must ask in conversation")
    async def execute(request, principal, name, args, **kwargs):
        calls.append(("execute", name))
        return {"status": "confirmation_required", "answer": "정말 게시할까요?"}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        mcp_gateway_store=Store(), mcp_gateway_executor=execute)))
    result = asyncio.run(dispatch_mcp_tool(request, PRINCIPAL, "pc_browser_act",
        {"action": "click", "name": "게시"}, approval_id=approval))
    assert result["status"] == "confirmation_required"
    assert result["confirmation_kind"] == "conversation"
    assert "approval_url" not in result and "approval_id" not in result
    assert calls[0] == ("audit", "requested")
    assert calls[-1] == ("audit", "confirmation_required")
    assert (("execute", "pc_browser_act") in calls) is (approval is None)


@pytest.mark.parametrize("name,args", [
    ("pc_browser_open", {"url": "https://example.com/"}),
    ("pc_browser_read", {}), ("pc_browser_screenshot", {}),
    ("pc_browser_act", {"action": "click", "text": "More information"}),
])
def test_browser_http_tools_execute_without_file_approval(gateway, name, args):
    response = post(gateway, "tools/call", params={"name": name, "arguments": args})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False and result["structuredContent"]["status"] == "completed"
    assert gateway.calls[0][1:3] == (name, args)
    assert not gateway.store.approvals and not gateway.store.consumed


@pytest.mark.parametrize("name,args", [
    ("pc_browser_open", {"url": "http://127.0.0.1/"}),
    ("pc_browser_read", {"url": "https://example.com/"}),
    ("pc_browser_act", {"action": "click", "name": "Send", "confirmed": "true"}),
    ("pc_browser_act", {"action": "click"}),
    ("pc_browser_act", {"action": "type", "name": "Search"}),
    ("pc_browser_act", {"action": "javascript_evaluate", "text": "document.cookie"}),
])
def test_browser_http_rejects_client_authority_and_invalid_schema(gateway, name, args):
    response = post(gateway, "tools/call", params={"name": name, "arguments": args})
    assert response.json()["error"]["code"] == -32602
    assert not gateway.calls and not gateway.store.approvals


def test_browser_sensitive_question_is_normal_mcp_response_without_receipt(gateway):
    async def ask(*args, **kwargs):
        return {"status": "confirmation_required", "answer": "정말 발송할까요?"}
    gateway.app.state.mcp_gateway_executor = ask
    result = post(gateway, "tools/call", params={"name": "pc_browser_act",
        "arguments": {"action": "click", "name": "Send"}}).json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["confirmation_kind"] == "conversation"
    assert "PADIEM" in result["structuredContent"]["confirmation_instructions"]
    assert not gateway.store.approvals and not gateway.store.consumed


def test_browser_capture_is_one_image_block_and_never_inline_text(gateway):
    encoded = base64.b64encode(b"synthetic PNG fixture only").decode()
    async def capture(*args, **kwargs):
        return {"status": "completed", "answer": "현재 화면입니다.",
                "_browser_image": {"type": "image", "mimeType": "image/png", "data": encoded}}
    gateway.app.state.mcp_gateway_executor = capture
    result = post(gateway, "tools/call", params={"name": "pc_browser_screenshot", "arguments": {}}).json()["result"]
    images = [block for block in result["content"] if block["type"] == "image"]
    assert images == [{"type": "image", "mimeType": "image/png", "data": encoded}]
    assert encoded not in json.dumps(result["structuredContent"])
    assert encoded not in result["content"][0]["text"]
