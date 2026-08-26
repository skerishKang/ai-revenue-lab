from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    B14_CHAT_COMPLETIONS_PATH,
    MAX_B14_RESPONSE_BYTES,
    MAX_CONFIGURED_B14_RESPONSE_BYTES,
    B14ChatRequest,
    B14ExecutionClient,
    B14ExecutionConfig,
    B14ExecutionError,
    B14RoutingOptions,
)


def run(coro):
    return asyncio.run(coro)


def success_payload(**overrides):
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "  반갑습니다.  "}}],
        "business14": {
            "request_id": "b14req_shared123",
            "route_mode": "auto",
            "selected_provider": "openrouter",
            "selected_model": "openrouter/free",
            "selected_upstream_model": "provider/free-model",
            "selected_route_id": "openrouter:free",
            "actual_response_model": "provider/free-model",
            "reason_codes": ["AUTO_ROUTE", "COST_PREFERENCE"],
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "configured",
            "estimated_krw": None,
            "private_unknown_field": "must-not-surface",
        },
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
        "private_top_level": "must-not-surface",
    }
    payload.update(overrides)
    return payload


def request_fixture() -> B14ChatRequest:
    return B14ChatRequest(
        messages=(
            {"role": "system", "content": "Answer clearly."},
            {"role": "user", "content": "안녕하세요"},
        ),
        max_tokens=700,
        routing=B14RoutingOptions(
            task_type="general",
            required_capabilities=("free",),
            optimize_for="korean",
            allow_external_fallback=True,
            provider_order=(),
            max_attempts=3,
        ),
    )


def test_config_normalizes_http_https_base_urls_and_builds_fixed_endpoint() -> None:
    https = B14ExecutionConfig(base_url=" https://b14.example/root/ ")
    assert https.base_url == "https://b14.example/root"
    assert https.chat_completions_url == "https://b14.example/root" + B14_CHAT_COMPLETIONS_PATH
    assert https.timeout_seconds == 20.0
    assert https.max_response_bytes == MAX_B14_RESPONSE_BYTES

    http = B14ExecutionConfig(base_url="http://localhost:8787/")
    assert http.base_url == "http://localhost:8787"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "example.com",
        "ftp://example.com",
        "https://user:pw@example.com",
        "https://example.com?next=evil",
        "https://example.com#frag",
        "https://example.com:99999",
        "https:///missing-host",
    ],
)
def test_config_rejects_invalid_base_urls(bad: str) -> None:
    with pytest.raises(ValueError):
        B14ExecutionConfig(base_url=bad)


@pytest.mark.parametrize("bad", [0, 0.9, 60.1, True, float("inf"), "20"])
def test_config_rejects_invalid_timeout(bad) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        B14ExecutionConfig(base_url="https://b14.example", timeout_seconds=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, -1, True, MAX_CONFIGURED_B14_RESPONSE_BYTES + 1, 1.5])
def test_config_rejects_invalid_response_cap(bad) -> None:
    with pytest.raises(ValueError, match="max_response_bytes"):
        B14ExecutionConfig(base_url="https://b14.example", max_response_bytes=bad)  # type: ignore[arg-type]


def test_config_public_state_contains_no_credentials_field() -> None:
    config = B14ExecutionConfig(base_url="https://b14.example")
    public = config.to_public_dict()
    assert public == {
        "base_url": "https://b14.example",
        "timeout_seconds": 20.0,
        "max_response_bytes": MAX_B14_RESPONSE_BYTES,
    }
    serialized = json.dumps(public)
    assert "key" not in serialized.lower()
    assert "authorization" not in serialized.lower()


