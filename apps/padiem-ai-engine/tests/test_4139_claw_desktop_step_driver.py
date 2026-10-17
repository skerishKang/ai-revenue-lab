"""Focused structured desktop step contract, without provider or PC side effects."""
import asyncio
from types import SimpleNamespace

import pytest

from app.claw_desktop_step_driver import (
    DesktopStepContractError, StructuredDesktopStepDriver,
)


def test_model_selects_next_tool_from_real_jpeg_observation():
    calls = []
    async def image_loader(**args):
        assert args["receipt"] == "owned-capture"
        return b"\xff\xd8\xff\x00"
    async def model(**kwargs):
        calls.append(kwargs)
        assert kwargs["observations"][0]["image_jpeg"].startswith(b"\xff\xd8\xff")
        return {"action": "tool", "tool_id": "claw.desktop.click",
                "arguments": {"x": 42, "y": 80}}
    result = SimpleNamespace(
        tool_id="claw.desktop.capture",
        output_copy=lambda: {"capture_receipt": "owned-capture"},
        event=SimpleNamespace(to_public_dict=lambda: {"status": "succeeded"}),
    )
    driver = StructuredDesktopStepDriver(
        select_step=model, read_capture=image_loader,
        allowed_tool_ids=frozenset({"claw.desktop.click"}),
    )
    context = SimpleNamespace(tool_results=(result,))
    choice = asyncio.run(driver.next_step(context, compiled_profile=None))
    assert choice.invocation.tool_id == "claw.desktop.click"
    assert choice.invocation.arguments_copy() == {"x": 42, "y": 80}
    assert len(calls) == 1


def test_unowned_capture_does_not_invoke_model_or_tool():
    calls = []
    async def image_loader(**kwargs):
        return None
    async def model(**kwargs):
        calls.append(1)
        return {"action": "complete", "answer": "done"}
    result = SimpleNamespace(
        tool_id="claw.desktop.capture",
        output_copy=lambda: {"capture_receipt": "foreign"},
        event=SimpleNamespace(to_public_dict=lambda: {}),
    )
    driver = StructuredDesktopStepDriver(
        select_step=model, read_capture=image_loader,
        allowed_tool_ids=frozenset({"claw.desktop.click"}),
    )
    with pytest.raises(DesktopStepContractError, match="unavailable"):
        asyncio.run(driver.next_step(SimpleNamespace(tool_results=(result,)), None))
    assert calls == []



def test_admitted_owner_tool_runtime_calls_signed_chat():
    import hashlib
    import hmac
    import json
    from types import SimpleNamespace
    from app.claw_desktop_step_driver import (
        _ENGINE_DESKTOP_OWNER, build_claw_desktop_tool_binding,
        DESKTOP_AGENT_ID, DESKTOP_CANONICAL_CAPTURE, DESKTOP_CAPTURE_ID,
    )
    from padiem_ai_core.tool_runtime import ToolInvocation

    secret = "x" * 32
    seen = []

    class Request:
        def __init__(self, url, *, method, headers, body):
            self.url, self.method, self.headers, self.body = url, method, headers, body
            self.js_object = self

    class Service:
        async def fetch(self, request):
            assert request.url == "https://padiem-chat.internal/internal/claw/engine-desktop"
            assert request.method == "POST"
            proof = hmac.new(secret.encode(), (
                request.headers["X-Claw-Engine-Time"] + "."
            ).encode() + request.body.encode(), hashlib.sha256).hexdigest()
            assert hmac.compare_digest(proof, request.headers["X-Claw-Engine-Proof"])
            body = json.loads(request.body)
            if body.get("mode") == "status":
                assert body == {
                    "subject_id": "sub_verified",
                    "run_id": "run_verified",
                    "dispatch_id": "dispatch_once",
                    "mode": "status",
                }
                return SimpleNamespace(
                    status=200,
                    text=lambda: asyncio.sleep(0, result=json.dumps({
                        "ok": True, "dispatch": {
                            "dispatch_id": "dispatch_once",
                            "run_id": "run_verified", "kind": "desktop",
                            "state": "done", "result_sha256": "a" * 64,
                        },
                    })),
                )
            assert set(body) == {"subject_id", "run_id", "device_id", "desktop_op"}
            assert body == {
                "subject_id": "sub_verified", "run_id": "run_verified",
                "device_id": "device_verified", "desktop_op": "desktop:capture",
            }
            seen.append(body)
            return SimpleNamespace(
                status=200,
                text=lambda: asyncio.sleep(0, result=json.dumps({
                    "ok": True, "dispatch": {
                        "dispatch_id": "dispatch_once",
                        "run_id": "run_verified", "kind": "desktop", "state": "pending",
                    },
                })),
            )

    binding = build_claw_desktop_tool_binding(
        service=Service(), request_factory=Request, secret=secret,
    )
    authority = binding.resolve_authority(DESKTOP_AGENT_ID)
    invocation = ToolInvocation(
        tool_id=DESKTOP_CAPTURE_ID, arguments={"device_id": "device_verified"}
    )
    token = _ENGINE_DESKTOP_OWNER.set(("sub_verified", "run_verified"))
    try:
        result = asyncio.run(binding.tool_runtime.execute(
            invocation, authority.compiled.runtime_profile, authority.authorization,
        ))
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)
    assert result.output_copy()["dispatch_id"] == "dispatch_once"
    assert result.output_copy()["execution_confirmed"] is True
    assert result.output_copy()["capture_receipt"] == "dispatch_once"
    assert len(seen) == 1


def test_unadmitted_owner_cannot_trigger_chat_transport():
    from app.claw_desktop_step_driver import (
        _ENGINE_DESKTOP_OWNER, build_claw_desktop_tool_binding,
        DESKTOP_AGENT_ID, DESKTOP_CAPTURE_ID,
    )
    from padiem_ai_core.tool_runtime import ToolInvocation
    from padiem_ai_core.tool_runtime import ToolRuntimeError

    class NoService:
        async def fetch(self, request):
            raise AssertionError("unauthorized transport called")

    binding = build_claw_desktop_tool_binding(
        service=NoService(), request_factory=lambda *a, **k: None,
        secret="x" * 32,
    )
    authority = binding.resolve_authority(DESKTOP_AGENT_ID)
    token = _ENGINE_DESKTOP_OWNER.set(None)
    try:
        with pytest.raises(ToolRuntimeError):
            asyncio.run(binding.tool_runtime.execute(
                ToolInvocation(
                    tool_id=DESKTOP_CAPTURE_ID,
                    arguments={"device_id": "device_verified"},
                ),
                authority.compiled.runtime_profile, authority.authorization,
            ))
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)
