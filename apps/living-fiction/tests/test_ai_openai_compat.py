from __future__ import annotations

import json
from unittest.mock import ANY, patch

import pytest
from pydantic import BaseModel, Field

from app.domain.enums import CostClass, ProviderErrorCategory


# ── helper schema for structured generation tests ────────────────────────


class _TestResponse(BaseModel):
    value: str = Field(min_length=1)
    number: int = Field(ge=0)


# ── config / factory tests ───────────────────────────────────────────────


def test_mock_provider_does_not_require_api_key():
    from app.config import settings as s
    from app.ai.mock import MockProvider

    saved = s.ai_provider, s.ai_api_key
    s.ai_provider = "mock"
    s.ai_api_key = ""
    s.validate_ai_provider()
    p = MockProvider()
    assert p.provider_name == "mock"
    s.ai_provider, s.ai_api_key = saved


def test_live_provider_requires_api_key():
    from app.config import settings as s

    saved = s.ai_provider, s.ai_api_key, s.ai_model
    s.ai_provider = "opencode_go"
    s.ai_api_key = ""
    s.ai_model = "deepseek-v4-flash"
    with pytest.raises(ValueError, match="LF_AI_API_KEY"):
        s.validate_ai_provider()
    s.ai_provider, s.ai_api_key, s.ai_model = saved


def test_live_provider_requires_model():
    from app.config import settings as s

    saved = s.ai_provider, s.ai_api_key, s.ai_model
    s.ai_provider = "openai_compat"
    s.ai_api_key = "sk-test"
    s.ai_model = ""
    with pytest.raises(ValueError, match="LF_AI_MODEL"):
        s.validate_ai_provider()
    s.ai_provider, s.ai_api_key, s.ai_model = saved


def test_deepseek_alias_removed():
    from app.config import settings as s

    saved = s.ai_provider, s.ai_api_key, s.ai_model
    s.ai_provider = "deepseek"
    s.ai_api_key = "sk-test"
    s.ai_model = "deepseek-v4-flash"
    with pytest.raises(ValueError, match="LF_AI_PROVIDER"):
        s.validate_ai_provider()
    s.ai_provider, s.ai_api_key, s.ai_model = saved


def test_opencode_go_factory_smoke(monkeypatch):
    from app.factory import _resolve_provider

    monkeypatch.setattr("app.config.settings.ai_provider", "opencode_go")
    monkeypatch.setattr("app.config.settings.ai_api_key", "sk-test-key")
    monkeypatch.setattr("app.config.settings.ai_model", "deepseek-v4-flash")
    monkeypatch.setattr("app.config.settings.ai_base_url", "")

    provider = _resolve_provider("opencode_go")
    assert provider.provider_name == "opencode_go"
    assert provider.model == "deepseek-v4-flash"
    assert provider.cost_class == CostClass.PAID
    assert provider.endpoint_url == "https://opencode.ai/zen/go/v1/chat/completions"


def test_no_api_key_mock_startup(monkeypatch):
    from app.factory import create_app
    monkeypatch.setattr("app.config.settings.ai_provider", "mock")
    monkeypatch.setattr("app.config.settings.ai_api_key", "")
    app = create_app(db_path="/tmp/lf_no_key_test.db", enable_web=False)
    assert app.state.provider.provider_name == "mock"


# ── URL validation tests ─────────────────────────────────────────────────


def test_validate_base_url_ok():
    from app.ai.openai_compat import validate_base_url
    result = validate_base_url("https://opencode.ai/zen/go/v1")
    assert result == "https://opencode.ai/zen/go/v1"


def test_validate_base_url_ok_deepseek():
    from app.ai.openai_compat import validate_base_url
    result = validate_base_url("https://api.deepseek.com")
    assert "https://api.deepseek.com/v1" in result


def test_validate_base_url_ok_with_v1():
    from app.ai.openai_compat import validate_base_url
    result = validate_base_url("https://opencode.ai/zen/go/v1")
    assert result == "https://opencode.ai/zen/go/v1"