def test_routing_options_serialize_current_b14_contract_exactly() -> None:
    options = B14RoutingOptions(
        task_type="GENERAL",
        required_capabilities=["free", "chat"],
        optimize_for="KOREAN",
        allow_external_fallback=False,
        provider_order=["provider-a", "provider-b"],
        max_attempts=2,
    )
    assert options.to_dict() == {
        "task_type": "general",
        "required_capabilities": ["free", "chat"],
        "optimize_for": "korean",
        "allow_external_fallback": False,
        "provider_order": ["provider-a", "provider-b"],
        "max_attempts": 2,
    }


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"task_type": "medical"}, "task_type"),
        ({"optimize_for": "best"}, "optimize_for"),
        ({"max_attempts": 0}, "max_attempts"),
        ({"max_attempts": 6}, "max_attempts"),
        ({"max_attempts": True}, "max_attempts"),
        ({"allow_external_fallback": "yes"}, "allow_external_fallback"),
        ({"required_capabilities": ["free", "free"]}, "duplicates"),
        ({"provider_order": "provider-a"}, "sequence"),
    ],
)
def test_routing_options_fail_closed_before_network(kwargs, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        B14RoutingOptions(**kwargs)


def test_request_defaults_to_auto_and_does_not_add_stream_or_tools() -> None:
    request = B14ChatRequest(messages=({"role": "user", "content": " hello "},))
    payload = request.to_payload()
    assert payload == {
        "model": "b14/auto",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.2,
    }
    assert "stream" not in payload
    assert "tools" not in payload
    assert "business14" not in payload


def test_request_copies_messages_and_is_not_affected_by_caller_mutation() -> None:
    messages = [{"role": "user", "content": "original"}]
    request = B14ChatRequest(messages=messages)  # type: ignore[arg-type]
    messages[0]["content"] = "mutated"
    messages.append({"role": "assistant", "content": "extra"})
    assert request.to_payload()["messages"] == [{"role": "user", "content": "original"}]
    with pytest.raises(TypeError):
        request.messages[0]["content"] = "cannot mutate"  # type: ignore[index]


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "user", "content": ""}],
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": "x", "name": "unexpected"}],
        [{"content": "missing role"}],
    ],
)
def test_request_rejects_obvious_invalid_messages(messages) -> None:
    with pytest.raises(ValueError):
        B14ChatRequest(messages=messages)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": ""},
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"temperature": True},
        {"max_tokens": 0},
        {"max_tokens": 4097},
        {"max_tokens": True},
    ],
)
def test_request_rejects_invalid_request_fields(kwargs) -> None:
    with pytest.raises(ValueError):
        B14ChatRequest(messages=({"role": "user", "content": "x"},), **kwargs)


def test_client_uses_exact_endpoint_payload_and_no_provider_credentials() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["headers"] = {key.lower(): value for key, value in request.headers.items()}
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=success_payload())

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    result = run(client.execute(request_fixture()))

    assert seen["url"] == "https://b14.example" + B14_CHAT_COMPLETIONS_PATH
    assert seen["method"] == "POST"
    assert seen["body"] == {
        "model": "b14/auto",
        "messages": [
            {"role": "system", "content": "Answer clearly."},
            {"role": "user", "content": "안녕하세요"},
        ],
        "temperature": 0.2,
        "max_tokens": 700,
        "business14": {
            "task_type": "general",
            "required_capabilities": ["free"],
            "optimize_for": "korean",
            "allow_external_fallback": True,
            "provider_order": [],
            "max_attempts": 3,
        },
    }
    assert "authorization" not in seen["headers"]
    assert "x-business14-provider-key" not in seen["headers"]
    assert "cookie" not in seen["headers"]
    assert result.answer == "반갑습니다."


def test_client_does_not_follow_redirects_or_duplicate_calls() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_request_error"
    assert info.value.upstream_status_code == 302
    assert calls == 1


def test_response_byte_cap_is_enforced_while_streaming() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 33)

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example", max_response_bytes=32),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_response_too_large"


def test_timeout_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail", request=request)

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_timeout"
    assert info.value.retryable is True
    assert "private timeout detail" not in info.value.safe_message


def test_generic_transport_error_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("PRIVATE-ENDPOINT-DETAIL", request=request)

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_unavailable"
    assert info.value.retryable is True
    assert "PRIVATE-ENDPOINT-DETAIL" not in info.value.safe_message


@pytest.mark.parametrize("status", [401, 403])
def test_auth_statuses_are_normalized_separately(status: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"private": "DO-NOT-LEAK"})

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_auth_error"
    assert info.value.upstream_status_code == status
    assert info.value.retryable is False
    assert "DO-NOT-LEAK" not in str(info.value)


