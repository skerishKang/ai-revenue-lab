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

from app.ai.external import ExternalProvider, _normalize_endpoint, _MAX_ERROR_BODY_BYTES
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


# ---------------------------------------------------------------------------
# Issue #42: structured output / response_format_mode tests
# ---------------------------------------------------------------------------

class TestResponseFormatMode:
    def test_json_schema_mode_includes_actual_schema(self):
        provider = _make_provider(response_format_mode="json_schema")
        captured = []

        def capture(req, **kwargs):
            captured.append(req.data.decode("utf-8"))
            raise urllib.error.URLError("blocked")

        with patch("urllib.request.urlopen", side_effect=capture):
            provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-schema",
            )

        body = json.loads(captured[0])
        rf = body["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "DummySchema"
        assert rf["json_schema"]["strict"] is True
        schema = rf["json_schema"]["schema"]
        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "value" in schema["properties"]

    def test_json_schema_preserves_required_fields(self):
        from enum import Enum

        class Status(str, Enum):
            active = "active"
            inactive = "inactive"

        class NestedSchema(BaseModel):
            id: str
            count: int
            status: Status
            tags: list[str]

        provider = _make_provider(response_format_mode="json_schema")
        captured = []

        def capture(req, **kwargs):
            captured.append(req.data.decode("utf-8"))
            raise urllib.error.URLError("blocked")

        with patch("urllib.request.urlopen", side_effect=capture):
            provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=NestedSchema, request_id="r-nested",
            )

        body = json.loads(captured[0])
        schema = body["response_format"]["json_schema"]["schema"]
        assert "id" in schema.get("required", [])
        assert "count" in schema.get("required", [])
        assert "status" in schema.get("required", [])
        assert "tags" in schema.get("required", [])
        # Pydantic uses $ref for enums; check $defs
        defs = schema.get("$defs", {})
        status_def = defs.get("Status", {})
        assert status_def.get("enum") == ["active", "inactive"]

    def test_json_schema_deterministic_name(self):
        provider = _make_provider(response_format_mode="json_schema")
        names = []
        for i in range(3):
            captured = []
            def capture(req, **kwargs):
                captured.append(req.data.decode("utf-8"))
                raise urllib.error.URLError("blocked")
            with patch("urllib.request.urlopen", side_effect=capture):
                provider.generate_structured(
                    task_name="t", system_prompt="", user_payload={},
                    response_schema=DummySchema, request_id=f"r-{i}",
                )
            body = json.loads(captured[0])
            names.append(body["response_format"]["json_schema"]["name"])
        assert len(set(names)) == 1

    def test_json_object_mode_uses_simple_format(self):
        provider = _make_provider(response_format_mode="json_object")
        captured = []

        def capture(req, **kwargs):
            captured.append(req.data.decode("utf-8"))
            raise urllib.error.URLError("blocked")

        with patch("urllib.request.urlopen", side_effect=capture):
            provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-obj",
            )

        body = json.loads(captured[0])
        assert body["response_format"] == {"type": "json_object"}

    def test_invalid_mode_raises_at_init(self):
        with pytest.raises(ValueError, match="response_format_mode"):
            ExternalProvider(
                base_url="https://x.com", api_key="k", model="m",
                response_format_mode="xml",
            )

    def test_json_schema_no_fallback_to_json_object(self):
        provider = _make_provider(response_format_mode="json_schema")
        captured = []

        def capture(req, **kwargs):
            captured.append(req.data.decode("utf-8"))
            raise urllib.error.URLError("blocked")

        with patch("urllib.request.urlopen", side_effect=capture):
            provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-nofb",
            )

        body = json.loads(captured[0])
        assert body["response_format"]["type"] == "json_schema"
        assert "json_schema" in body["response_format"]

    def test_schema_mismatch_detected_after_valid_json(self):
        provider = _make_provider(response_format_mode="json_schema")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"wrong": "field"})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-sm",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_MISMATCH

    def test_usage_snake_case_parsing(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"name": "ok"})}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-use",
            )
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50
        assert result.usage.total_tokens == 150

    def test_missing_usage_returns_none_fields(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"name": "ok"})}}],
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-nouse",
            )
        assert result.usage.input_tokens is None
        assert result.usage.output_tokens is None
        assert result.usage.total_tokens is None

    def test_negative_usage_treated_as_none(self):
        provider = _make_provider()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"name": "ok"})}}],
            "usage": {"prompt_tokens": -5, "completion_tokens": -1, "total_tokens": 0},
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-neg",
            )
        assert result.usage.input_tokens is None
        assert result.usage.output_tokens is None
        assert result.usage.total_tokens == 0

    def test_raw_body_not_in_error_message(self):
        provider = _make_provider(api_key="super-secret-key")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"raw garbage with super-secret-key embedded"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-raw",
            )
        assert "super-secret-key" not in (result.error_message or "")
        assert "super-secret-key" not in str(result)