def test_validate_base_url_ok_with_full_path():
    from app.ai.openai_compat import validate_base_url
    result = validate_base_url("https://opencode.ai/zen/go/v1/chat/completions")
    assert "opencode.ai" in result


def test_malformed_url():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises((ValueError, Exception)):
        validate_base_url("not-a-url")


def test_http_url_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="HTTPS"):
        validate_base_url("http://api.deepseek.com")


def test_embedded_url_credentials():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="credentials"):
        validate_base_url("https://user:pass@api.deepseek.com")


def test_loopback_url_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://127.0.0.1:8000")


def test_localhost_url_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://localhost:8000")


def test_private_url_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://192.168.1.1")


def test_link_local_url_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://169.254.1.1")


def test_query_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="query"):
        validate_base_url("https://api.deepseek.com/v1?foo=bar")


def test_fragment_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="fragment"):
        validate_base_url("https://api.deepseek.com/v1#section")


def test_invalid_port_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError):
        validate_base_url("https://api.deepseek.com:notaport")


def test_ipv6_loopback_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://[::1]:8080")


def test_ipv4_mapped_ipv6_loopback_rejection():
    from app.ai.openai_compat import validate_base_url
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://[::ffff:127.0.0.1]")


def test_hostname_resolving_to_loopback_rejection(monkeypatch):
    from app.ai.openai_compat import validate_base_url
    import socket as _socket

    original_getaddrinfo = _socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "evil.example":
            return [(original_getaddrinfo("127.0.0.1", *args, **kwargs)[0])]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://evil.example/v1")


def test_hostname_resolving_to_link_local_rejection(monkeypatch):
    from app.ai.openai_compat import validate_base_url
    import socket as _socket

    original_getaddrinfo = _socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "evil2.example":
            return [(original_getaddrinfo("169.254.1.1", *args, **kwargs)[0])]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://evil2.example/v1")


def test_hostname_resolving_to_mixed_ips_rejection(monkeypatch):
    from app.ai.openai_compat import validate_base_url
    import socket as _socket

    original_getaddrinfo = _socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "evil3.example":
            public = original_getaddrinfo("8.8.8.8", *args, **kwargs)[0]
            private = original_getaddrinfo("10.0.0.1", *args, **kwargs)[0]
            return [public, private]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="not allowed"):
        validate_base_url("https://evil3.example/v1")


def test_opencode_go_canonical_endpoint_exact_match():
    from app.ai.openai_compat import validate_base_url
    result = validate_base_url("https://opencode.ai/zen/go/v1")
    assert result == "https://opencode.ai/zen/go/v1"


def test_endpoint_no_duplicate_v1():
    from app.ai.openai_compat import _build_endpoint_url
    url = _build_endpoint_url("https://opencode.ai/zen/go/v1")
    assert url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert url.count("v1") == 1


def test_endpoint_opencode_go_full_path():
    from app.ai.openai_compat import validate_base_url, _build_endpoint_url
    validated = validate_base_url("https://opencode.ai/zen/go/v1/chat/completions")
    url = _build_endpoint_url(validated)
    assert url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert url.count("chat/completions") == 1


def test_endpoint_no_duplicate_chat_completions():
    from app.ai.openai_compat import _build_endpoint_url
    url = _build_endpoint_url("https://opencode.ai/zen/go/v1/chat/completions")
    assert url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert url.count("chat/completions") == 1


def test_endpoint_from_base_no_slash():
    from app.ai.openai_compat import _build_endpoint_url
    url = _build_endpoint_url("https://opencode.ai/zen/go/v1")
    assert url.count("v1") == 1
    assert url.count("chat/completions") == 1


# ── provider constructor tests ───────────────────────────────────────────


def test_requires_api_key():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with pytest.raises(ValueError, match="LF_AI_API_KEY"):
        OpenAICompatibleProvider(api_key="", model="test-model", base_url="https://opencode.ai/zen/go/v1")


