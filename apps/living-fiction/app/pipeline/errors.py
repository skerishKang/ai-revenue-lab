"""Pipeline error types and validation-status constants.

Error messages are short, category-oriented strings suitable for durable
generation-run records. They never carry raw reader input, token material,
or full generated content.
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


_RETRYABLE_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.PROVIDER_ERROR,
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.INVALID_JSON,
        ProviderErrorCategory.SCHEMA_MISMATCH,
    }
)


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
    """Return a sanitized, category-oriented error message."""
    if category is not None and category in _CATEGORY_MESSAGES:
        return f"{category.value}: {_CATEGORY_MESSAGES[category]}"
    return "unknown: unexpected provider error"