# ---------------------------------------------------------------------------
# Issue #42 supplement: silent fallback removal and schema capability errors
# ---------------------------------------------------------------------------

class TestSilentFallbackRemoval:
    def test_json_schema_missing_schema_fails_closed(self):
        provider = _make_provider(response_format_mode="json_schema")
        with pytest.raises(ValueError, match="json_schema mode requires"):
            provider._build_request_body(
                task_name="t", system_prompt="", user_payload={},
                response_schema=None,
            )

    def test_json_schema_missing_schema_no_network_call(self):
        provider = _make_provider(response_format_mode="json_schema")
        mock_open = MagicMock()
        with patch("urllib.request.urlopen", mock_open):
            with pytest.raises(ValueError, match="json_schema mode requires"):
                provider._build_request_body(
                    task_name="t", system_prompt="", user_payload={},
                    response_schema=None,
                )
        mock_open.assert_not_called()

    def test_json_schema_missing_schema_not_json_object(self):
        provider = _make_provider(response_format_mode="json_schema")
        with pytest.raises(ValueError):
            provider._build_request_body(
                task_name="t", system_prompt="", user_payload={},
                response_schema=None,
            )

    def test_json_schema_missing_schema_no_credential_in_error(self):
        provider = _make_provider(
            api_key="super-secret-key",
            response_format_mode="json_schema",
        )
        with pytest.raises(ValueError) as exc_info:
            provider._build_request_body(
                task_name="t", system_prompt="", user_payload={},
                response_schema=None,
            )
        assert "super-secret-key" not in str(exc_info.value)


class TestSchemaCapabilityErrors:
    def _make_400_error(self, body: bytes) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="https://api.example.com", code=400, msg="Bad Request",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=body)),
        )

    def test_response_format_unsupported_code(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {
                "code": "unsupported_response_format",
                "message": "response_format is not supported",
                "type": "invalid_request_error",
            }
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-rfu",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED

    def test_schema_rejected_by_param(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {
                "code": "invalid_request",
                "message": "invalid parameter",
                "type": "invalid_request_error",
                "param": "response_format.json_schema",
            }
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-sr",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_REJECTED

    def test_schema_rejected_by_code(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {
                "code": "schema_validation_failed",
                "message": "schema error",
            }
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-sr2",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_REJECTED

    def test_generic_400_not_schema_rejected(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {
                "code": "invalid_request",
                "message": "missing required field 'messages'",
            }
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-gen400",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_422_not_misclassified_as_schema_rejected(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {
                "code": "invalid_request",
                "message": "field required",
                "param": "messages",
            }
        }).encode()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=422, msg="Unprocessable",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=body)),
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-422",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_raw_body_not_in_error_message(self):
        provider = _make_provider(api_key="secret-key-xyz")
        body = json.dumps({
            "error": {
                "code": "invalid_request",
                "message": "bad request with secret-key-xyz in body",
            }
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-raw-body",
            )
        assert "secret-key-xyz" not in (result.error_message or "")
        assert "bad request with" not in (result.error_message or "")

    def test_free_text_message_not_in_error(self):
        provider = _make_provider()
        body = json.dumps({
            "error": {
                "code": "invalid_request",
                "message": "The model gpt-4 does not exist or you do not have access",
            }
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-free-text",
            )
        assert "gpt-4" not in (result.error_message or "")
        assert "does not exist" not in (result.error_message or "")

    def test_429_still_rate_limit(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=429, msg="Too Many",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b"")),
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-429",
            )
        assert result.error_category == ProviderErrorCategory.RATE_LIMIT

    def test_401_still_auth_failure(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=401, msg="Unauthorized",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b"")),
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-401",
            )
        assert result.error_category == ProviderErrorCategory.AUTH_FAILURE

    def test_403_still_auth_failure(self):
        provider = _make_provider()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=403, msg="Forbidden",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=b"")),
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-403",
            )
        assert result.error_category == ProviderErrorCategory.AUTH_FAILURE

    def test_schema_conforming_response_still_succeeds(self):
        provider = _make_provider(response_format_mode="json_schema")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"name": "test", "value": 42})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-ok",
            )
        assert result.success is True
        assert result.payload == {"name": "test", "value": 42}

    def test_schema_mismatch_still_detected(self):
        provider = _make_provider(response_format_mode="json_schema")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"wrong": "field"})}}],
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-sm2",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_MISMATCH

    def test_unparseable_error_body_returns_provider_error(self):
        provider = _make_provider()
        exc = self._make_400_error(b"not json at all")
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-unp",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR


# ---------------------------------------------------------------------------
# Issue #42 hardening: error body limit, exact allowlist, non-retryable
# ---------------------------------------------------------------------------

