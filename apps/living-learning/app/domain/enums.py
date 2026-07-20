"""Domain enums for Living Learning."""

from enum import StrEnum


class LearnerActivity(StrEnum):
    active = "active"
    paused = "paused"
    completed = "completed"


class LessonGenerationStatus(StrEnum):
    input_received = "input_received"
    generation_pending = "generation_pending"
    pending_review = "pending_review"
    generation_failed = "generation_failed"


class LessonPublicationState(StrEnum):
    pending = "pending"
    published = "published"
    closed = "closed"


class MasteryLevel(StrEnum):
    unknown = "unknown"
    beginning = "beginning"
    developing = "developing"
    proficient = "proficient"


class FeedbackAppliesTo(StrEnum):
    first_lesson = "first_lesson"
    second_lesson = "second_lesson"
    not_applicable = "not_applicable"


class FeedbackAppliedStatus(StrEnum):
    not_applied = "not_applied"
    applied_to_first = "applied_to_first"
    applied_to_second = "applied_to_second"


class ProviderErrorCategory(StrEnum):
    timeout = "timeout"
    invalid_json = "invalid_json"
    schema_mismatch = "schema_mismatch"
    provider_error = "provider_error"
    unknown = "unknown"


class CostClass(StrEnum):
    free = "free"
    paid = "paid"
    local = "local"
    unknown = "unknown"


class PilotEvidenceType(StrEnum):
    free_sample = "free_sample"
    pilot_complete = "pilot_complete"


class ConceptPrerequisiteError(StrEnum):
    missing_prerequisite = "missing_prerequisite"
    skipped_prerequisite = "skipped_prerequisite"


class FeedbackIdempotencyError(StrEnum):
    already_applied = "already_applied"
    foreign_learner = "foreign_learner"
    already_processed = "already_processed"


class RetryExhausted(StrEnum):
    max_retries = "max_retries"
    timeout = "timeout"