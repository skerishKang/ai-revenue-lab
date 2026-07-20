from enum import StrEnum


class Language(StrEnum):
    KO = "ko"
    EN = "en"


class SourceTier(StrEnum):
    """Allowed synthetic provenance tiers (see BENCHMARK_SPEC.md section 5)."""

    PRIMARY_OFFICIAL = "primary_official"
    VERIFIED_OFFICIAL_SOCIAL = "verified_official_social"
    REPUTABLE_SECONDARY = "reputable_secondary"


class SourceState(StrEnum):
    """Verification state of a source card / canonical event.

    Exactly the five states required by Issue #36. ``withdrawn`` and
    ``superseded`` cards must never be selected.
    """

    SINGLE_SOURCE = "single_source"
    MULTI_SOURCE = "multi_source"
    CONFLICTING = "conflicting"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class BriefStatus(StrEnum):
    """Every generated brief stays in review; no automatic publication."""

    PENDING_REVIEW = "pending_review"


class BriefSequence(StrEnum):
    FIRST = "first"
    SECOND = "second"


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


class FeedbackAction(StrEnum):
    """Structured, privacy-safe feedback levers.

    The Issue sample calls for increasing culture/neighborhood coverage and
    reducing promotional entertainment.
    """

    INCREASE_CULTURE_NEIGHBORHOOD = "increase_culture_neighborhood"
    REDUCE_PROMOTIONAL_ENTERTAINMENT = "reduce_promotional_entertainment"
    MORE_PRACTICAL = "more_practical"
    SHORTER = "shorter"
    LONGER = "longer"


class Category(StrEnum):
    """Low-risk content families (BENCHMARK_SPEC.md section 3)."""

    PLACE_CULTURE = "place_culture"
    OFFICIAL_EVENT = "official_event"
    NEIGHBORHOOD = "neighborhood"
    PROMOTIONAL_ENTERTAINMENT = "promotional_entertainment"
    OTHER = "other"


class GenerationTaskType(StrEnum):
    GENERATE_FIRST_MICROBRIEF = "generate_first_microbrief"
    GENERATE_SECOND_MICROBRIEF = "generate_second_microbrief"


class PilotEvidenceType(StrEnum):
    """Privacy-safe pilot signals. No personal data is stored."""

    FOLLOWED_COUNTRY = "followed_country"
    REQUESTED_CONTINUED_EDITIONS = "requested_continued_editions"
    CLICKED_OFFICIAL_LINK = "clicked_official_link"
    WHITE_LABEL_INTEREST = "white_label_interest"
    PROMOTED_LISTING_INTEREST = "promoted_listing_interest"
