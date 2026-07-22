"""Domain models for Personal Video Archive.

Every model here is a pure Python / Pydantic data structure with no
persistence or I/O coupling.  Validation lives in the model so it can be
tested in isolation and reused by repositories, services, and the fake
providers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    DefaultSort,
    DurationPreference,
    ProposalStatus,
    ProposalType,
    Provenance,
    ShortsPreference,
    SyncStatus,
    ValidationStatus,
    ViewingState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YOUTUBE_URL_RE = re.compile(
    r"^https://(www\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"
    r"(?:\&.*)?$"
)
_YOUTUBE_SHORTS_RE = re.compile(
    r"^https://(www\.)?youtube\.com/shorts/([A-Za-z0-9_-]{11})"
    r"(?:\&.*)?$"
)
# Canonical form: youtu.be/<id> or youtube.com/watch?v=<id>
_CANONICAL_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Tag contract: 1-40 chars, must start with a letter (Unicode-aware),
# then letters/digits/spaces/hyphens/underscores. Rejects empty, control chars,
# HTML/script, and duplicates (checked separately).
_TAG_RE = re.compile(r"^[A-Za-z\uac00-\ud7a3][A-Za-z0-9\uac00-\ud7a3 _-]{0,39}$")

def validate_tags(tags: list[str]) -> list[str]:
    """Validate a list of tags using the shared tag contract.

    Rules:
    - Must start with a letter (Unicode-aware: Latin or Hangul)
    - 1-40 chars: letters, digits, spaces, hyphens, underscores
    - No control characters
    - No HTML/script content
    - No duplicates (case-insensitive)
    - No empty tags
    - No comma-only values

    Returns the validated tag list. Raises ValueError on invalid input.
    """
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError(f"Tag must be a string, got {type(tag).__name__}")
        stripped = tag.strip()
        if not stripped:
            raise ValueError("Tags cannot be empty")
        if not _TAG_RE.match(stripped):
            raise ValueError(
                f"Invalid tag: {tag!r}. Tags must start with a letter "
                f"and contain only letters, digits, spaces, hyphens, and "
                f"underscores (1-40 chars)."
            )
        # Check for control characters
        if any(ord(c) < 32 for c in stripped):
            raise ValueError(f"Tag contains control characters: {tag!r}")
        # Check for HTML/script
        lower = stripped.lower()
        if "<script" in lower or "javascript:" in lower or "onerror" in lower:
            raise ValueError(f"Tag contains dangerous content: {tag!r}")
        # Check for duplicates (case-insensitive)
        key = stripped.lower()
        if key in seen:
            raise ValueError(f"Duplicate tag: {tag!r}")
        seen.add(key)
        result.append(stripped)
    return result


# ISO 8601-ish date or datetime
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_youtube_url(video_id: str) -> str:
    """Return the canonical watch URL for a YouTube video ID."""
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_youtube_id(url_or_id: str) -> str | None:
    """Extract an 11-char YouTube video ID from a URL or bare ID."""
    url_or_id = url_or_id.strip()
    if _CANONICAL_RE.match(url_or_id):
        return url_or_id
    m = _YOUTUBE_URL_RE.match(url_or_id)
    if m:
        return m.group(2)
    m = _YOUTUBE_SHORTS_RE.match(url_or_id)
    if m:
        return m.group(2)
    return None


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------

class Topic(BaseModel):
    """A user-defined subject to follow."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1, max_length=2000)
    is_archived: bool = False
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("id", "name", "intent", mode="before")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("created_at", "updated_at")
    @classmethod
    def _validate_datetime(cls, v: str) -> str:
        if not _DATETIME_RE.match(v):
            raise ValueError("must be ISO-8601 datetime")
        return v


# ---------------------------------------------------------------------------
# QueryRule
# ---------------------------------------------------------------------------

