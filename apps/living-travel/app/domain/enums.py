"""Domain enums for Living Travel."""

from enum import StrEnum


class TravelerStatus(StrEnum):
    active = "active"
    deleted = "deleted"


class TripContext(StrEnum):
    solo = "solo"
    couple = "couple"
    family = "family"
    group = "group"


class InformationClass(StrEnum):
    inspiration = "inspiration"
    stable_reference = "stable_reference"
    time_sensitive = "time_sensitive"


class EditionGenerationStatus(StrEnum):
    input_received = "input_received"
    generation_pending = "generation_pending"
    pending_review = "pending_review"
    generation_failed = "generation_failed"


class PublicationState(StrEnum):
    pending = "pending"
    published = "published"
    rejected = "rejected"


class SourceConfidence(StrEnum):
    confirmed = "confirmed"
    approximate = "approximate"
    uncertain = "uncertain"
    withdrawn = "withdrawn"


class FeedbackDirection(StrEnum):
    continue_direction = "continue_direction"
    more_local_food = "more_local_food"
    quieter_places = "quieter_places"
    slower_pace = "slower_pace"
    less_walking = "less_walking"
    lower_budget = "lower_budget"
    more_practical = "more_practical"
    reduce_famous = "reduce_famous"
    deeper_on_section = "deeper_on_section"


class CostClass(StrEnum):
    free = "free"
    paid = "paid"
    local = "local"
    unknown = "unknown"


class ProviderErrorCategory(StrEnum):
    timeout = "timeout"
    invalid_json = "invalid_json"
    schema_mismatch = "schema_mismatch"
    provider_error = "provider_error"
    unknown = "unknown"


class PilotEvidenceType(StrEnum):
    free_sample = "free_sample"
    paid_edition = "paid_edition"