def test_default_attributes():
    from app.ai.openai_compat import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(
        api_key="sk-test-key", model="deepseek-v4-flash",
        base_url="https://opencode.ai/zen/go/v1",
    )
    assert provider.provider_name == "openai_compat"
    assert provider.model == "deepseek-v4-flash"
    assert provider.cost_class == CostClass.PAID
    assert provider.endpoint_url == "https://opencode.ai/zen/go/v1/chat/completions"


def test_custom_provider_name():
    from app.ai.openai_compat import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(
        api_key="sk-test-key", model="deepseek-v4-flash",
        provider_name="opencode_go",
        base_url="https://opencode.ai/zen/go/v1",
    )
    assert provider.provider_name == "opencode_go"
    assert provider.model == "deepseek-v4-flash"


def test_opencode_go_default_url():
    from app.ai.openai_compat import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(
        api_key="sk-test-key", model="deepseek-v4-flash",
        provider_name="opencode_go",
        base_url="https://opencode.ai/zen/go/v1",
    )
    assert provider.endpoint_url == "https://opencode.ai/zen/go/v1/chat/completions"


# ── helper response builders ─────────────────────────────────────────────


def _mock_response(
    payload: dict, *, model="test-model",
    prompt_tokens=50, completion_tokens=100, total_tokens=150,
    finish_reason="stop",
):
    class _MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1700000000,
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(payload)},
                    "finish_reason": finish_reason,
                }],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            }
    return _MockResponse()


def _mock_error_response(status_code=401):
    class _MockResponse:
        def __init__(self):
            self.status_code = status_code
            self.headers = {}
        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError(
                f"Error {status_code}", request=ANY, response=self,
            )
        def json(self):
            return {"error": {"message": "error"}}
    return _MockResponse()


def _mock_text_response(content_text: str):
    """Response with arbitrary text content (not JSON)."""
    class _MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "test-model",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content_text},
                    "finish_reason": "stop",
                }],
                "usage": {},
            }
    return _MockResponse()


def _mock_no_choices_response():
    class _MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "usage": {},
            }
    return _MockResponse()


def _mock_empty_choices_response():
    class _MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [],
                "usage": {},
            }
    return _MockResponse()


def _mock_list_response():
    """Response where data is a list instead of dict."""
    class _MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return ["not", "a", "dict"]
    return _MockResponse()


def _mock_choice_not_dict_response():
    """Response where choices[0] is not a dict."""
    class _MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": ["not a dict"],
                "usage": {},
            }
    return _MockResponse()


# ── success scenarios ────────────────────────────────────────────────────


def test_successful_generation():
    from app.ai.openai_compat import OpenAICompatibleProvider
    expected = {"value": "hello", "number": 42}
    with patch("httpx.post", return_value=_mock_response(expected)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="deepseek-v4-flash", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="You are a helpful assistant.",
            user_payload={"input": "test"}, response_schema=_TestResponse,
            request_id="r1",
        )
    assert result.success is True
    assert result.provider == "openai_compat"
    assert result.advertised_model == "deepseek-v4-flash"
    assert result.payload == expected
    assert result.usage.input_tokens == 50
    assert result.usage.output_tokens == 100
    assert result.finish_reason == "stop"


def test_successful_generation_custom_base_url(monkeypatch):
    from app.ai.openai_compat import OpenAICompatibleProvider
    import socket as _socket

    original_getaddrinfo = _socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "custom.api.com":
            return [(original_getaddrinfo("8.8.8.8", *args, **kwargs)[0])]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    expected = {"value": "custom", "number": 1}
    with patch("httpx.post", return_value=_mock_response(expected)) as mp:
        provider = OpenAICompatibleProvider(
            api_key="sk-test", model="custom-model",
            base_url="https://custom.api.com",
        )
        provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r2",
        )
    url = mp.call_args[0][0]
    assert url == "https://custom.api.com/v1/chat/completions"


def test_successful_generation_opencode_go():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_response({"value": "x", "number": 7})):
        provider = OpenAICompatibleProvider(
            api_key="sk-test", model="deepseek-v4-flash", provider_name="opencode_go",
            base_url="https://opencode.ai/zen/go/v1",
        )
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r3",
        )
    assert result.provider == "opencode_go"
    assert result.advertised_model == "deepseek-v4-flash"


