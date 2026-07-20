from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.domain.enums import (
    Category,
    CostClass,
    FeedbackAction,
    Language,
    PilotEvidenceType,
    ProviderErrorCategory,
    SourceState,
    SourceTier,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

_UTC_ISO_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$"


def _validate_utc_iso(value: str, field_name: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise ValueError(
                f"{field_name} must be UTC ISO-8601 (YYYY-MM-DDTHH:MM:SS[.mmm]Z)"
            ) from exc
    return value


# Unsafe markup is prohibited (BENCHMARK_SPEC.md section 15, Issue #36).
_UNSAFE_MARKUP_RE = (
    r"<script|</script>|<iframe|</iframe|javascript:|onerror=|onload="
    r"|<img|<\?php|<\s*style\s*="
)


def _reject_unsafe_markup(value: str, field_name: str) -> str:
    import re

    if re.search(_UNSAFE_MARKUP_RE, value, flags=re.IGNORECASE):
        raise ValueError(f"{field_name} contains unsafe markup and is rejected")
    return value


class ReaderPreferences(BaseModel):
    """Privacy-safe synthetic reader preferences. No sensitive traits."""

    interests: list[Category] = Field(default_factory=list)
    excluded_categories: list[Category] = Field(default_factory=list)
    desired_coverage: list[Category] = Field(default_factory=list)
    detail_level: str = "standard"
    language: Language = Language.KO


class SourceCard(BaseModel):
    """Accepted synthetic source card.

    Validated at the edge: allowed provenance, well-formed dates, safe markup,
    and an explicit synthetic flag. Rejected problems (unknown provenance,
    malformed dates, duplicate ids, unsafe markup) never reach the store.
    """

    source_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    country: NonEmptyStr
    locality: NonEmptyStr
    original_language: Language
    source_tier: SourceTier
    publisher_name: NonEmptyStr
    organization_type: NonEmptyStr
    canonical_url: NonEmptyStr
    publication_timestamp: str
    access_timestamp: str
    title: str = Field(min_length=1)
    text_extract: str = Field(min_length=1)
    category: Category
    media_rights_state: NonEmptyStr
    source_state: SourceState
    conflict_penalty: float = Field(default=0.0, ge=0.0, le=1.0)
    canonical_key: NonEmptyStr
    checksum: NonEmptyStr
    synthetic_flag: bool = True
    reviewer_notes: str = ""

    @field_validator("publication_timestamp", "access_timestamp")
    @classmethod
    def _check_timestamps(cls, v: str, info) -> str:
        return _validate_utc_iso(v, info.field_name)

    @field_validator("title", "text_extract", "publisher_name", "locality", "country")
    @classmethod
    def _check_markup(cls, v: str, info) -> str:
        return _reject_unsafe_markup(v, info.field_name)

    @field_validator("synthetic_flag")
    @classmethod
    def _require_synthetic(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("only synthetic source cards are accepted")
        return v


class ReaderProfileInput(BaseModel):
    reader_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: NonEmptyStr
    language: Language = Language.KO
    preferences: ReaderPreferences = Field(default_factory=ReaderPreferences)
    active: bool = True


class FeedbackInput(BaseModel):
    """Structured, persisted feedback. Applied exactly once via idempotency."""

    feedback_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    reader_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    prior_brief_id: str | None = None
    idempotency_key: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    action: FeedbackAction
    detail: str = ""


class BriefItem(BaseModel):
    """One cited microbrief item. event_id must belong to the selected set."""

    event_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    headline: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    source_ids: list[NonEmptyStr] = Field(min_length=1)


class BriefContent(BaseModel):
    """Generated Korean microbrief structure (provider output)."""

    brief_title: str = Field(min_length=1)
    deck: str = Field(min_length=1)
    items: list[BriefItem] = Field(min_length=1, max_length=12)
    uncertainty_notes: list[str] = Field(default_factory=list)
    feedback_note: str | None = None

    @model_validator(mode="after")
    def _unique_event_ids(self):
        ids = [i.event_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("brief items must cite each event at most once")
        return self


class PilotEvidenceInput(BaseModel):
    """Privacy-safe pilot evidence. No personal identifiers are stored."""

    reader_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    brief_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    evidence_type: PilotEvidenceType
    anonymous_token: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    detail: str = ""


class ProviderUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderResult(BaseModel):
    provider: str
    advertised_model: str
    cost_class: CostClass = CostClass.FREE
    latency_seconds: float = Field(default=0.0, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    payload: dict | None = None
    request_id: str | None = None
    error_category: ProviderErrorCategory | None = None
    error_message: str | None = None
    success: bool = False
