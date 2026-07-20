from unittest.mock import patch

import pytest
from pydantic import BaseModel

from app.ai.mock import MockProvider
from app.domain.enums import ProviderErrorCategory
from app.domain.models import BriefContent, BriefItem


class _Schema(BaseModel):
    name: str


_BRIEF = {
    "brief_title": "t",
    "deck": "d",
    "items": [
        BriefItem(
            event_id="e1", headline="h", explanation="x", source_ids=["s"]
        ).model_dump()
    ],
}


class TestMockProvider:
    def test_valid_payload(self):
        p = MockProvider(fixture_payload={"name": "x"})
        r = p.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="r1",
        )
        assert r.success is True
        assert r.provider == "mock"
        assert r.advertised_model == "mock-world-feed-v1"
        assert r.payload == {"name": "x"}

    def test_provider_error(self):
        p = MockProvider()
        r = p.generate_structured(
            task_name="error", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="r2",
        )
        assert r.success is False
        assert r.error_category == ProviderErrorCategory.PROVIDER_ERROR

    def test_schema_mismatch(self):
        p = MockProvider()
        r = p.generate_structured(
            task_name="invalid_payload", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="r3",
        )
        assert r.success is False
        assert r.error_category == ProviderErrorCategory.SCHEMA_MISMATCH

    def test_task_payloads_override(self):
        p = MockProvider(task_payloads={"gen": _BRIEF})
        r = p.generate_structured(
            task_name="gen", system_prompt="", user_payload={},
            response_schema=BriefContent, request_id="r4",
        )
        assert r.success is True
        assert r.payload["brief_title"] == "t"

    def test_scripted_responses_consumed_in_order(self):
        p = MockProvider(
            responses=[
                {"kind": "error", "category": ProviderErrorCategory.PROVIDER_ERROR},
                {"kind": "payload", "payload": {"name": "ok"}},
            ]
        )
        first = p.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="r5",
        )
        second = p.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="r6",
        )
        assert first.success is False
        assert second.success is True
        assert second.payload == {"name": "ok"}

    def test_no_network_socket(self):
        with patch("socket.create_connection") as sock:
            sock.side_effect = RuntimeError("network prevented")
            p = MockProvider(fixture_payload={"name": "net"})
            r = p.generate_structured(
                task_name="t", system_prompt="", user_payload={},
                response_schema=_Schema, request_id="r7",
            )
            assert r.success is True
            sock.assert_not_called()

    def test_request_recording_isolated(self):
        p = MockProvider(fixture_payload={"name": "x"})
        p.generate_structured(
            task_name="a", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="ra",
        )
        p.generate_structured(
            task_name="b", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="rb",
        )
        assert [q["task_name"] for q in p.requests] == ["a", "b"]
        snapshot = p.requests
        snapshot.append({"x": 1})
        assert len(p.requests) == 2

    def test_usage_aggregation_from_scripted(self):
        p = MockProvider(
            responses=[
                {
                    "kind": "payload",
                    "payload": {"name": "ok"},
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                }
            ]
        )
        r = p.generate_structured(
            task_name="t", system_prompt="", user_payload={},
            response_schema=_Schema, request_id="r8",
        )
        assert r.usage.input_tokens == 10
        assert r.usage.output_tokens == 5
        assert r.usage.total_tokens == 15