def test_successful_generation_finish_reason_none():
    from app.ai.openai_compat import OpenAICompatibleProvider
    resp = _mock_response({"value": "x", "number": 1}, finish_reason=None)
    with patch("httpx.post", return_value=resp):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r3b",
        )
    assert result.success is True
    assert result.finish_reason is None


# ── structured JSON instruction tests ────────────────────────────────────


def test_json_instruction_in_request():
    """Verify the request body includes response_format=json_object."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_response({"value": "x", "number": 1})) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        provider.generate_structured(
            task_name="t", system_prompt="Respond in JSON.", user_payload={},
            response_schema=_TestResponse, request_id="r20",
        )
    body = mp.call_args[1]["json"]
    assert body["response_format"] == {"type": "json_object"}


def test_json_instruction_in_system_prompt():
    """Verify the system prompt includes JSON instruction and schema."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_response({"value": "x", "number": 1})) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r20a",
        )
    body = mp.call_args[1]["json"]
    messages = body["messages"]
    system_content = messages[0]["content"]
    assert "JSON" in system_content
    assert "json_schema" in system_content or "JSON Schema" in system_content
    assert "value" in system_content
    assert "number" in system_content


def test_json_instruction_with_empty_system_prompt():
    """JSON instruction must be present even with empty system_prompt."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_response({"value": "x", "number": 1})) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r20b",
        )
    body = mp.call_args[1]["json"]
    system_content = body["messages"][0]["content"]
    assert "Return exactly one valid JSON object" in system_content
    assert "Do not use Markdown" in system_content


def test_private_payload_not_in_request_body():
    """Private user payload should not appear in error messages."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_response({"value": "x", "number": 1})) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        provider.generate_structured(
            task_name="t", system_prompt="", user_payload={"secret": "my-secret-data"},
            response_schema=_TestResponse, request_id="r20c",
        )
    body = mp.call_args[1]["json"]
    user_content = body["messages"][1]["content"]
    assert "my-secret-data" in user_content


# ── error scenarios ──────────────────────────────────────────────────────


def test_invalid_json_response():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_text_response("not valid json {{{{")):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r4",
        )
    assert result.success is False
    assert result.error_category == ProviderErrorCategory.INVALID_JSON


def test_schema_mismatch_response():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_response({"value": "ok", "number": "bad"})):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r5",
        )
    assert result.success is False
    assert result.error_category == ProviderErrorCategory.SCHEMA_MISMATCH


def test_empty_content():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_text_response("")):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r6",
        )
    assert result.success is False
    assert result.error_category == ProviderErrorCategory.INVALID_JSON


def test_whitespace_content():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_text_response("   \n  \t  ")):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r7",
        )
    assert result.success is False
    assert result.error_category == ProviderErrorCategory.INVALID_JSON


def test_finish_reason_length():
    from app.ai.openai_compat import OpenAICompatibleProvider
    resp = _mock_response({"value": "x", "number": 1}, finish_reason="length")
    with patch("httpx.post", return_value=resp):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r8",
        )
    assert result.success is False
    assert "length" in (result.error_message or "")
    assert result.finish_reason == "length"


def test_missing_choices():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_no_choices_response()):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r9",
        )
    assert result.success is False
    assert "choices" in (result.error_message or "")


def test_empty_choices():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_empty_choices_response()):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r10",
        )
    assert result.success is False
    assert "choices" in (result.error_message or "")


def test_missing_usage():
    from app.ai.openai_compat import OpenAICompatibleProvider
    resp = _mock_response({"value": "x", "number": 1}, prompt_tokens=None, completion_tokens=None, total_tokens=None)
    with patch("httpx.post", return_value=resp):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r11",
        )
    assert result.success is True
    assert result.usage.input_tokens is None


