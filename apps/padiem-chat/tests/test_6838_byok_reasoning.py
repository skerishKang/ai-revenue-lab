"""#6838: BYOK is the exception; the customer's reasoning choice travels unchanged."""
from __future__ import annotations

import pytest

from app.byok_client import CustomProviderError, _request_body
from app.request_contract import BrowserRequestError, parse_custom_selection
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


# --- the request contract carries the customer's choice (#6828 후속) ---

def test_the_selection_parser_accepts_the_customers_reasoning_choice():
    selection = parse_custom_selection(
        {"provider": "fixture", "model": "fixture-model", "reasoning_effort": "low"},
    )
    assert selection.reasoning_effort == "low"


def test_the_selection_parser_defaults_to_no_reasoning():
    assert parse_custom_selection(
        {"provider": "fixture", "model": "fixture-model"},
    ).reasoning_effort is None
    assert parse_custom_selection(
        {"provider": "fixture", "model": "fixture-model", "reasoning_effort": None},
    ).reasoning_effort is None


def test_the_selection_parser_refuses_unknown_reasoning_values():
    with pytest.raises(BrowserRequestError) as caught:
        parse_custom_selection(
            {"provider": "fixture", "model": "fixture-model", "reasoning_effort": "maximum"},
        )
    assert "추론 강도" in str(caught.value)
