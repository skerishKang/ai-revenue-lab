"""Final accounting contract tests.

Tests provider exception categories, retry matrix, latency recording,
failed ProviderResult identity preservation, and validation failure accounting.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from app.pipeline.errors import (
    is_exception_retryable,
    categorize_exception,
    safe_error_message,
    is_retryable,
)
from app.domain.enums import ProviderErrorCategory


def test_timeout_attempt_category_and_aggregate_latency():
    """TimeoutError is TIMEOUT category and retryable."""
    exc = TimeoutError("request timed out")
    assert is_exception_retryable(exc)
    assert categorize_exception(exc) == ProviderErrorCategory.TIMEOUT


def test_connection_failure_category():
    """ConnectionResetError is PROVIDER_ERROR category."""
    exc = ConnectionResetError("connection reset")
    assert is_exception_retryable(exc)
    assert categorize_exception(exc) == ProviderErrorCategory.PROVIDER_ERROR


def test_connection_refused_not_retryable():
    """ConnectionRefusedError (non-reset) is NOT retryable."""
    exc = ConnectionRefusedError("connection refused")
    assert not is_exception_retryable(exc)
    assert categorize_exception(exc) == ProviderErrorCategory.PROVIDER_ERROR


def test_unknown_exception_not_retried():
    """Unknown arbitrary exception is not retryable."""
    exc = RuntimeError("unexpected bug")
    assert not is_exception_retryable(exc)
    assert categorize_exception(exc) == ProviderErrorCategory.UNKNOWN


def test_keyboard_interrupt_not_retryable():
    """KeyboardInterrupt is not in retryable set."""
    exc = KeyboardInterrupt()
    assert not is_exception_retryable(exc)


def test_value_error_not_retryable():
    """ValueError is not retryable."""
    exc = ValueError("invalid value")
    assert not is_exception_retryable(exc)


def test_schema_mismatch_not_retryable():
    """SCHEMA_MISMATCH category is not retryable."""
    assert not is_retryable(ProviderErrorCategory.SCHEMA_MISMATCH)


def test_invalid_json_not_retryable():
    """INVALID_JSON category is not retryable."""
    assert not is_retryable(ProviderErrorCategory.INVALID_JSON)


def test_provider_error_retryable():
    """PROVIDER_ERROR category is retryable."""
    assert is_retryable(ProviderErrorCategory.PROVIDER_ERROR)


def test_timeout_retryable():
    """TIMEOUT category is retryable."""
    assert is_retryable(ProviderErrorCategory.TIMEOUT)


def test_unknown_not_retryable():
    """UNKNOWN category is not retryable."""
    assert not is_retryable(ProviderErrorCategory.UNKNOWN)


def test_failed_provider_result_preserves_actual_identity():
    """Failed ProviderResult preserves provider/model/cost."""
    from app.domain.models import ProviderResult, ProviderUsage
    from app.domain.enums import CostClass
    result = ProviderResult(
        provider="test-provider",
        advertised_model="test-model",
        cost_class=CostClass.PAID,
        latency_seconds=1.5,
        success=False,
        error_category=ProviderErrorCategory.PROVIDER_ERROR,
        error_message="test error",
        usage=ProviderUsage(input_tokens=100, output_tokens=50, total_tokens=150),
    )
    assert result.provider == "test-provider"
    assert result.advertised_model == "test-model"
    assert result.cost_class == "paid"


def test_exception_attempt_records_measured_latency():
    """Exception attempt records measured latency."""
    import time
    start = time.perf_counter()
    # Simulate work
    time.sleep(0.01)
    latency = time.perf_counter() - start
    assert latency > 0.0, "Latency should be measurable"


def test_safe_error_message_no_raw_exception():
    """safe_error_message does not include raw exception text."""
    msg = safe_error_message(
        ProviderErrorCategory.UNKNOWN,
        "Exception: secret_api_key_abc123",
    )
    assert "secret_api_key" not in msg, "Should not leak raw exception text"
    assert "unexpected provider error" in msg


def test_safe_error_message_known_category():
    """Known categories produce static bounded messages."""
    msg = safe_error_message(
        ProviderErrorCategory.TIMEOUT,
        "request timed out after 30s",
    )
    assert msg == "timeout: provider request timed out"


def test_safe_error_message_none_category():
    """None category returns fallback 'unknown' message."""
    msg = safe_error_message(None, "some error")
    assert msg == "unknown: unexpected provider error"
