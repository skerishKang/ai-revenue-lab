from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT_SOURCE = (ROOT / "app/b14_client.py").read_text(encoding="utf-8")


def test_b62_image_completion_uses_product_neutral_core_multimodal_facade() -> None:
    assert "MultimodalExecutionRequest" in CLIENT_SOURCE
    assert "MultimodalExecutionRuntime" in CLIENT_SOURCE
    assert "_multimodal_execution_request(" in CLIENT_SOURCE
    assert "execution = await runtime.run(request)" in CLIENT_SOURCE


def test_b62_no_longer_constructs_low_level_multimodal_b14_contract() -> None:
    assert "B14MultimodalChatRequest" not in CLIENT_SOURCE
    assert "B14RoutingOptions" not in CLIENT_SOURCE
    assert "B14ExecutionError" not in CLIENT_SOURCE
    assert "_translate_core_error" not in CLIENT_SOURCE
    assert "upstream_messages" not in CLIENT_SOURCE


def test_image_capability_fail_closed_gate_remains_product_owned() -> None:
    assert 'if not model_supports(model, "image"):' in CLIENT_SOURCE
    assert '"image_model_unavailable"' in CLIENT_SOURCE
    assert 'required_capabilities=("chat", "image")' in CLIENT_SOURCE


def test_text_and_stream_core_paths_remain_present() -> None:
    assert "ExecutionRequest" in CLIENT_SOURCE
    assert "ExecutionRuntime" in CLIENT_SOURCE
    assert "StreamingExecutionRuntime" in CLIENT_SOURCE
    assert 'required_capabilities=("chat",)' in CLIENT_SOURCE
