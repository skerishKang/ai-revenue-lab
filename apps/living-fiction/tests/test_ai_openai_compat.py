from __future__ import annotations

import json
from unittest.mock import ANY, patch

import pytest
from pydantic import BaseModel, Field

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult, ProviderUsage


# ── helper schema for structured generation tests ────────────────────────


class _TestResponse(BaseModel):
    value: str = Field(min_length=1)
    number: int = Field(ge=0)


# ── constructor validation ────────────────────────────────────────────────


def test_requires_api_key():
    from app.ai.openai_compat import OpenAICompatibleProvider

    with pytest.raises(ValueError, match="LF_AI_API_KEY"):
        OpenAICompatibleProvider(api_key="", model="test-model")


def test_default_attributes():
    from app.ai.openai_compat import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(
        api_key="sk-test-key",
        model="test-model",
    )
    assert provider.provider_name == "openai_compat"
    assert provider.model == "test-model"
    assert provider.cost_class == CostClass.PAID


def test_custom_provider_name():
    from app.ai.openai_compat import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(
        api_key="sk-test-key",
        model="deepseek-chat",
        provider_name="deepseek",
    )
    assert provider.provider_name == "deepseek"
    assert provider.model == "deepseek-chat"


# ── helpers ──────────────────────────────────────────────────────────────


def _mock_response(
    payload: dict,
    *,
    model: str = "test-model",
    prompt_tokens: int | None = 50,
    completion_tokens: int | None = 100,
    total_tokens: int | None = 150,
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
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(payload),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            }

    return _MockResponse()


def _mock_error_response(status_code: int = 401):
    class _MockResponse:
        def __init__(self):
            self.status_code = status_code

        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError(
                f"Error {status_code}",
                request=ANY,
                response=self,
            )

        def json(self):
            return {"error": {"message": "error"}}

    return _MockResponse()


# ── success scenarios ────────────────────────────────────────────────────


def test_successful_generation():
    from app.ai.openai_compat import OpenAICompatibleProvider

    expected_payload = {"value": "hello", "number": 42}
    mock_resp = _mock_response(expected_payload)

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model")
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={"input": "test"},
            response_schema=_TestResponse,
            request_id="req-001",
        )

    assert result.success is True
    assert result.provider == "openai_compat"
    assert result.advertised_model == "test-model"
    assert result.cost_class == CostClass.PAID
    assert result.payload == expected_payload
    assert result.request_id == "req-001"
    assert result.usage.input_tokens == 50
    assert result.usage.output_tokens == 100
    assert result.usage.total_tokens == 150
    assert result.latency_seconds >= 0
    assert result.error_category is None
    assert result.error_message is None

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert "Authorization" in call_kwargs["headers"]
    assert "Bearer " in call_kwargs["headers"]["Authorization"]
    assert call_kwargs["json"]["model"] == "test-model"


def test_successful_generation_with_custom_base_url():
    from app.ai.openai_compat import OpenAICompatibleProvider

    expected_payload = {"value": "custom", "number": 1}
    mock_resp = _mock_response(expected_payload)

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        provider = OpenAICompatibleProvider(
            api_key="sk-test",
            model="custom-model",
            base_url="https://custom.api.com/v1",
        )
        provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-002",
        )

    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert url == "https://custom.api.com/v1/chat/completions"


def test_successful_generation_deepseek_alias():
    from app.ai.openai_compat import OpenAICompatibleProvider

    expected_payload = {"value": "deepseek", "number": 7}
    mock_resp = _mock_response(expected_payload)

    with patch("httpx.post", return_value=mock_resp):
        provider = OpenAICompatibleProvider(
            api_key="sk-test",
            model="deepseek-chat",
            provider_name="deepseek",
        )
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-003",
        )

    assert result.success is True
    assert result.provider == "deepseek"
    assert result.advertised_model == "deepseek-chat"


# ── error scenarios ──────────────────────────────────────────────────────


def test_invalid_json_response():
    from app.ai.openai_compat import OpenAICompatibleProvider

    class _InvalidJsonResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": 'not valid json {{{{',
                        }
                    }
                ],
                "usage": {},
            }

    with patch("httpx.post", return_value=_InvalidJsonResponse()):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model")
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-004",
        )

    assert result.success is False
    assert result.error_category == ProviderErrorCategory.INVALID_JSON
    assert result.request_id == "req-004"


def test_schema_mismatch_response():
    from app.ai.openai_compat import OpenAICompatibleProvider

    mock_resp = _mock_response({"value": "ok", "number": "not_an_integer"})

    with patch("httpx.post", return_value=mock_resp):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model")
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-005",
        )

    assert result.success is False
    assert result.error_category == ProviderErrorCategory.SCHEMA_MISMATCH


def test_http_error_non_retryable():
    from app.ai.openai_compat import OpenAICompatibleProvider

    mock_resp = _mock_error_response(status_code=401)

    with patch("httpx.post", return_value=mock_resp):
        provider = OpenAICompatibleProvider(api_key="sk-test", model="test-model")
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-006",
        )

    assert result.success is False
    assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR
    assert "401" in (result.error_message or "")


def test_retryable_then_success():
    from app.ai.openai_compat import OpenAICompatibleProvider

    error_resp = _mock_error_response(status_code=429)
    expected_payload = {"value": "retried", "number": 99}
    success_resp = _mock_response(expected_payload)
    responses = iter([error_resp, success_resp])

    with patch("httpx.post", side_effect=lambda *a, **kw: next(responses)):
        provider = OpenAICompatibleProvider(
            api_key="sk-test", model="test-model", max_retries=2
        )
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-007",
        )

    assert result.success is True
    assert result.payload == expected_payload
    assert result.retry_count == 1


def test_all_retries_exhausted():
    from app.ai.openai_compat import OpenAICompatibleProvider

    error_resp = _mock_error_response(status_code=502)
    responses = iter([error_resp, error_resp])

    with patch("httpx.post", side_effect=lambda *a, **kw: next(responses)):
        provider = OpenAICompatibleProvider(
            api_key="sk-test", model="test-model", max_retries=1
        )
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-009",
        )

    assert result.success is False
    assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR


def test_timeout_error():
    from app.ai.openai_compat import OpenAICompatibleProvider

    with patch("httpx.post", side_effect=TimeoutError("connection timed out")):
        provider = OpenAICompatibleProvider(
            api_key="sk-test", model="test-model", timeout_seconds=0.001
        )
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="You are a helpful assistant.",
            user_payload={},
            response_schema=_TestResponse,
            request_id="req-008",
        )

    assert result.success is False
    assert result.error_category in (
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.UNKNOWN,
    )
