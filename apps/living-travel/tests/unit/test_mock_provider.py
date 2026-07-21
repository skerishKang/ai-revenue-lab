"""Unit tests for MockProvider."""

import pytest

from app.ai.mock import MockProvider
from app.domain.models import EditorialPlan, EditionContent, ProviderResult


class TestMockProvider:
    def test_fixture_payload(self):
        provider = MockProvider(
            fixture_payload={
                "plan_version": "1.0",
                "language": "ko",
                "central_theme": "부산",
                "sections": [],
            }
        )
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="test",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req1",
        )
        assert result.success is True
        assert result.provider == "mock"
        assert result.model == "mock-fixture"
        assert len(provider.requests) == 1
        assert provider.requests[0]["task_name"] == "editorial_plan"

    def test_task_payloads(self):
        provider = MockProvider(
            task_payloads={
                "editorial_plan": {
                    "plan_version": "1.0",
                    "language": "ko",
                    "central_theme": "테스트",
                    "sections": [],
                }
            }
        )
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="test",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req2",
        )
        assert result.success is True

    def test_error_task(self):
        provider = MockProvider()
        result = provider.generate_structured(
            task_name="error",
            system_prompt="test",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req3",
        )
        assert result.success is False
        assert result.error_category == "provider_error"

    def test_sequential_responses(self):
        provider = MockProvider(
            responses=[
                {
                    "plan_version": "1.0",
                    "language": "ko",
                    "central_theme": "첫 번째",
                    "sections": [],
                },
                {
                    "plan_version": "1.0",
                    "language": "ko",
                    "central_theme": "두 번째",
                    "sections": [],
                },
            ]
        )
        r1 = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="test",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req4",
        )
        r2 = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="test",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="req5",
        )
        assert r1.success is True
        assert r2.success is True
        assert r1.payload["central_theme"] == "첫 번째"
        assert r2.payload["central_theme"] == "두 번째"

    def test_all_requests_recorded(self):
        provider = MockProvider(
            fixture_payload={
                "plan_version": "1.0",
                "language": "ko",
                "central_theme": "x",
                "sections": [],
            }
        )
        for i in range(3):
            provider.generate_structured(
                task_name="editorial_plan",
                system_prompt="test",
                user_payload={"i": i},
                response_schema=EditorialPlan,
                request_id=f"req_{i}",
            )
        assert len(provider.requests) == 3
