"""Normalized pipeline error types and validation-status constants.

These errors are raised by deterministic pipeline stages. They never carry raw
participant input, token material, or full generated content. Messages are
short, category-oriented strings suitable for durable generation-run records.
"""

from app.domain.enums import ProviderErrorCategory


class PipelineError(RuntimeError):
    """Base class for all deterministic pipeline failures."""


class SegmentationError(PipelineError):
    """Raised when normalization or segmentation cannot produce valid segments."""


class PlanValidationError(PipelineError):
    """Raised when an editorial plan fails deterministic validation."""


class DraftValidationError(PipelineError):
    """Raised when an edition draft fails deterministic validation."""


class GroundingError(DraftValidationError):
    """Raised when a draft contains a prohibited invented personal fact."""


class UnsafeMarkupError(DraftValidationError):
    """Raised when a draft contains raw HTML, scripts, or unsafe URLs."""


class ProviderCallError(PipelineError):
    """Normalized wrapper around a provider failure or exception.

    ``category`` is a :class:`ProviderErrorCategory` and ``retryable`` tells the
    service whether a bounded retry is permitted.
    """

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


# validation_status values persisted to generation_runs.validation_status.
VALIDATION_PASSED = "passed"
VALIDATION_FAILED = "validation_failed"
PROVIDER_FAILED = "provider_failed"
NOT_ATTEMPTED = "not_attempted"

_VALIDATION_STATUSES = frozenset(
    {VALIDATION_PASSED, VALIDATION_FAILED, PROVIDER_FAILED, NOT_ATTEMPTED}
)


def is_valid_validation_status(value: str) -> bool:
    return value in _VALIDATION_STATUSES


# Provider outcomes that may be retried within the bounded retry budget.
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


def safe_error_message(category: ProviderErrorCategory | None, raw: str | None) -> str:
    """Return a sanitized, category-oriented error message.

    The raw provider error message may echo fixture or field data. It is
    truncated and prefixed with its category so that no raw private material is
    durably recorded.
    """
    label = category.value if category is not None else "unknown"
    if raw:
        snippet = raw.strip()
        if len(snippet) > 160:
            snippet = snippet[:160] + "..."
        return f"{label}: {snippet}"
    return f"{label}: provider returned no usable structured payload"
