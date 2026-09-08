"""#2094: upstream failure codes must map to specific safe copy, not the generic fallthrough.

Before the repair, core codes ``upstream_auth_error``, ``upstream_request_error``
and ``upstream_server_error`` fell through to the generic 502
"답변을 불러오지 못했습니다." copy, hiding provider/config failures behind a
plain "연결 오류" badge.
"""

from __future__ import annotations

import pytest

from app.b14_client import ChatRuntimeError, _chat_error

GENERIC_MESSAGE = "답변을 불러오지 못했습니다. 다시 시도해 주세요."
FORBIDDEN_INTERNALS = (
    "kilo",
    "minimax",
    "nemotron",
    "poolside",
    "laguna",
    "http",
    "token",
    "key",
    "provider_secret",
    "api.",
)


def test_upstream_auth_error_maps_to_specific_safe_code_and_copy():
    error = _chat_error("upstream_auth_error")
    assert isinstance(error, ChatRuntimeError)
    assert error.status_code == 502
    assert error.code == "provider_auth_error"
    assert error.user_message != GENERIC_MESSAGE
    assert "인증" in error.user_message


def test_upstream_request_error_maps_to_specific_safe_code_and_copy():
    error = _chat_error("upstream_request_error")
    assert isinstance(error, ChatRuntimeError)
    assert error.status_code == 502
    assert error.code == "provider_route_error"
    assert error.user_message != GENERIC_MESSAGE
    assert "모델" in error.user_message


def test_upstream_server_error_maps_to_specific_safe_code_and_copy():
    error = _chat_error("upstream_server_error")
    assert isinstance(error, ChatRuntimeError)
    assert error.status_code == 502
    assert error.code == "provider_server_error"
    assert error.user_message != GENERIC_MESSAGE
    assert "오류" in error.user_message


def test_upstream_timeout_copy_stays_distinct_and_retryable_framed():
    error = _chat_error("upstream_timeout")
    assert error.status_code == 504
    assert error.code == "upstream_timeout"
    assert error.user_message != GENERIC_MESSAGE


@pytest.mark.parametrize(
    "code",
    (
        "upstream_auth_error",
        "upstream_request_error",
        "upstream_server_error",
        "upstream_timeout",
        "unknown_future_code",
    ),
)
def test_no_mapping_leaks_provider_internals_or_raw_details(code: str):
    message = _chat_error(code).user_message.lower()
    for forbidden in FORBIDDEN_INTERNALS:
        assert forbidden not in message


def test_unknown_codes_still_fall_through_to_generic_safe_copy():
    error = _chat_error("some_unseen_code")
    assert error.status_code == 502
    assert error.code == "upstream_error"
    assert error.user_message == GENERIC_MESSAGE