class QueryRule(BaseModel):
    """Explicit, inspectable search rules for a topic."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    topic_id: str = Field(min_length=1, max_length=64)
    primary_query: str = Field(min_length=1, max_length=200)
    related_queries: list[str] = Field(default_factory=list, max_length=20)
    required_terms: list[str] = Field(default_factory=list, max_length=20)
    excluded_terms: list[str] = Field(default_factory=list, max_length=20)
    preferred_languages: list[str] = Field(default_factory=list, max_length=10)
    included_channels: list[str] = Field(default_factory=list, max_length=50)
    excluded_channels: list[str] = Field(default_factory=list, max_length=50)
    duration_preference: DurationPreference = DurationPreference.ANY
    shorts_preference: ShortsPreference = ShortsPreference.INCLUDE
    date_window_start: str | None = None
    date_window_end: str | None = None
    default_sort: DefaultSort = DefaultSort.NEWEST
    is_active: bool = True
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator(
        "primary_query", "related_queries", "required_terms",
        "excluded_terms", "preferred_languages",
        "included_channels", "excluded_channels",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, v):
        if isinstance(v, list):
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("related_queries", "required_terms", "excluded_terms",
                     "preferred_languages", "included_channels",
                     "excluded_channels")
    @classmethod
    def _no_duplicates(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("duplicate entries are not allowed")
        return v

    @field_validator("date_window_start", "date_window_end")
    @classmethod
    def _validate_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _DATE_RE.match(v):
            raise ValueError("must be YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def _validate_window(self) -> "QueryRule":
        if self.date_window_start and self.date_window_end:
            if self.date_window_start > self.date_window_end:
                raise ValueError(
                    "date_window_start must not be after date_window_end"
                )
        return self


# ---------------------------------------------------------------------------
# DiscoveredVideo
# ---------------------------------------------------------------------------

class DiscoveredVideo(BaseModel):
    """YouTube-sourced metadata for a discovered video."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    provider: str = Field(default="youtube", min_length=1, max_length=40)
    provider_video_id: str = Field(min_length=1, max_length=40)
    canonical_url: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    channel_id: str = Field(default="", max_length=100)
    channel_title: str = Field(default="", max_length=200)
    published_at: str = Field(min_length=1, max_length=40)
    duration_seconds: int | None = Field(default=None, ge=0)
    view_count: int | None = Field(default=None, ge=0)
    like_count: int | None = Field(default=None, ge=0)
    thumbnail_url: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=100)
    provenance: Provenance = Provenance.YOUTUBE
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("canonical_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        vid = extract_youtube_id(v)
        if vid is None:
            raise ValueError("canonical_url must be a valid YouTube URL")
        return canonical_youtube_url(vid)

    @field_validator("provider_video_id")
    @classmethod
    def _validate_provider_id(cls, v: str) -> str:
        if extract_youtube_id(v) is None:
            raise ValueError("provider_video_id must be a valid YouTube ID")
        return v

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: list[str]) -> list[str]:
        seen = set()
        for t in v:
            if not _TAG_RE.match(t):
                raise ValueError(f"invalid tag: {t!r}")
            if t in seen:
                raise ValueError(f"duplicate tag: {t!r}")
            seen.add(t)
        return v


# ---------------------------------------------------------------------------
# TopicVideo
# ---------------------------------------------------------------------------

class TopicVideo(BaseModel):
    """Association between a Topic and a DiscoveredVideo."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    topic_id: str = Field(min_length=1, max_length=64)
    video_id: str = Field(min_length=1, max_length=64)
    first_matched_at: str = Field(default_factory=_now_iso)
    last_matched_at: str = Field(default_factory=_now_iso)
    match_score: float | None = Field(default=None, ge=0.0, le=1.0)
    match_reasons: list[str] = Field(default_factory=list, max_length=20)
    is_excluded: bool = False
    provenance: Provenance = Provenance.APPLICATION
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# TimestampReference
# ---------------------------------------------------------------------------

class TimestampReference(BaseModel):
    """A user-entered timestamp reference within a viewing record."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    record_id: str = Field(min_length=1, max_length=64)
    timestamp_seconds: int = Field(ge=0)
    label: str = Field(default="", max_length=200)
    created_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# PrivateViewingRecord
# ---------------------------------------------------------------------------

class PrivateViewingRecord(BaseModel):
    """User-authored private record for a topic-video pair."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    topic_video_id: str = Field(min_length=1, max_length=64)
    viewing_state: ViewingState = ViewingState.UNSEEN
    rating: int | None = Field(default=None, ge=1, le=5)
    reflection: str = Field(default="", max_length=5000)
    learned_point: str = Field(default="", max_length=5000)
    agreement: str = Field(default="", max_length=5000)
    disagreement: str = Field(default="", max_length=5000)
    uncertainty: str = Field(default="", max_length=5000)
    follow_up_plan: str = Field(default="", max_length=5000)
    free_form_note: str = Field(default="", max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    opened_date: str | None = None
    completed_date: str | None = None
    timestamp_references: list[TimestampReference] = Field(default_factory=list)
    provenance: Provenance = Provenance.USER
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: list[str]) -> list[str]:
        seen = set()
        for t in v:
            if not _TAG_RE.match(t):
                raise ValueError(f"invalid tag: {t!r}")
            if t in seen:
                raise ValueError(f"duplicate tag: {t!r}")
            seen.add(t)
        return v

    @field_validator("opened_date", "completed_date")
    @classmethod
    def _validate_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _DATE_RE.match(v):
            raise ValueError("must be YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def _validate_dates(self) -> "PrivateViewingRecord":
        if self.opened_date and self.completed_date:
            if self.opened_date > self.completed_date:
                raise ValueError(
                    "opened_date must not be after completed_date"
                )
        return self


# ---------------------------------------------------------------------------
# SyncRun
# ---------------------------------------------------------------------------

class SyncRun(BaseModel):
    """Audit record for a discovery sync run."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    topic_id: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=40)
    started_at: str = Field(default_factory=_now_iso)
    completed_at: str | None = None
    status: SyncStatus = SyncStatus.RUNNING
    videos_found: int = Field(default=0, ge=0)
    videos_added: int = Field(default=0, ge=0)
    videos_updated: int = Field(default=0, ge=0)
    quota_cost: int = Field(default=0, ge=0)
    error_message: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------------------
