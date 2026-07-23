"""Domain enums for Personal Video Archive."""

from __future__ import annotations

from enum import Enum


class ViewingState(str, Enum):
    """States a user can set for a video within a topic."""

    UNSEEN = "unseen"
    OPENED = "opened"
    SAVED = "saved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVISIT = "revisit"
    IRRELEVANT = "irrelevant"


# Ordered list for filter UI — newest-first feed is the default ordering,
# but viewing-state filtering uses this canonical order.
VIEWING_STATE_ORDER = [
    ViewingState.UNSEEN,
    ViewingState.OPENED,
    ViewingState.SAVED,
    ViewingState.IN_PROGRESS,
    ViewingState.COMPLETED,
    ViewingState.REVISIT,
    ViewingState.IRRELEVANT,
]


class Provenance(str, Enum):
    """Origin of a piece of data, used to keep sources visibly distinct."""

    YOUTUBE = "youtube"
    APPLICATION = "application"
    USER = "user"


class DurationPreference(str, Enum):
    ANY = "any"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class ShortsPreference(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


class DefaultSort(str, Enum):
    NEWEST = "newest"
    RELEVANCE = "relevance"
    VIEW_COUNT = "view_count"


class ProposalType(str, Enum):
    QUERY_RULE = "query_rule"
    RECORD_STRUCTURE = "record_structure"
    TITLE_SUMMARY = "title_summary"
    RULE_CHANGE = "rule_change"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


class SyncStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
