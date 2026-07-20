"""Domain enums for Living Fiction."""

from enum import StrEnum


class EpisodeType(StrEnum):
    CANON = "canon"
    PERSONAL_BRANCH = "personal_branch"


class ReviewState(StrEnum):
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    DELETED = "deleted"


class CostClass(StrEnum):
    FREE = "free"
    PAID = "paid"
    LOCAL = "local"
    UNKNOWN = "unknown"


class ProviderErrorCategory(StrEnum):
    TIMEOUT = "timeout"
    INVALID_JSON = "invalid_json"
    SCHEMA_MISMATCH = "schema_mismatch"
    PROVIDER_ERROR = "provider_error"
    UNKNOWN = "unknown"


class BranchStatus(StrEnum):
    ACTIVE = "active"
    REJOINED = "rejoined"
    ABANDONED = "abandoned"


class ContentClassification(StrEnum):
    ADULT = "adult"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"


class EvidenceCategory(StrEnum):
    INVITATION = "invitation"
    CONSENT = "consent"
    EPISODE_DELIVERY = "episode_delivery"
    EXPLICIT_CHOICE = "explicit_choice"
    ENGAGEMENT = "engagement"
    CORRECTION_TIME = "correction_time"
    AI_INFRA_COST = "ai_infra_cost"
    REVENUE_HYPOTHESIS = "revenue_hypothesis"


class ValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "validation_failed"
    PROVIDER_FAILED = "provider_failed"
    NOT_ATTEMPTED = "not_attempted"


class AttemptResult(StrEnum):
    """Result classification for a single provider attempt."""
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    NON_RETRYABLE_FAILURE = "non_retryable_failure"
    EXCEPTION = "exception"


class BranchRequestStatus(StrEnum):
    """Status of a branch generation request (idempotency tracking)."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class RejoinRequestStatus(StrEnum):
    """Status of a rejoin request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