def test_http_401_no_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(401)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r12",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_http_402_no_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(402)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r13",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_http_403_no_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(403)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r13a",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_http_404_no_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(404)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r13b",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_http_422_no_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(422)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r14",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_http_429_retry_after():
    from app.ai.openai_compat import OpenAICompatibleProvider
    resp1 = _mock_error_response(429)
    resp1.headers = {"Retry-After": "0"}
    resp2 = _mock_response({"value": "ok", "number": 1})
    responses = iter([resp1, resp2])
    with patch("httpx.post", side_effect=lambda *a, **kw: next(responses)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=2, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r15",
        )
    assert result.success is True
    assert result.retry_count == 1


def test_http_429_retry_after_http_date():
    from app.ai.openai_compat import OpenAICompatibleProvider
    from datetime import datetime, timezone, timedelta

    resp1 = _mock_error_response(429)
    future = datetime.now(timezone.utc) + timedelta(seconds=0)
    resp1.headers = {"Retry-After": future.strftime("%a, %d %b %Y %H:%M:%S GMT")}
    resp2 = _mock_response({"value": "ok", "number": 1})
    responses = iter([resp1, resp2])
    with patch("httpx.post", side_effect=lambda *a, **kw: next(responses)) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=2, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r15a",
        )
    assert result.success is True
    assert result.retry_count == 1


def test_http_500_bounded_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(500)):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=2, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r16",
        )
    assert result.success is False
    assert result.retry_count == 2


def test_http_503_bounded_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(503)):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=1, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r17",
        )
    assert result.success is False
    assert result.retry_count == 1


def test_http_504_bounded_retry():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(504)):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=1, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r17a",
        )
    assert result.success is False
    assert result.retry_count == 1


def test_timeout_error():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", side_effect=TimeoutError("timed out")):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", timeout_seconds=0.001, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r18",
        )
    assert result.success is False
    assert result.error_category in (
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.UNKNOWN,
    )


def test_all_retries_exhausted():
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(502)):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=1, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r19",
        )
    assert result.success is False
    assert result.retry_count == 1


# ── no-retry on parsing/shape errors ────────────────────────────────────


def test_invalid_json_body_no_retry():
    """Response body that is invalid JSON should not retry."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_text_response("not valid json {{{{")) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r22",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_response_is_list_no_retry():
    """Response data that is a list instead of dict should not retry."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_list_response()) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r23",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_choice_not_dict_no_retry():
    """Response where choices[0] is not a dict should not retry."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_choice_not_dict_response()) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r24",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_schema_mismatch_no_retry():
    """Schema mismatch should not retry."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_response({"value": "ok", "number": "bad"})) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r25",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_unexpected_exception_no_retry():
    """Unexpected RuntimeError should not retry."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", side_effect=RuntimeError("unexpected")) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=3, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r26",
        )
    assert result.success is False
    assert mp.call_count == 1


def test_transport_error_retry():
    """httpx.TransportError should retry."""
    import httpx
    from app.ai.openai_compat import OpenAICompatibleProvider
    resp2 = _mock_response({"value": "ok", "number": 1})
    responses = iter([httpx.ConnectError("connection refused"), resp2])

    def _side_effect(*a, **kw):
        item = next(responses)
        if isinstance(item, BaseException):
            raise item
        return item

    with patch("httpx.post", side_effect=_side_effect) as mp:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model", max_retries=2, base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r27",
        )
    assert result.success is True
    assert result.retry_count == 1


# ── secret safety ────────────────────────────────────────────────────────


def test_secret_not_in_error():
    """Verify error messages never contain the Authorization header value."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with patch("httpx.post", return_value=_mock_error_response(401)):
        provider = OpenAICompatibleProvider(api_key="sk-super-secret-value", model="test-model", base_url="https://opencode.ai/zen/go/v1")
        result = provider.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_TestResponse, request_id="r21",
        )
    assert result.error_message is not None
    assert "sk-super-secret-value" not in result.error_message
    assert "Authorization" not in (result.error_message or "")


# ── fail-closed: generic openai_compat requires explicit URL ────────────