# QuotaLedger
# ---------------------------------------------------------------------------

class QuotaLedgerEntry(BaseModel):
    """A single quota consumption event."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    topic_id: str = Field(min_length=1, max_length=64)
    sync_run_id: str | None = None
    provider: str = Field(min_length=1, max_length=40)
    operation: str = Field(min_length=1, max_length=100)
    cost: int = Field(ge=0)
    recorded_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# LLM Proposal
# ---------------------------------------------------------------------------

class QueryRuleProposal(BaseModel):
    """A proposed QueryRule draft from the LLM."""

    model_config = ConfigDict(extra="forbid")

    primary_query: str = Field(min_length=1, max_length=200)
    related_queries: list[str] = Field(default_factory=list, max_length=20)
    required_terms: list[str] = Field(default_factory=list, max_length=20)
    excluded_terms: list[str] = Field(default_factory=list, max_length=20)
    preferred_languages: list[str] = Field(default_factory=list, max_length=10)
    included_channels: list[str] = Field(default_factory=list, max_length=50)
    excluded_channels: list[str] = Field(default_factory=list, max_length=50)
    duration_preference: DurationPreference = DurationPreference.ANY
    shorts_preference: ShortsPreference = ShortsPreference.INCLUDE
    date_window_start: str | None = None
    date_window_end: str | None = None
    default_sort: DefaultSort = DefaultSort.NEWEST
    rationale: str = Field(default="", max_length=2000)

    @field_validator(
        "primary_query", "related_queries", "required_terms",
        "excluded_terms", "preferred_languages",
        "included_channels", "excluded_channels",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, v):
        if isinstance(v, list):
            return [s.strip() for s in v if isinstance(s, str) and s.strip()]
        if isinstance(v, str):
            return v.strip()
        return v


class VideoClassification(BaseModel):
    """Application-derived match classification for a video."""

    model_config = ConfigDict(extra="forbid")

    video_id: str = Field(min_length=1, max_length=64)
    match_level: str = Field(min_length=1, max_length=20)  # strong|possible|noise
    reasons: list[str] = Field(default_factory=list, max_length=20)
    is_excluded_candidate: bool = False


class RecordStructureProposal(BaseModel):
    """Structured proposal for a private viewing record from rough notes."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=1000)
    reflection: str = Field(default="", max_length=5000)
    learned_point: str = Field(default="", max_length=5000)
    agreement: str = Field(default="", max_length=5000)
    disagreement: str = Field(default="", max_length=5000)
    uncertainty: str = Field(default="", max_length=5000)
    follow_up_plan: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    timestamp_references: list[dict[str, Any]] = Field(default_factory=list)
    rating: int | None = Field(default=None, ge=1, le=5)


class RuleChangeProposal(BaseModel):
    """Proposed search-rule changes from user feedback."""

    model_config = ConfigDict(extra="forbid")

    added_excluded_terms: list[str] = Field(default_factory=list, max_length=20)
    added_related_queries: list[str] = Field(default_factory=list, max_length=20)
    preferred_channels: list[str] = Field(default_factory=list, max_length=50)
    excluded_channels: list[str] = Field(default_factory=list, max_length=50)
    exclude_shorts: bool = False
    date_window_start: str | None = None
    date_window_end: str | None = None
    duration_preference: DurationPreference | None = None
    rationale: str = Field(default="", max_length=2000)


class ProposalRecord(BaseModel):
    """Persisted LLM proposal with pending/accepted/rejected lifecycle."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    topic_id: str | None = None
    record_id: str | None = None
    proposal_type: ProposalType
    status: ProposalStatus = ProposalStatus.PENDING
    input_text: str = Field(default="", max_length=20000)
    proposed_json: str = Field(min_length=1, max_length=50000)
    validation_status: ValidationStatus = ValidationStatus.VALID
    validation_error: str = Field(default="", max_length=2000)
    created_at: str = Field(default_factory=_now_iso)
    decided_at: str | None = None