def test_rate_limit_is_normalized_and_retryable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"secret": "PRIVATE-UPSTREAM-BODY"})

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_rate_limited"
    assert info.value.retryable is True
    assert "PRIVATE-UPSTREAM-BODY" not in json.dumps(info.value.to_public_dict())


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "upstream_request_error", False),
        (404, "upstream_request_error", False),
        (500, "upstream_server_error", True),
        (503, "upstream_server_error", True),
    ],
)
def test_other_http_failures_are_classified(status: int, code: str, retryable: bool) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"PRIVATE RAW BODY")

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == code
    assert info.value.retryable is retryable
    assert "PRIVATE RAW BODY" not in info.value.safe_message


@pytest.mark.parametrize("content", [b"not-json", b"\xff"])
def test_malformed_json_or_utf8_fails_closed(content: bytes) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "malformed_upstream"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 123}}]},
    ],
)
def test_missing_or_invalid_assistant_content_fails_closed(payload) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "malformed_upstream"


def test_empty_assistant_answer_has_distinct_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "   "}}]},
        )

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.example"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "empty_upstream_answer"


def test_success_parses_bounded_route_and_usage_metadata_without_raw_unknowns() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=success_payload())

    result = run(
        B14ExecutionClient(
            B14ExecutionConfig(base_url="https://b14.example"),
            httpx.MockTransport(handler),
        ).execute(request_fixture())
    )
    assert result.answer == "반갑습니다."
    assert result.route.request_id == "b14req_shared123"
    assert result.route.route_mode == "auto"
    assert result.route.selected_provider == "openrouter"
    assert result.route.selected_model == "openrouter/free"
    assert result.route.selected_upstream_model == "provider/free-model"
    assert result.route.selected_route_id == "openrouter:free"
    assert result.route.actual_response_model == "provider/free-model"
    assert result.route.reason_codes == ("AUTO_ROUTE", "COST_PREFERENCE")
    assert result.route.fallback_used is False
    assert result.route.attempt_count == 1
    assert result.route.route_evidence_status == "configured"
    assert result.route.estimated_krw is None
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 8
    assert result.usage.total_tokens == 20

    public = result.to_public_dict()
    serialized = json.dumps(public, ensure_ascii=False)
    assert "private_unknown_field" not in serialized
    assert "private_top_level" not in serialized
    assert set(public["route"]) == {
        "request_id",
        "route_mode",
        "selected_provider",
        "selected_model",
        "selected_upstream_model",
        "selected_route_id",
        "actual_response_model",
        "reason_codes",
        "fallback_used",
        "attempt_count",
        "route_evidence_status",
        "estimated_krw",
    }


def test_missing_or_invalid_optional_metadata_remains_unknown_not_fabricated() -> None:
    payload = {
        "choices": [{"message": {"content": "ok"}}],
        "business14": {
            "request_id": 123,
            "reason_codes": "not-a-list",
            "fallback_used": "no",
            "attempt_count": -1,
            "estimated_krw": float("nan"),
        },
        "usage": {
            "prompt_tokens": -1,
            "completion_tokens": "8",
            "total_tokens": True,
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = run(
        B14ExecutionClient(
            B14ExecutionConfig(base_url="https://b14.example"),
            httpx.MockTransport(handler),
        ).execute(B14ChatRequest(messages=({"role": "user", "content": "x"},)))
    )
    assert result.answer == "ok"
    assert result.route.request_id is None
    assert result.route.reason_codes == ()
    assert result.route.fallback_used is None
    assert result.route.attempt_count is None
    assert result.route.estimated_krw is None
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None


def test_missing_business14_and_usage_metadata_is_valid() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    result = run(
        B14ExecutionClient(
            B14ExecutionConfig(base_url="https://b14.example"),
            httpx.MockTransport(handler),
        ).execute(B14ChatRequest(messages=({"role": "user", "content": "x"},)))
    )
    assert result.route.request_id is None
    assert result.route.selected_provider is None
    assert result.route.reason_codes == ()
    assert result.usage.to_public_dict() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
