from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.app_factory import create_app, health
from app.b14_client import B14Client, ChatRuntimeError, _chat_error, _translate_execution_error
from app.config import Settings
from app.usage_gate import InMemoryUsageCounterStore
from padiem_ai_core import ExecutionRuntimeError, RunMetadata, RunStatus

USER_MESSAGES = [{"role": "user", "content": "시스템 상태를 알려주세요."}]
VALID_SALT = "a" * 32


def test_upstream_error_mappings_distinguish_rate_limiting_and_binding():
    """Verify internal classification of B14/Core upstream error codes."""
    # 1. Rate limited upstream maps to 503 upstream_busy
    rate_limited = _chat_error("upstream_rate_limited")
    assert rate_limited.status_code == 503
    assert rate_limited.code == "upstream_busy"
    assert "사용자가 많습니다" in rate_limited.user_message

    # 2. Upstream binding unavailable is 503 upstream_binding_unavailable, distinct from upstream_busy
    binding_unavailable = ChatRuntimeError(
        503,
        "upstream_binding_unavailable",
        "AI 내부 스트리밍 연결이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
    )
    assert binding_unavailable.status_code == 503
    assert binding_unavailable.code == "upstream_binding_unavailable"
    assert binding_unavailable.code != rate_limited.code
    assert binding_unavailable.user_message != rate_limited.user_message

    # 3. Upstream timeout maps to 504 upstream_timeout
    timeout_err = _chat_error("upstream_timeout")
    assert timeout_err.status_code == 504
    assert timeout_err.code == "upstream_timeout"

    # 4. Upstream unavailable maps to 502 upstream_unavailable
    unavailable_err = _chat_error("upstream_unavailable")
    assert unavailable_err.status_code == 502
    assert unavailable_err.code == "upstream_unavailable"

    # 5. Generic or unknown upstream errors map to 502 upstream_error
    generic_err = _chat_error("unknown_failure_code")
    assert generic_err.status_code == 502
    assert generic_err.code == "upstream_error"
    assert generic_err.code != rate_limited.code


def test_translate_execution_error_from_padiem_ai_core():
    """Verify translation of product-neutral ExecutionRuntimeError into B62 ChatRuntimeError."""
    metadata = RunMetadata(
        trace_id="tr_diagnostics_1",
        app_id="padiem-chat",
        agent_id="b62-auto",
        status=RunStatus.FAILED,
    )
    core_rate_limit = ExecutionRuntimeError(
        "upstream_rate_limited",
        "Model execution is temporarily rate limited.",
        metadata=metadata,
        retryable=True,
    )
    b62_err = _translate_execution_error(core_rate_limit)
    assert b62_err.status_code == 503
    assert b62_err.code == "upstream_busy"
    assert "지금 사용자가 많습니다" in b62_err.user_message
    assert "Model execution is temporarily rate limited" not in b62_err.user_message


@pytest.mark.asyncio
async def test_b14_client_stream_binding_unavailable_is_distinct_from_rate_limit():
    """Verify stream client raises distinct upstream_binding_unavailable when binding is missing."""
    client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal"),
        stream_transport=None,
        require_service_binding=True,
    )

    with pytest.raises(ChatRuntimeError) as exc_info:
        async for _ in client.stream_text_auto(USER_MESSAGES):
            pass

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "upstream_binding_unavailable"
    assert exc_info.value.code != "upstream_busy"


@pytest.mark.asyncio
async def test_b14_client_stream_upstream_rate_limited_maps_to_upstream_busy():
    """Verify stream client raises upstream_busy on HTTP 429 from upstream."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited by upstream model cluster"})

    client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal"),
        stream_transport=httpx.MockTransport(handler),
        require_service_binding=True,
    )

    with pytest.raises(ChatRuntimeError) as exc_info:
        async for _ in client.stream_text_auto(USER_MESSAGES):
            pass

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "upstream_busy"
    # No secret or internal detail leaked
    assert "rate limited by upstream model cluster" not in exc_info.value.user_message


@pytest.mark.asyncio
async def test_api_chat_stream_preserves_error_status_and_avoids_fake_success():
    """Verify /api/chat/stream returns real 503/504 JSON errors instead of fake answers."""
    async def handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "concurrency limit exceeded"})

    app_429 = create_app(
        Settings.from_values(
            runtime_mode="b14",
            b14_base_url="https://b14.internal",
            quota_salt=VALID_SALT,
        ),
        transport=httpx.MockTransport(handler_429),
        usage_store=InMemoryUsageCounterStore(),
    )
    app_429.state.b14_client = B14Client(
        Settings.from_values(
            runtime_mode="b14",
            b14_base_url="https://b14.internal",
            quota_salt=VALID_SALT,
        ),
        stream_transport=httpx.MockTransport(handler_429),
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_429), base_url="http://test") as client:
        response = await client.post(
            "/api/chat/stream",
            json={"messages": USER_MESSAGES, "mode": "auto"},
            headers={"cf-connecting-ip": "203.0.113.10"},
        )
        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "upstream_busy"
        assert "사용자가 많습니다" in data["error"]["message"]
        assert "concurrency limit exceeded" not in response.text
        assert "delta" not in response.text


@pytest.mark.asyncio
async def test_health_endpoint_metadata_is_non_secret_booleans_and_statuses():
    """Verify health endpoint exposes only non-secret boolean flags and safe status strings."""
    settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        live_enabled="true",
        quota_salt=VALID_SALT,
        session_secret="s" * 32,
        google_client_secret="secret_google_secret",
        firecrawl_api_key="secret_firecrawl_key",
        daum_rest_api_key="secret_daum_key",
    )
    app = create_app(settings, usage_store=InMemoryUsageCounterStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        payload = response.json()

        allowed_keys = {
            "status",
            "app",
            "runtime",
            "b14_configured",
            "web_tools_ready",
            "deep_research_ready",
            "image_attachment_ready",
            "text_document_attachment_ready",
            "auth_configured",
            "history_store_bound",
            "projects_code_ready",
            "project_files_code_ready",
            "project_file_store_bound",
            "saved_outputs_code_ready",
            "saved_output_store_bound",
            "quota_store_bound",
            "live_abuse_gate_ready",
            "live_enabled",
            "canonical_identity_bound",
            "identity_shadow_bound",
            # #1975: boolean-only telemetry channel presence flag.
            "request_telemetry_enabled",
        }
        assert set(payload.keys()) == allowed_keys

        raw_text = response.text
        for secret in (
            VALID_SALT,
            "s" * 32,
            "secret_google_secret",
            "secret_firecrawl_key",
            "secret_daum_key",
        ):
            assert secret not in raw_text