def test_openai_compat_missing_base_url_fails_closed():
    """openai_compat with empty base URL must fail closed."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with pytest.raises(ValueError, match="base_url"):
        OpenAICompatibleProvider(
            api_key="sk-test", model="test-model",
            base_url="",
        )


def test_openai_compat_whitespace_base_url_fails_closed():
    """openai_compat with whitespace-only base URL must fail closed."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with pytest.raises(ValueError, match="base_url"):
        OpenAICompatibleProvider(
            api_key="sk-test", model="test-model",
            base_url="   ",
        )


def test_constructor_missing_base_url_fails():
    """Constructor without base_url must fail."""
    from app.ai.openai_compat import OpenAICompatibleProvider
    with pytest.raises(TypeError):
        OpenAICompatibleProvider(
            api_key="sk-test", model="test-model",
        )


def test_openai_compat_never_falls_back_to_opencode_go():
    """openai_compat must not silently use OpenCode Go when URL is missing."""
    from app.config import settings as s
    from app.factory import _resolve_provider

    saved = s.ai_provider, s.ai_api_key, s.ai_model, s.ai_base_url
    s.ai_provider = "openai_compat"
    s.ai_api_key = "sk-test"
    s.ai_model = "test-model"
    s.ai_base_url = ""
    with pytest.raises(ValueError, match="LF_AI_BASE_URL"):
        s.validate_ai_provider()
    s.ai_provider, s.ai_api_key, s.ai_model, s.ai_base_url = saved


def test_openai_compat_explicit_public_url_succeeds(monkeypatch):
    """openai_compat with explicit public URL succeeds."""
    import socket as _socket
    from app.ai.openai_compat import OpenAICompatibleProvider

    original_getaddrinfo = _socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "public.example.com":
            return [(original_getaddrinfo("8.8.8.8", *args, **kwargs)[0])]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    provider = OpenAICompatibleProvider(
        api_key="sk-test", model="test-model",
        base_url="https://public.example.com/v1",
    )
    assert provider.endpoint_url == "https://public.example.com/v1/chat/completions"


def test_opencode_go_without_base_url_setting_succeeds(monkeypatch):
    """opencode_go works without LF_AI_BASE_URL."""
    from app.config import settings as s
    from app.factory import _resolve_provider

    saved = s.ai_provider, s.ai_api_key, s.ai_model, s.ai_base_url
    s.ai_provider = "opencode_go"
    s.ai_api_key = "sk-test"
    s.ai_model = "deepseek-v4-flash"
    s.ai_base_url = ""
    s.validate_ai_provider()
    provider = _resolve_provider("opencode_go")
    assert provider.provider_name == "opencode_go"
    assert provider.endpoint_url == "https://opencode.ai/zen/go/v1/chat/completions"
    s.ai_provider, s.ai_api_key, s.ai_model, s.ai_base_url = saved


def test_opencode_go_supplied_base_url_cannot_redirect(monkeypatch):
    """opencode_go ignores LF_AI_BASE_URL and uses canonical endpoint."""
    from app.config import settings as s
    from app.factory import _resolve_provider

    saved = s.ai_provider, s.ai_api_key, s.ai_model, s.ai_base_url
    s.ai_provider = "opencode_go"
    s.ai_api_key = "sk-test"
    s.ai_model = "deepseek-v4-flash"
    s.ai_base_url = "https://evil.example.com/v1"
    s.validate_ai_provider()
    provider = _resolve_provider("opencode_go")
    assert provider.endpoint_url == "https://opencode.ai/zen/go/v1/chat/completions"
    s.ai_provider, s.ai_api_key, s.ai_model, s.ai_base_url = saved


def test_mock_unaffected_by_base_url_validation():
    """Mock provider remains unaffected by base URL validation."""
    from app.config import settings as s
    from app.ai.mock import MockProvider

    saved = s.ai_provider, s.ai_api_key, s.ai_base_url
    s.ai_provider = "mock"
    s.ai_api_key = ""
    s.ai_base_url = ""
    s.validate_ai_provider()
    p = MockProvider()
    assert p.provider_name == "mock"
    s.ai_provider, s.ai_api_key, s.ai_base_url = saved
