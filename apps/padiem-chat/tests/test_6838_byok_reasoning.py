"""#6838: BYOK is the exception; the customer's reasoning choice travels unchanged."""
from __future__ import annotations

import pytest

from app.byok_client import CustomProviderError, _request_body
from app.byok_credentials import CustomProvider


def _spec(wire: str = "openai-chat") -> CustomProvider:
    return CustomProvider(
        provider_id="fixture", display_name="Fixture",
        base_origin="https://example.invalid", wire=wire, auth="bearer",
    )


def test_the_customers_level_is_sent_verbatim():
    body = _request_body(
        _spec(), "fixture-model", [{"role": "user", "content": "hi"}], None, False,
        reasoning_effort="minimal",
    )
    assert body["reasoning_effort"] == "minimal"


def test_no_level_is_sent_when_the_customer_chose_none():
    body = _request_body(
        _spec(), "fixture-model", [{"role": "user", "content": "hi"}], None, False,
    )
    assert "reasoning_effort" not in body


def test_a_wire_without_the_field_refuses_instead_of_dropping_it():
    with pytest.raises(CustomProviderError) as caught:
        _request_body(
            _spec("anthropic-messages"), "fixture-model",
            [{"role": "user", "content": "hi"}], None, False,
            reasoning_effort="high",
        )
    assert caught.value.code == "reasoning_effort_unsupported_wire"
    assert caught.value.status_code == 422
