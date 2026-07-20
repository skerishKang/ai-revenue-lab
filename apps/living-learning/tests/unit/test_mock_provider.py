"""Unit tests for MockProvider."""

import pytest
from pydantic import BaseModel

from app.ai import MockProvider
from app.domain.models import ProviderResult


class SimplePayload(BaseModel):
    name: str
    value: int


def test_mock_provider_uses_fixture_payload() -> None:
    provider = MockProvider(
        fixture_payload={"name": "test", "value": 42}
    )

    result = provider.generate_structured(
        task_name="test_task",
        system_prompt="You are a test.",
        user_payload={},
        response_schema=SimplePayload,
        request_id="req_1",
    )

    assert result.success is True
    assert result.provider == "mock"
    assert result.model == "mock-fixture"


def test_mock_provider_uses_task_payload() -> None:
    provider = MockProvider(
        task_payloads={"specific_task": {"name": "specific", "value": 99}}
    )

    result = provider.generate_structured(
        task_name="specific_task",
        system_prompt="",
        user_payload={},
        response_schema=SimplePayload,
        request_id="req_2",
    )

    assert result.success is True
    assert result.payload["name"] == "specific"


def test_mock_provider_uses_responses_list() -> None:
    provider = MockProvider(
        responses=[
            {"name": "first", "value": 1},
            {"name": "second", "value": 2},
        ]
    )

    result1 = provider.generate_structured(
        task_name="task",
        system_prompt="",
        user_payload={},
        response_schema=SimplePayload,
        request_id="req_1",
    )

    result2 = provider.generate_structured(
        task_name="task",
        system_prompt="",
        user_payload={},
        response_schema=SimplePayload,
        request_id="req_2",
    )

    assert result1.payload["name"] == "first"
    assert result2.payload["name"] == "second"


def test_mock_provider_error_task() -> None:
    provider = MockProvider()

    result = provider.generate_structured(
        task_name="error",
        system_prompt="",
        user_payload={},
        response_schema=SimplePayload,
        request_id="req_error",
    )

    assert result.success is False
    assert result.error_category == "provider_error"


def test_mock_provider_tracks_requests() -> None:
    provider = MockProvider(
        task_payloads={"task1": {"name": "a", "value": 1}}
    )

    provider.generate_structured(
        task_name="task1",
        system_prompt="prompt1",
        user_payload={"key": "val"},
        response_schema=SimplePayload,
        request_id="req_1",
    )

    assert len(provider.requests) == 1
    assert provider.requests[0]["task_name"] == "task1"
    assert provider.requests[0]["system_prompt"] == "prompt1"