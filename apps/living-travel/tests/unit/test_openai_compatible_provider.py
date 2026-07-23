"""Unit tests for OpenAI-compatible provider.

All tests are network-free — an injectable stub transport replaces the real
HTTP client so no socket is ever opened.
"""

from __future__ import annotations

import json

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
