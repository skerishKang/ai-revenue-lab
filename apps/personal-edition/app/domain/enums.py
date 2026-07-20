from enum import StrEnum


class Language(StrEnum):
    KO = "ko"
    EN = "en"


class FeedbackDirection(StrEnum):
    CONTINUE_DIRECTION = "continue_direction"
    MORE_PRACTICAL = "more_practical"
    MORE_REFLECTIVE = "more_reflective"
    DEEPER_ON_SECTION = "deeper_on_section"
    REDUCE_TOPIC = "reduce_topic"
    EXCLUDE_TOPIC = "exclude_topic"
    SHORTER = "shorter"
    LONGER = "longer"
    CHANGE_TONE = "change_tone"


class GenerationStatus(StrEnum):
    INPUT_RECEIVED = "input_received"
    GENERATION_PENDING = "generation_pending"
    GENERATION_FAILED = "generation_failed"
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
    RATE_LIMIT = "rate_limit"
    AUTH_FAILURE = "auth_failure"
    REFUSAL = "refusal"
    CONNECTION_ERROR = "connection_error"