class TestErrorBodyLimit:
    def _make_400_error(self, body: bytes) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="https://api.example.com", code=400, msg="Bad Request",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=body)),
        )

    def test_valid_schema_error_within_limit(self):
        from app.ai.external import ExternalProvider
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {
                "code": "unsupported_response_format",
                "message": "format not supported",
            }
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-ok-limit",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED

    def test_exact_max_size_body_parsed(self):
        provider = _make_provider(response_format_mode="json_schema")
        base = json.dumps({
            "error": {"code": "unsupported_response_format", "message": "ok"}
        }).encode()
        assert len(base) < _MAX_ERROR_BODY_BYTES
        exc = self._make_400_error(base)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-max-exact",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED

    def test_oversized_body_not_parsed(self):
        provider = _make_provider()
        body = b'{"error": {"code": "x"}}' + b" " * (_MAX_ERROR_BODY_BYTES + 1)
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-over",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_boundary_size_body_classified(self):
        provider = _make_provider(response_format_mode="json_schema")
        code = "unsupported_response_format"
        msg = "x"
        while len(json.dumps({"error": {"code": code, "message": msg}}).encode()) < _MAX_ERROR_BODY_BYTES:
            msg += "x"
        body = json.dumps({"error": {"code": code, "message": msg}}).encode()
        assert len(body) <= _MAX_ERROR_BODY_BYTES
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-boundary",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED

    def test_read_receives_byte_limit(self):
        provider = _make_provider()
        exc = self._make_400_error(b'{"error": {}}')
        with patch("urllib.request.urlopen", side_effect=exc):
            provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-read-limit",
            )
        exc.fp.read.assert_called_once_with(_MAX_ERROR_BODY_BYTES + 1)

    def test_truncated_json_returns_provider_error(self):
        provider = _make_provider()
        body = b'{"error": {"code": "un'
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-trunc",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_invalid_utf8_returns_provider_error(self):
        provider = _make_provider()
        exc = self._make_400_error(b"\xff\xfe\x00")
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-utf8",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_api_key_in_oversized_body_not_exposed(self):
        provider = _make_provider(api_key="secret-key-abc")
        body = b'{"error": {"msg": "secret-key-abc"}}' + b"x" * (_MAX_ERROR_BODY_BYTES)
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-oversized-key",
            )
        assert "secret-key-abc" not in (result.error_message or "")


class TestExactAllowlistClassification:
    def _make_400_error(self, body: bytes) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="https://api.example.com", code=400, msg="Bad Request",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=body)),
        )

    def test_database_schema_error_not_misclassified(self):
        provider = _make_provider()
        body = json.dumps({
            "error": {"code": "database_schema_error", "message": "db error"}
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-db-schema",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_account_schema_version_error_not_misclassified(self):
        provider = _make_provider()
        body = json.dumps({
            "error": {"code": "account_schema_version_error", "message": "x"}
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-acct-schema",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_exact_unsupported_code_classified(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {"code": "response_format_not_supported", "message": "no"}
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-exact-unsup",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED

    def test_exact_schema_rejected_code(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {"code": "schema_validation_failed", "message": "x"}
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-exact-reject",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_REJECTED

    def test_bracket_param_canonicalized(self):
        provider = _make_provider(response_format_mode="json_schema")
        body = json.dumps({
            "error": {"code": "invalid_request", "param": "response_format[json_schema]"}
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-bracket",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_REJECTED

    def test_generic_400_not_schema_related(self):
        provider = _make_provider()
        body = json.dumps({
            "error": {"code": "invalid_request", "message": "missing field 'messages'"}
        }).encode()
        exc = self._make_400_error(body)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-gen400b",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_422_general_validation_not_schema_rejected(self):
        provider = _make_provider()
        body = json.dumps({
            "error": {"code": "invalid_request", "message": "field required", "param": "messages"}
        }).encode()
        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=422, msg="Unprocessable",
            hdrs=None, fp=MagicMock(read=MagicMock(return_value=body)),
        )
        with patch("urllib.request.urlopen", side_effect=exc):
            result = provider.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=DummySchema, request_id="r-422b",
            )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR


class TestNonRetryableCategories:
    def test_response_format_unsupported_not_retryable(self):
        from app.pipeline.errors import is_retryable
        assert is_retryable(ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED) is False

    def test_schema_rejected_not_retryable(self):
        from app.pipeline.errors import is_retryable
        assert is_retryable(ProviderErrorCategory.SCHEMA_REJECTED) is False

    def test_response_format_unsupported_has_static_message(self):
        from app.pipeline.errors import safe_error_message
        msg = safe_error_message(ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED, None)
        assert "response_format" in msg
        assert len(msg) < 200

    def test_schema_rejected_has_static_message(self):
        from app.pipeline.errors import safe_error_message
        msg = safe_error_message(ProviderErrorCategory.SCHEMA_REJECTED, None)
        assert "schema" in msg
        assert len(msg) < 200

    def test_max_error_body_bytes_value(self):
        assert _MAX_ERROR_BODY_BYTES == 64 * 1024
