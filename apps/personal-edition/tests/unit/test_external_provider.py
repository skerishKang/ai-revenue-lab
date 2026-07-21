"""Unit tests for the ExternalProvider adapter.

All tests use mocked urllib to avoid any real network calls. Credentials
are never asserted to be present in any output.
"""

import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from app.ai.external import ExternalProvider, _normalize_endpoint
from app.domain.enums import ProviderErrorCategory


class DummySchema(BaseModel):
    name: str
    value: int = 0


def _make_provider(**kwargs):
    defaults = dict(
        base_url="https://api.example.com/v1",
        api_key="test-key-12345",
        model="test-model",
        timeout_seconds=30,
    )
    defaults.update(kwargs)
    return ExternalProvider(**defaults)


class TestNormalizeEndpoint:
    def test_adds_chat_completions(self):
        assert _normalize_endpoint("https://api.example.com/v1") == \
            "https://api.example.com/v1/chat/completions"

    def test_strips_trailing_slash(self):
        assert _normalize_endpoint("https://api.example.com/v1/") == \
            "https://api.example.com/v1/chat/completions"

    def test_preserves_full_path(self):
        url = "https://api.example.com/v1/chat/completions"
        assert _normalize_endpoint(url) == url

    def test_strips_double_slash(self):
        assert _normalize_endpoint("https://api.example.com/v1//") == \
            "https://api.example.com/v1/chat/completions"


class TestExternalProviderInit:
    def test_valid_init(self):
        p = _make_provider()
        assert p.provider == "external"
        assert p.model == "test-model"

    def test_empty_base_url_raises(self):
        with pytest.raises(ValueError, match="base_url"):
            ExternalProvider(base_url="", api_key="k", model="m")

    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="api_key"):
            ExternalProvider(base_url="https://x.com", api_key="", model="m")

    def test_empty_model_raises(self):
        with pytest.raises(ValueError, match="model"):
            ExternalProvider(base_url="https://x.com", api_key="k", model="")

    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            ExternalProvider(base_url="https://x.com", api_key="k", model="m",
                             timeout_seconds=0)


class TestExternalProviderSuccess:
    def test_successful_response(self):
        provider = _make_provider()
        response_body = json.dumps({
            "choices": [{
                "message": {
                    "content": json.dumps({"name": "test", "value": 42})
                }
            }],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = provider.generate_structured(
                task_name="test_task",
                system_prompt="Be helpful.",
                user_payload={"input": "hello"},
                response_schema=DummySchema,
                request_id="req-001",
            )

        assert result.success is True
        assert result.provider == "external"
        assert result.advertised_model == "test-model"
        assert result.payload == {"name": "test", "value": 42}
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50
        assert result.usage.total_tokens == 150
        assert result.latency_seconds >= 0

    def test_successful_response_no_usage(self):
        provider = _make_provider()
        response_body = json.dumps({
            "choices": [{
                "message": {
                    "content": json.dumps({"name": "test"})
                }
            }],
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="test_task",
                system_prompt="",
                user_payload={},
                response_schema=DummySchema,
                request_id="req-002",
            )

        assert result.success is True
        assert result.usage.input_tokens is None


class TestExternalProviderErrors:
    def test_http_429_rate_limit(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=429, msg="Too Many Requests",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b""))
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r1",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.RATE_LIMIT

    def test_http_401_auth_failure(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=401, msg="Unauthorized",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b""))
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r2",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.AUTH_FAILURE

    def test_http_403_auth_failure(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=403, msg="Forbidden",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b""))
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r3",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.AUTH_FAILURE

    def test_http_500_server_error(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=500, msg="Server Error",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b""))
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r4",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_http_400_generic(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=400, msg="Bad Request",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b""))
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r5",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_socket_timeout(self):
        provider = _make_provider()
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r6",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.TIMEOUT

    def test_os_error_connection(self):
        provider = _make_provider()
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r7",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.CONNECTION_ERROR

    def test_url_error_with_os_error_reason(self):
        provider = _make_provider()
        url_exc = urllib.error.URLError(OSError("Name or service not known"))
        with patch("urllib.request.urlopen", side_effect=url_exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r8",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.CONNECTION_ERROR

    def test_url_error_with_timeout_reason(self):
        provider = _make_provider()
        url_exc = urllib.error.URLError(socket.timeout("timed out"))
        with patch("urllib.request.urlopen", side_effect=url_exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r9",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.TIMEOUT

    def test_invalid_json_response(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r10",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.INVALID_JSON

    def test_empty_choices_response(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"choices": []}).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r11",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_content_not_json(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "not json"}}]
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r12",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.INVALID_JSON

    def test_schema_mismatch(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"wrong": "schema"})}}]
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r13",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_MISMATCH


class TestExternalProviderPrivacy:
    def test_api_key_not_in_request_body(self):
        provider = _make_provider(api_key="secret-key-abc123")
        captured_requests = []

        def capture_request(req, **kwargs):
            body = req.data.decode("utf-8")
            captured_requests.append(body)
            raise urllib.error.URLError("blocked")

        with patch("urllib.request.urlopen", side_effect=capture_request):
            provider.generate_structured(
                task_name="t", system_prompt="sys", user_payload={"k": "v"},
                response_schema=DummySchema, request_id="r-priv",
            )

        assert len(captured_requests) == 1
        assert "secret-key-abc123" not in captured_requests[0]

    def test_api_key_not_in_exception_message(self):
        provider = _make_provider(api_key="secret-key-xyz")
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=500, msg="Server Error",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b""))
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-priv2",
            )
        assert "secret-key-xyz" not in (result.error_message or "")
        assert "secret-key-xyz" not in str(result)

    def test_no_network_in_success_path(self):
        provider = _make_provider()
        response_body = json.dumps({
            "choices": [{"message": {"content": json.dumps({"name": "ok"})}}]
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-net",
            )
            assert result.success is True

        call_args = mock_open.call_args
        req = call_args[0][0]
        auth_header = req.get_header("Authorization")
        assert auth_header == "Bearer test-key-12345"
