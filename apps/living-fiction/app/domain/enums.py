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
    IDEMPOTENCY_WAIT_TIMEOUT = "idempotency_wait_timeout"
    PLAN_VALIDATION_FAILED = "plan_validation_failed"
    CONTENT_VALIDATION_FAILED = "content_validation_failed"
    MATERIAL_CHANGE_VALIDATION_FAILED = "material_change_validation_failed"
    CONTINUITY_VALIDATION_FAILED = "continuity_validation_failed"
    BRANCH_BINDING_FAILED = "branch_binding_failed"
    BRANCH_PERSISTENCE_FAILED = "branch_persistence_failed"
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
    CANON_DELIVERY = "canon_delivery"
    EXPLICIT_CHOICE = "explicit_choice"
    BRANCH_DELIVERY = "branch_delivery"
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
