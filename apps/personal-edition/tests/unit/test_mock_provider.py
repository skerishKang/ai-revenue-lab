from unittest.mock import patch

import pytest
from pydantic import BaseModel, ValidationError

from app.ai.mock import MockProvider
from app.domain.enums import ProviderErrorCategory
from app.domain.models import (
    EditionContent,
    EditionSection,
    EditorialPlan,
    EditorialPlanSection,
)


class DummySchema(BaseModel):
    name: str


EDITORIAL_PLAN_FIXTURE = {
    "plan_version": "v1",
    "language": "ko",
    "central_theme": "theme",
    "reader_value": "value",
    "opening_intent": "intro",
    "sections": [
        {
            "section_id": "s1",
            "working_title": "Section 1",
            "purpose": "purpose",
            "source_segment_ids": ["seg1"],
        },
        {
            "section_id": "s2",
            "working_title": "Section 2",
            "purpose": "purpose",
            "source_segment_ids": ["seg2"],
        },
    ],
    "highlighted_insight": "key insight",
}


class TestMockProvider:
    def test_valid_payload_dummy_schema(self):
        provider = MockProvider(fixture_payload={"name": "test-fixture"})
        result = provider.generate_structured(
            task_name="test_task",
            system_prompt="Be helpful.",
            user_payload={"input": "hello"},
            response_schema=DummySchema,
            request_id="req-001",
        )
        assert result.success is True
        assert result.provider == "mock"
        assert result.advertised_model == "mock-personal-edition-v1"
        assert result.payload == {"name": "test-fixture"}

    def test_valid_payload_editorial_plan(self):
        provider = MockProvider(fixture_payload=EDITORIAL_PLAN_FIXTURE)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-plan",
        )
        assert result.success is True
        assert result.payload is not None
        assert result.payload["plan_version"] == "v1"
        assert len(result.payload["sections"]) == 2

    def test_provider_error(self):
        provider = MockProvider()
        result = provider.generate_structured(
            task_name="error",
            system_prompt="",
            user_payload={},
            response_schema=DummySchema,
            request_id="req-002",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.PROVIDER_ERROR
        assert result.error_message == "simulated provider error"

    def test_invalid_payload_fails_validation(self):
        provider = MockProvider()
        result = provider.generate_structured(
            task_name="invalid_payload",
            system_prompt="",
            user_payload={},
            response_schema=DummySchema,
            request_id="req-003",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_MISMATCH
        assert "name" in result.error_message

    def test_no_fixture_with_required_fields_fails(self):
        provider = MockProvider()
        result = provider.generate_structured(
            task_name="no_fixture",
            system_prompt="",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req-004",
        )
        assert result.success is False
        assert result.error_category == ProviderErrorCategory.SCHEMA_MISMATCH

    def test_no_network_monkeypatch(self):
        with patch("socket.create_connection") as mock_socket:
            mock_socket.side_effect = RuntimeError("network call prevented")
            provider = MockProvider(fixture_payload={"name": "net-test"})
            result = provider.generate_structured(
                task_name="test_task",
                system_prompt="",
                user_payload={},
                response_schema=DummySchema,
                request_id="req-net",
            )
            assert result.success is True
            mock_socket.assert_not_called()

    def test_request_recording(self):
        provider = MockProvider(fixture_payload={"name": "rec"})
        provider.generate_structured(
            task_name="task_a",
            system_prompt="",
            user_payload={},
            response_schema=DummySchema,
            request_id="req-010",
        )
        provider.generate_structured(
            task_name="task_b",
            system_prompt="",
            user_payload={},
            response_schema=DummySchema,
            request_id="req-011",
        )
        assert len(provider.requests) == 2
        assert provider.requests[0]["task_name"] == "task_a"
        assert provider.requests[0]["request_id"] == "req-010"
        assert provider.requests[1]["task_name"] == "task_b"
        assert provider.requests[1]["request_id"] == "req-011"

    def test_model_property(self):
        provider = MockProvider(model="custom-v2")
        assert provider.model == "custom-v2"

    def test_requests_isolation(self):
        provider = MockProvider(fixture_payload={"name": "iso"})
        provider.generate_structured(
            task_name="t1",
            system_prompt="",
            user_payload={},
            response_schema=DummySchema,
            request_id="r1",
        )
        reqs = provider.requests
        assert len(reqs) == 1
        reqs.append({"should_not_mutate": True})
        assert len(provider.requests) == 1
