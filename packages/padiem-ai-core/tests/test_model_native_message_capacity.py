"""Regression: old product character/turn ceilings cannot preempt provider (#4379).

No live supplier calls. Transport byte safety and trusted contexts are separate.
"""
from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    B14ChatRequest, B14ExecutionClient, B14ExecutionConfig,
    MAX_CONFIGURED_B14_RESPONSE_BYTES,
)
from padiem_ai_core.b14_multimodal import B14MultimodalChatRequest
from padiem_ai_core.contracts import AgentProfile
from padiem_ai_core.execution_runtime import (
    ExecutionRequest, ExecutionRuntime, MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
)
from padiem_ai_core.multimodal_execution_runtime import MultimodalExecutionRequest


LONG_TEXT = ("긴 질문과 대답. " * 4500) + "끝"  # > 32,000 characters
LONG_HISTORY = tuple(
    {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"}
    for i in range(130)
)


def _agent():
    return AgentProfile(
        id="capacity-test", title="Capacity", description="Safe mock execution",
        system_instruction="Use the permitted model.",
        task_type="general", optimize_for="korean", max_tokens=500,
        required_capabilities=("free",),
        model_policy={"model": "test/route"},
    )


def test_b14_transport_preserves_full_long_message_and_130_turns():
    original = LONG_HISTORY + ({"role": "user", "content": LONG_TEXT},)
    req = B14ChatRequest(messages=original, model="test/route")
    payload = req.to_payload()
    assert len(payload["messages"]) == 131
    assert payload["messages"][-1]["content"] == LONG_TEXT
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 32_000


def test_b14_http_mock_receives_long_raw_input_unchanged():
    original = LONG_HISTORY + ({"role": "user", "content": LONG_TEXT},)
    seen = []

    def handler(request):
        seen.extend(json.loads(request.content)["messages"])
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "confirmed"}}]
        })

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://mock.example"),
        httpx.MockTransport(handler),
    )
    result = asyncio.run(client.execute(B14ChatRequest(messages=original, model="test/route")))
    assert result.answer == "confirmed"
    assert len(seen) == len(original)
    assert seen[-1]["content"] == LONG_TEXT


def test_core_execution_runtime_preserves_long_input_and_history():
    class Capture:
        def __init__(self):
            self.requests = []

        async def execute(self, request):
            self.requests.append(request)
            from padiem_ai_core.b14_execution import B14ExecutionResult
            return B14ExecutionResult(answer="mocked")

    fake = Capture()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=fake)
    result = asyncio.run(runtime.run(
        ExecutionRequest(agent=_agent(), messages=LONG_HISTORY + (
            {"role": "user", "content": LONG_TEXT},
        ))
    ))
    assert result.answer == "mocked"
    sent = fake.requests[0].to_payload()["messages"]
    assert len(sent) == len(LONG_HISTORY) + 2  # one trusted system instruction
    assert sent[-1]["content"] == LONG_TEXT


def test_multimodal_b14_and_runtime_keep_long_text_and_history():
    image = "data:image/png;base64," + base64.b64encode(bytes.fromhex("89504e470d0a1a0a") + b"proof").decode()
    multimodal = {"role": "user", "content": [
        {"type": "text", "text": LONG_TEXT},
        {"type": "image_url", "image_url": {"url": image}},
    ]}
    messages = LONG_HISTORY + (multimodal,)
    packet = B14MultimodalChatRequest(messages=messages, model="test/route")
    assert packet.to_payload()["messages"][-1]["content"][0]["text"] == LONG_TEXT
    execution = MultimodalExecutionRequest(agent=_agent(), messages=messages)
    assert len(execution.messages) == 131
    assert execution.messages[-1]["content"][0]["text"] == LONG_TEXT


def test_security_guards_and_invalid_shapes_remain():
    with pytest.raises(ValueError):
        B14ChatRequest(messages=(), model="test/route")
    with pytest.raises(ValueError):
        B14ChatRequest(messages=({"role": "tool", "content": "x"},), model="test/route")
    with pytest.raises(ValueError):
        B14ExecutionConfig(base_url="https://test.example", max_response_bytes=MAX_CONFIGURED_B14_RESPONSE_BYTES + 1)
    with pytest.raises(ValueError, match="bounded context"):
        ExecutionRequest(
            agent=_agent(), messages=({"role": "user", "content": "ok"},),
            additional_system_context="x" * (MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS + 1),
        )
