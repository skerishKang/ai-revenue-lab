"""Network-free safety contract for completed Provider envelope diagnostics (#1452)."""

from __future__ import annotations

import json

import pytest

from app.pilot.completed_response_shape import (
    CATEGORY_CHOICES_EMPTY,
    CATEGORY_CHOICES_NOT_LIST,
    CATEGORY_INVALID_JSON,
    CATEGORY_MISSING_CHOICES,
    CATEGORY_NON_OBJECT,
    CATEGORY_NORMAL_CHAT_COMPLETION,
    classify_completed_response_structure,
)
from app.pilot.errors import MalformedUpstreamResponse


@pytest.mark.parametrize(
    ("raw", "category", "decoded_type", "choices_type", "choices_count"),
    [
        (b"not-json", CATEGORY_INVALID_JSON, "unparsed", None, None),
        (b"[]", CATEGORY_NON_OBJECT, "array", None, None),
        (b'"hello"', CATEGORY_NON_OBJECT, "string", None, None),
        (b'{"id":"x"}', CATEGORY_MISSING_CHOICES, "object", None, None),
        (b'{"choices":{}}', CATEGORY_CHOICES_NOT_LIST, "object", "object", None),
        (b'{"choices":[]}', CATEGORY_CHOICES_EMPTY, "object", "array", 0),
        (
            b'{"id":"x","model":"m","choices":[{"message":{"content":"ok"}}]}',
            CATEGORY_NORMAL_CHAT_COMPLETION,
            "object",
            "array",
            1,
        ),
    ],
)
def test_completed_response_shape_categories(
    raw: bytes,
    category: str,
    decoded_type: str,
    choices_type: str | None,
    choices_count: int | None,
) -> None:
    shape = classify_completed_response_structure(raw)

    assert shape.category == category
    assert shape.decoded_type == decoded_type
    assert shape.choices_type == choices_type
    assert shape.choices_count == choices_count


def test_completed_response_shape_diagnostics_are_value_blind_and_allow_listed() -> None:
    raw = json.dumps(
        {
            "id": "provider-secret-looking-id",
            "model": "private-model-value",
            "choices": [{"message": {"content": "private response text"}}],
            "usage": {"prompt_tokens": 99},
            "authorization": "Bearer should-never-appear",
            "prompt": "private prompt",
            "secret_token": "top-secret-value",
        }
    ).encode()

    shape = classify_completed_response_structure(raw)
    fields = shape.safe_log_fields()
    rendered = repr(fields)

    assert shape.category == CATEGORY_NORMAL_CHAT_COMPLETION
    assert shape.safe_top_level_keys == ("choices", "id", "model", "usage")
    assert fields["choices_count"] == 1

    for forbidden in (
        "provider-secret-looking-id",
        "private-model-value",
        "private response text",
        "Bearer should-never-appear",
        "private prompt",
        "top-secret-value",
        "authorization",
        "prompt",
        "secret_token",
    ):
        assert forbidden not in rendered


def test_completed_response_shape_does_not_broaden_current_contract() -> None:
    # Alternate-looking envelopes are diagnosed, not silently normalized.
    shape = classify_completed_response_structure(
        b'{"output":[{"content":"hello"}],"model":"m"}'
    )
    assert shape.category == CATEGORY_MISSING_CHOICES


def test_public_malformed_upstream_error_contract_is_unchanged() -> None:
    error = MalformedUpstreamResponse()

    assert error.code == "malformed_upstream_response"
    assert error.status_code == 502
    assert error.to_dict() == {
        "code": "malformed_upstream_response",
        "message": "Provider 응답 형식이 올바르지 않습니다.",
    }
