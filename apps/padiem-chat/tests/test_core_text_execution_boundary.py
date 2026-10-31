from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from padiem_ai_core import B14StreamEvent
from padiem_ai_core.b14_streaming import B14StreamToolCall

import app.b14_client as b14_module
from app.b14_client import ChatStreamEvent, ChatToolCall
from app.chat_pc_drive import CHAT_PC_TOOL_DEFINITIONS
from app.task_modes import get_task_mode


SOURCE_PATH = Path(__file__).resolve().parents[1] / "app" / "b14_client.py"


def _class_methods(tree: ast.Module, class_name: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    target = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name: node
        for node in target.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Name):
            names.add(item.id)
        elif isinstance(item, ast.Attribute):
            names.add(item.attr)
    return names


def test_b62_text_execution_is_locked_to_high_level_core_runtime():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = _class_methods(tree, "B14Client")

    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "padiem_ai_core"
        for alias in node.names
    }
    assert {"ExecutionRequest", "ExecutionRuntime", "StreamingExecutionRuntime"} <= imports
    assert "B14ChatRequest" not in imports
    assert "B14StreamEvent" not in imports

    auto_names = _names(methods["stream_text_auto"])
    stream_core_names = _names(methods["_stream_core"])
    complete_text_names = _names(methods["_complete_text"])

    assert "_execution_request" in auto_names
    assert "_stream_core" in auto_names
    assert "StreamingExecutionRuntime" in stream_core_names
    assert "_execution_request" in complete_text_names
    assert "ExecutionRuntime" in complete_text_names

    forbidden = {"B14ChatRequest", "B14MultimodalChatRequest", "B14RoutingOptions"}
    assert auto_names.isdisjoint(forbidden)
    assert complete_text_names.isdisjoint(forbidden)


def test_multimodal_execution_is_locked_to_high_level_core_runtime():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = _class_methods(tree, "B14Client")

    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "padiem_ai_core"
        for alias in node.names
    }
    assert {"MultimodalExecutionRequest", "MultimodalExecutionRuntime"} <= imports
    assert "B14MultimodalChatRequest" not in imports
    assert "B14RoutingOptions" not in imports
    assert "B14ExecutionError" not in imports

    image_names = _names(methods["_complete_image"])
    assert "_multimodal_execution_request" in image_names
    assert "MultimodalExecutionRuntime" in image_names
    assert "ExecutionRuntimeError" in image_names
    assert "B14MultimodalChatRequest" not in image_names
    assert "B14RoutingOptions" not in image_names

    for method_name in ("stream_text_auto", "stream_text_preview", "_complete_text"):
        names = _names(methods[method_name])
        assert "B14MultimodalChatRequest" not in names
        assert "B14RoutingOptions" not in names


def test_b62_stream_projection_has_no_route_or_model_fields():
    event = ChatStreamEvent(delta_content="한 조각")

    assert event.delta_content == "한 조각"
    assert event.done is False
    assert not hasattr(event, "route")
    assert not hasattr(event, "model")
    assert not hasattr(event, "provider")


def test_stream_projection_carries_the_pending_core_tool_call(monkeypatch):
    """The real Core stream event carries the model's tool call unchanged."""
    script = [
        B14StreamEvent(
            tool_call=B14StreamToolCall(
                id="call_1", name="files_list", arguments={}, index=0,
            ),
            finish_reason="tool_calls",
        ),
        B14StreamEvent(delta_content="본문"),
        B14StreamEvent(done=True, finish_reason="stop"),
    ]

    class _ScriptedB14StreamClient:
        def __init__(self, *args, **kwargs):
            pass

        def _events(self):
            async def _iterate():
                for event in script:
                    yield event

            return _iterate()

        def stream(self, request):
            return self._events()

        def stream_auto(self, request):
            return self._events()

    monkeypatch.setattr(b14_module, "B14StreamingClient", _ScriptedB14StreamClient)
    client = b14_module.B14Client(
        b14_module.Settings.from_values(
            runtime_mode="mock", b14_base_url="https://b14.example.test",
        )
    )
    request = b14_module._execution_request(
        [{"role": "user", "content": "질문"}],
        skill=get_task_mode(),
        model="google/gemini-3.1-flash-lite",
        required_capabilities=("chat",),
        additional_system_context=None,
        tools=CHAT_PC_TOOL_DEFINITIONS,
        tool_choice="auto",
    )

    async def scenario():
        return [event async for event in client._stream_core(request)]

    projected = asyncio.run(scenario())

    assert projected[0].tool_call == ChatToolCall(
        id="call_1", name="files_list", arguments={}, index=0,
    )
    assert projected[0].finish_reason == "tool_calls"
    assert projected[1].delta_content == "본문"
    assert projected[1].finish_reason is None
    assert projected[2].done is True
    assert projected[2].finish_reason == "stop"


def test_tool_call_projection_copies_the_validated_core_call():
    call = B14StreamToolCall(
        id="call_1", name="files_list", arguments={"depth": 1}, index=2,
    )
    assert b14_module._project_tool_call(call) == ChatToolCall(
        id="call_1", name="files_list", arguments={"depth": 1}, index=2,
    )
    assert b14_module._project_tool_call(None) is None


def test_tool_call_projection_preserves_the_opaque_provider_signature():
    call = B14StreamToolCall(
        id="call_1", name="files_list", arguments={"depth": 1}, index=2,
        signature="sig_native_abc123",
    )
    projected = b14_module._project_tool_call(call)
    assert projected.signature == "sig_native_abc123"
    # The signature is relay-only data and carries no product authority.
    assert projected.name == "files_list" and projected.arguments == {"depth": 1}
