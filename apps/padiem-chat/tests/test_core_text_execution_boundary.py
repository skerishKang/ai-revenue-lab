from __future__ import annotations

import ast
from pathlib import Path

from app.b14_client import ChatStreamEvent


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
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


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


def test_multimodal_low_level_contract_is_confined_to_image_exception():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = _class_methods(tree, "B14Client")

    image_names = _names(methods["_complete_image"])
    assert "B14MultimodalChatRequest" in image_names
    assert "B14RoutingOptions" in image_names

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
