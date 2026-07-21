"""Pipeline error types and validation-status constants.

Error messages are short, category-oriented strings suitable for durable
generation-run records. They never carry raw reader input, token material,
or full generated content.

Updated retry matrix:
- Retryable: TIMEOUT, PROVIDER_ERROR (connection_reset, rate_limit, transient)
- Non-retryable: INVALID_JSON, SCHEMA_MISMATCH, UNKNOWN
"""

from __future__ import annotations

from app.domain.enums import ProviderErrorCategory


class PipelineError(RuntimeError):
    """Base class for all deterministic pipeline failures."""


class PlanValidationError(PipelineError):
    """Raised when an episode plan fails deterministic validation."""


class ContentValidationError(PipelineError):
    """Raised when episode content fails deterministic validation."""


class ContinuityError(ContentValidationError):
    """Raised when continuity rules are violated."""


class ProhibitedContentError(ContentValidationError):
    """Raised when prohibited identifiers or content are detected."""


class UnsafeMarkupError(ContentValidationError):
    """Raised when raw HTML, scripts, or unsafe URLs are detected."""


class ProviderCallError(PipelineError):
    """Normalized wrapper around a provider failure."""

    def __init__(
        self,
        *,
        category: ProviderErrorCategory,
        message: str,
        retryable: bool,
    ) -> None:
        self.category = category
        self.retryable = retryable
        self.message = message
        super().__init__(message)


class PrivacyViolationError(PipelineError):
    """Raised when sensitive data is detected in export-safe records."""


class MaterialChangeError(ContentValidationError):
    """Raised when a branch does not materially apply reader input."""


class BranchBindingError(PipelineError):
    """Raised when persisted branch binding validation fails."""


class RejoinValidationError(PipelineError):
    """Raised when rejoin validation fails."""


# Updated retry matrix (Section 7 contract):
# Retryable: TIMEOUT, transient PROVIDER_ERROR only.
# Non-retryable: SCHEMA_MISMATCH, INVALID_JSON, UNKNOWN, auth, programming errors.
_RETRYABLE_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.PROVIDER_ERROR,
        ProviderErrorCategory.TIMEOUT,
    }
)

# Exception retry matrix: which exception types are retryable
# Unknown/programming exceptions are NEVER retried
_RETRYABLE_EXCEPTION_TYPES = frozenset({
    "TimeoutError",
    "ConnectionResetError",
    "ConnectionError",
    "ConnectionAbortedError",
})


def is_exception_retryable(exc: BaseException) -> bool:
    """Determine if an exception should be retried.

    Only timeout and connection-reset exceptions are retryable.
    Programming errors, auth errors, and unknown exceptions are NOT retried.
    """
    exc_type = type(exc).__name__
    if exc_type in _RETRYABLE_EXCEPTION_TYPES:
        return True
    # ConnectionError subclasses (ConnectionRefusedError, etc.) are NOT retryable
    if isinstance(exc, ConnectionError):
        return type(exc).__name__ == "ConnectionResetError"
    return False


def is_retryable(category: ProviderErrorCategory | None) -> bool:
    return category in _RETRYABLE_CATEGORIES


_CATEGORY_MESSAGES = {
    ProviderErrorCategory.PROVIDER_ERROR: "provider returned an error",
    ProviderErrorCategory.TIMEOUT: "provider request timed out",
    ProviderErrorCategory.INVALID_JSON: "provider returned invalid JSON",
    ProviderErrorCategory.SCHEMA_MISMATCH: "provider response did not match the expected schema",
    ProviderErrorCategory.UNKNOWN: "unexpected provider error",
}


def safe_error_message(category: ProviderErrorCategory | None, raw: str | None) -> str:
    """Return a sanitized, category-oriented error message.

    NEVER embeds raw exception string, generated content, or private data.
    Always returns a static, bounded, privacy-safe string.
    """
    if category is not None and category in _CATEGORY_MESSAGES:
        return f"{category.value}: {_CATEGORY_MESSAGES[category]}"
    return "unknown: unexpected provider error"
