"""Tests for extended error normalization with new ProviderErrorCategory values.

Verifies that the error taxonomy correctly classifies and messages new
error categories: CONNECTION_ERROR, RATE_LIMIT, REFUSAL.
"""

import pytest

from app.domain.enums import ProviderErrorCategory
from app.pipeline.errors import (
    is_retryable,
    safe_error_message,
)


class TestNewErrorCategoriesRetryable:
    def test_connection_error_is_retryable(self):
        assert is_retryable(ProviderErrorCategory.CONNECTION_ERROR) is True

    def test_rate_limit_is_retryable(self):
        assert is_retryable(ProviderErrorCategory.RATE_LIMIT) is True

    def test_refusal_not_retryable(self):
        assert is_retryable(ProviderErrorCategory.REFUSAL) is False


class TestExistingCategoriesStillRetryable:
    def test_provider_error_still_retryable(self):
        assert is_retryable(ProviderErrorCategory.PROVIDER_ERROR) is True

    def test_timeout_still_retryable(self):
        assert is_retryable(ProviderErrorCategory.TIMEOUT) is True

    def test_invalid_json_still_retryable(self):
        assert is_retryable(ProviderErrorCategory.INVALID_JSON) is True

    def test_schema_mismatch_still_retryable(self):
        assert is_retryable(ProviderErrorCategory.SCHEMA_MISMATCH) is True

    def test_unknown_not_retryable(self):
        assert is_retryable(ProviderErrorCategory.UNKNOWN) is False

    def test_none_not_retryable(self):
        assert is_retryable(None) is False


class TestNewCategoryMessages:
    def test_connection_error_message(self):
        msg = safe_error_message(ProviderErrorCategory.CONNECTION_ERROR, None)
        assert "connection" in msg.lower()
        assert "provider" in msg.lower()

    def test_rate_limit_message(self):
        msg = safe_error_message(ProviderErrorCategory.RATE_LIMIT, None)
        assert "rate" in msg.lower()

    def test_refusal_message(self):
        msg = safe_error_message(ProviderErrorCategory.REFUSAL, None)
        assert "refused" in msg.lower()

    def test_no_raw_material_in_messages(self):
        for cat in ProviderErrorCategory:
            msg = safe_error_message(cat, "sensitive data here")
            assert "sensitive" not in msg
            assert "data here" not in msg


class TestAllCategoriesCovered:
    def test_every_category_has_message(self):
        for cat in ProviderErrorCategory:
            msg = safe_error_message(cat, None)
            assert msg
            assert isinstance(msg, str)

    def test_unknown_fallback(self):
        msg = safe_error_message(ProviderErrorCategory.UNKNOWN, None)
        assert "unexpected" in msg.lower()
