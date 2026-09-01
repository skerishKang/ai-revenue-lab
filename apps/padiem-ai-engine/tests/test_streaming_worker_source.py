from __future__ import annotations

from pathlib import Path
import tomllib


APP_ROOT = Path(__file__).resolve().parents[1]


def test_worker_uses_incremental_ndjson_readable_stream_adapter() -> None:
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")

    assert "ReadableStream" in source
    assert "TextEncoder" in source
    assert "create_proxy" in source
    assert '"pull"' in source
    assert '"cancel"' in source
    assert "NDJSON_CONTENT_TYPE" in source
    # Health must be truthful: capabilities-driven, not hardcoded booleans hiding deferred state
    assert "capabilities" in source
    assert "provider_streaming_run" in source
    assert 'required_for_all_non_health_routes' in source
    assert "Access-Control-Allow-Origin" not in source
    assert "workers.dev" not in source


def test_engine_stream_contract_does_not_reimplement_b14_sse() -> None:
    source = (APP_ROOT / "app" / "streaming_service.py").read_text(encoding="utf-8")

    assert "StreamingExecutionEvent" in source
    assert "build_execution_request" in source
    assert "text/event-stream" not in source
    assert "data:" not in source
    assert "[DONE]" not in source
    assert "provider response" not in source.lower()


def test_worker_reuses_core_streaming_runtime_and_fixed_binding() -> None:
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    transport = (APP_ROOT / "app" / "cloudflare_transport.py").read_text(
        encoding="utf-8"
    )

    assert "B14StreamingClient" in source
    assert "StreamingExecutionRuntime" in source
    assert 'B14_SERVICE_BINDING_NAME = "B14_SERVICE"' in source
    assert 'B14_INTERNAL_ORIGIN = "https://b14.internal"' in transport
    assert "B14_CHAT_COMPLETIONS_PATH" in transport
    assert "B14_STREAM_PREVIEW_PATH" in transport
    assert "B14_AUTO_STREAM_PREVIEW_PATH" in transport
    assert "workers.dev" not in transport


def test_wrangler_remains_internal_service_binding_only() -> None:
    config = tomllib.loads((APP_ROOT / "wrangler.toml").read_text(encoding="utf-8"))

    assert config["workers_dev"] is False
    assert "route" not in config
    assert "routes" not in config
    assert config["services"] == [
        {
            "binding": "B14_SERVICE",
            "service": "ai-revenue-korean-ai-platform",
        }
    ]
