"""Unit tests for OpenAI-compatible provider.

All tests are network-free — an injectable stub transport replaces the real
HTTP client so no socket is ever opened.
"""

from __future__ import annotations

import json
import urllib.request

import pytest
from pydantic import BaseModel, Field

from app.ai.openai_compatible import OpenAICompatibleProvider
from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import EditorialPlan, ProviderResult, EditionContent


# ---------------------------------------------------------------------------
# Stub transport helpers
# ---------------------------------------------------------------------------


class _StubTransport:
    """Inject a fake HTTP transport so tests never touch the network."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, bytes, dict[str, str]]] = []

    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        self.requests.append((url, data, headers))
        return self._handler(url, data, headers, timeout)


def _ok(payload: dict) -> _StubTransport:
    """Return a stub that always responds 200 with the given payload."""
    t = _StubTransport()
    response = {
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 100},
    }
    t._handler = lambda *a: (200, json.dumps(response).encode("utf-8"))
    return t


def _envelope(status: int = 200, body: dict | None = None) -> _StubTransport:
    """Return a stub with a custom response envelope."""
    t = _StubTransport()
    data = json.dumps(body or {}).encode("utf-8") if body else b"{}"
    t._handler = lambda *a: (status, data)
    return t


def _raw(status: int, text: str) -> _StubTransport:
    t = _StubTransport()
    t._handler = lambda *a: (status, text.encode("utf-8"))
    return t


# ---------------------------------------------------------------------------
# Shared provider factory
# ---------------------------------------------------------------------------

_DEFAULT_PROVIDER_KWARGS = {
    "base_url": "https://api.openai.com/v1/chat/completions",
    "api_key": "sk-test-placeholder",
    "model": "gpt-4o-mini",
    "timeout_seconds": 30,
    "cost_class": CostClass.free,
}


def _provider(transport: _StubTransport, **overrides: object) -> OpenAICompatibleProvider:
    kwargs = dict(_DEFAULT_PROVIDER_KWARGS)
    kwargs["transport"] = transport
    kwargs.update(overrides)
    return OpenAICompatibleProvider(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_implements_ai_provider_protocol(self):
        from app.ai.base import AIProvider

        t = _ok({"central_theme": "test", "sections": []})
        provider = _provider(t)
        assert isinstance(provider, AIProvider)

    def test_generate_structured_signature_matches(self):
        t = _ok({"central_theme": "test", "sections": []})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="test system",
            user_payload={"key": "value"},
            response_schema=EditorialPlan,
            request_id="test-req-001",
        )
        assert isinstance(result, ProviderResult)
        url, data, headers = t.requests[0]
        assert "chat/completions" in url
        assert "sk-test-placeholder" in headers["Authorization"]
        body = json.loads(data)
        assert body["model"] == "gpt-4o-mini"
        assert body["temperature"] == 0
        assert body["response_format"]["type"] == "json_object"

    def test_request_id_is_correlation_only(self):
        t = _ok({"central_theme": "test", "sections": []})
        provider = _provider(t)
        provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="corr-001",
        )
        url, data, headers = t.requests[0]
        body = json.loads(data)
        # request_id must not appear in the API request body
        assert "request_id" not in body
        assert "corr-001" not in body

    def test_one_outbound_attempt_only(self):
        t = _ok({"central_theme": "test", "sections": []})
        provider = _provider(t)
        provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-001",
        )
        assert len(t.requests) == 1


class TestSuccessfulGeneration:
    def test_valid_editorial_plan(self):
        plan = {
            "plan_version": "1.0",
            "language": "ko",
            "central_theme": "busan",
            "sections": [
                {"section_id": "sec_intro", "title": "intro", "description": "test"}
            ],
        }
        t = _ok(plan)
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="plan",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-002",
        )
        assert result.success is True
        assert result.provider == "openai_compatible"
        assert result.model == "gpt-4o-mini"
        assert result.cost_class == CostClass.free
        assert isinstance(result.latency_ms, float)
        assert result.latency_ms > 0
        assert result.prompt_tokens == 50
        assert result.completion_tokens == 100
        assert result.payload is not None
        assert result.payload["central_theme"] == "busan"

    def test_valid_edition_draft(self):
        draft = {
            "content_version": "1.0",
            "publication_title": "test",
            "edition_title": "first",
            "destination": "busan",
            "trip_frame": "3night 4days",
            "editorial_opening": "test opening",
            "sections": [],
        }
        t = _ok(draft)
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="edition_draft",
            system_prompt="draft",
            user_payload={},
            response_schema=EditionContent,
            request_id="req-003",
        )
        assert result.success is True
        assert result.payload["destination"] == "busan"

    def test_usage_metadata_populated(self):
        t = _StubTransport()
        payload = {"central_theme": "x", "sections": []}
        response = {
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        t._handler = lambda *a: (200, json.dumps(response).encode("utf-8"))
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-004",
        )
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20

    def test_usage_metadata_missing_handled(self):
        t = _StubTransport()
        payload = {"central_theme": "x", "sections": []}
        response = {"choices": [{"message": {"content": json.dumps(payload)}}]}
        t._handler = lambda *a: (200, json.dumps(response).encode("utf-8"))
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-005",
        )
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0


class TestErrorMapping:
    def test_timeout_maps_correctly(self):
        t = _StubTransport()
        def _raise(_u, _d, _h, _t):
            raise TimeoutError("connection timed out")
        t._handler = _raise
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-006",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.timeout
        assert result.provider == "openai_compatible"

    def test_invalid_json_response(self):
        t = _raw(200, "not-json{{{")
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-007",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.invalid_json

    def test_malformed_envelope_missing_choices(self):
        t = _envelope(200, {"choices": None})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-008",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.invalid_json

    def test_empty_choices(self):
        t = _envelope(200, {"choices": []})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-009",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.invalid_json

    def test_missing_content(self):
        t = _envelope(200, {"choices": [{"message": {}}]})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-010",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.invalid_json

    def test_http_401(self):
        t = _raw(401, '{"error": "unauthorized"}')
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-011",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.provider_error
        assert "401" in result.error_message

    def test_http_429(self):
        t = _raw(429, '{"error": "rate limited"}')
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-012",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.provider_error

    def test_http_500(self):
        t = _raw(500, "Internal Server Error")
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-013",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.provider_error

    def test_schema_mismatch(self):
        t = _ok({"not_a_valid_plan": True})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-014",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.schema_mismatch


class TestStrictJsonHandling:
    def test_fenced_json_rejected(self):
        content = '```json\n{"central_theme": "test", "sections": []}\n```'
        response = {
            "choices": [{"message": {"content": content}}],
            "usage": {},
        }
        t = _raw(200, json.dumps(response))
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-015",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.invalid_json

    def test_prose_wrapped_json_rejected_as_invalid(self):
        content = 'Here is a plan: {"central_theme": "test", "sections": []}'
        response = {
            "choices": [{"message": {"content": content}}],
            "usage": {},
        }
        t = _raw(200, json.dumps(response))
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-016",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.invalid_json

    def test_array_instead_of_object_rejected(self):
        response = {
            "choices": [{"message": {"content": "[1, 2, 3]"}}],
            "usage": {},
        }
        t = _raw(200, json.dumps(response))
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-017",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.schema_mismatch


class TestSecurity:
    def test_api_key_not_in_error_message(self):
        t = _raw(401, '{"error": "unauthorized"}')
        provider = _provider(t, api_key="super-secret-key-1234567890")
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-018",
        )
        msg = str(result.error_message)
        assert "super-secret-key" not in msg

    def test_response_body_not_in_error_message(self):
        t = _raw(500, "SENSITIVE_INTERNAL_ERROR_DETAILS_12345")
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-019",
        )
        assert "SENSITIVE_INTERNAL" not in str(result.error_message)

    def test_authorization_header_not_in_loggable_result(self):
        t = _raw(401, "unauth")
        provider = _provider(t, api_key="sk-ultra-secret-key-99999")
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-020",
        )
        assert "sk-ultra-secret" not in str(result.error_message)
        assert "Bearer" not in str(result.error_message)

    def test_unsupported_task_rejected(self):
        t = _ok({"central_theme": "test", "sections": []})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="unsupported_task",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-021",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.unknown


class TestCostClassAndLatency:
    def test_cost_class_free(self):
        t = _ok({"central_theme": "x", "sections": []})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-c1",
        )
        assert result.cost_class == CostClass.free

    def test_cost_class_paid(self):
        t = _ok({"central_theme": "x", "sections": []})
        provider = _provider(t, cost_class=CostClass.paid)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-c2",
        )
        assert result.cost_class == CostClass.paid

    def test_latency_ms_positive_on_success(self):
        t = _ok({"central_theme": "x", "sections": []})
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-l1",
        )
        assert result.latency_ms > 0

    def test_latency_ms_positive_on_failure(self):
        t = _raw(500, "error")
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-l2",
        )
        assert result.latency_ms > 0


class TestNetworkIsolation:
    def test_stub_transport_no_network(self):
        """Ensure the stub transport never opens a real socket."""
        t = _ok({"central_theme": "x", "sections": []})
        assert t.requests == []
        provider = _provider(t)
        provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-n1",
        )
        assert len(t.requests) == 1
        assert all(isinstance(x, tuple) for x in t.requests)


class TestRedirectBlocking:
    def test_301_redirect_blocked(self):
        t = _StubTransport()
        t._handler = lambda *a: (301, b"")
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-r1",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.provider_error
        assert "301" in result.error_message

    def test_302_redirect_blocked(self):
        t = _StubTransport()
        t._handler = lambda *a: (302, b"")
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-r2",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.provider_error

    def test_307_redirect_blocked(self):
        t = _StubTransport()
        t._handler = lambda *a: (307, b"")
        provider = _provider(t)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-r3",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.provider_error


class TestSSRFValidation:
    def test_127_0_0_1_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://127.0.0.1:11434/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_127_0_0_2_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://127.0.0.2/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_10_0_0_1_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://10.0.0.1/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_172_17_0_1_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://172.17.0.1/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_172_31_255_255_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://172.31.255.255/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_169_254_1_1_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://169.254.1.1/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_0_0_0_0_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://0.0.0.0/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_loopback_ipv6_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://[::1]/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_127_0_0_2_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://127.0.0.2/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_10_0_0_1_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://10.0.0.1/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_172_17_0_1_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://172.17.0.1/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_172_31_255_255_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://172.31.255.255/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_169_254_1_1_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://169.254.1.1/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_0_0_0_0_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://0.0.0.0/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_loopback_ipv6_blocked_in_staging(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="staging")
        with pytest.raises(ProviderTransportError, match="not a global address"):
            transport.request(
                "https://[::1]/v1/chat/completions",
                b"{}", {}, 5.0
            )

    def test_development_http_localhost_allowed(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="development", allow_http_for_localhost=True)
        # localhost resolving should not raise SSRF error
        # We're testing the SSRF check, not actual connection
        try:
            transport._validate_destination("localhost")
        except ProviderTransportError as e:
            if "SSRF" in str(e) or "not a global" in str(e):
                pytest.fail("localhost should be allowed in development")

    def test_development_127_0_0_1_ip_allowed(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="development", allow_http_for_localhost=True)
        try:
            transport._validate_destination("127.0.0.1")
        except ProviderTransportError as e:
            if "SSRF" in str(e) or "not a global" in str(e):
                pytest.fail("127.0.0.1 should be allowed in development")

    def test_development_non_localhost_private_blocked(self):
        from app.ai.openai_compatible import UrllibTransport, ProviderTransportError

        transport = UrllibTransport(environment="development", allow_http_for_localhost=True)
        with pytest.raises(ProviderTransportError, match="SSRF blocked"):
            transport._validate_destination("10.0.0.1")


class TestResponseSizeLimit:
    def test_urllib_transport_enforces_size_limit(self):
        """Test that UrllibTransport rejects responses exceeding size limit."""
        from app.ai.openai_compatible import (
            UrllibTransport,
            ProviderResponseTooLargeError,
        )
        from unittest.mock import patch, MagicMock

        class _FakeResolver:
            def resolve(self, hostname: str) -> list[str]:
                return ["8.8.8.8"]

        transport = UrllibTransport(
            environment="staging",
            max_response_size=100,
            resolver=_FakeResolver(),
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"x" * 200  # 200 bytes, limit is 100

        with patch("urllib.request.build_opener") as mock_opener_builder:
            mock_opener = MagicMock()
            mock_opener.open.return_value.__enter__.return_value = mock_response
            mock_opener_builder.return_value = mock_opener

            with pytest.raises(ProviderResponseTooLargeError):
                transport.request("https://example.com", b"{}", {}, 5.0)

    def test_urllib_transport_accepts_within_limit(self):
        """Test that UrllibTransport accepts responses within size limit."""
        from app.ai.openai_compatible import UrllibTransport
        from unittest.mock import patch, MagicMock

        class _FakeResolver:
            def resolve(self, hostname: str) -> list[str]:
                return ["8.8.8.8"]

        transport = UrllibTransport(
            environment="staging",
            max_response_size=1000,
            resolver=_FakeResolver(),
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"OK" + b"x" * 100

        with patch("urllib.request.build_opener") as mock_opener_builder:
            mock_opener = MagicMock()
            mock_opener.open.return_value.__enter__.return_value = mock_response
            mock_opener_builder.return_value = mock_opener

            status, body = transport.request("https://example.com", b"{}", {}, 5.0)
            assert status == 200


class TestEndpointNormalization:
    def test_base_url_with_v1_appended_correctly(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com/v1",
            ai_api_key="sk-test",
            ai_model="gpt-4o-mini",
        )
        url = s.ai_chat_completions_url
        assert url == "https://api.openai.com/v1/chat/completions"

    def test_base_url_without_v1_has_v1_appended(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test",
            ai_model="gpt-4o-mini",
        )
        url = s.ai_chat_completions_url
        assert url == "https://api.openai.com/v1/chat/completions"

    def test_base_url_with_existing_v1_path_no_double_v1(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com/v1",
            ai_api_key="sk-test",
            ai_model="gpt-4o-mini",
        )
        url = s.ai_chat_completions_url
        assert url.count("/v1") == 1
        assert "/chat/completions" in url


class TestCorrelationId:
    def test_correlation_id_is_opaque(self):
        from app.ai.openai_compatible import _make_correlation_id

        opaque_id = _make_correlation_id("traveler-123_edition-456_plan-789")
        assert opaque_id != "traveler-123_edition-456_plan-789"
        assert len(opaque_id) == 32
        assert opaque_id.isalnum()

    def test_correlation_id_consistent_for_same_input(self):
        from app.ai.openai_compatible import _make_correlation_id

        id1 = _make_correlation_id("request-xyz")
        id2 = _make_correlation_id("request-xyz")
        assert id1 == id2
