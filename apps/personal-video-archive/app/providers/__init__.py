"""Provider interfaces for Personal Video Archive.

These abstract boundaries keep the domain and application layers independent
of any concrete provider.  Phase 1 uses deterministic fake implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import ProviderHealth
from app.domain.models import (
    DiscoveredVideo,
    QueryRule,
    QueryRuleProposal,
    RecordStructureProposal,
    RuleChangeProposal,
    VideoClassification,
)


@dataclass(frozen=True)
class SearchPage:
    """A page of search results from a discovery provider."""

    videos: list[DiscoveredVideo]
    next_cursor: str | None = None
    total_estimate: int | None = None
    provider: str = "unknown"
    quota_cost: int = 0
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProviderHealthCheck:
    """Normalized health status from a provider."""

    provider: str
    status: ProviderHealth
    message: str = ""
    quota_remaining: int | None = None


class VideoDiscoveryProvider(ABC):
    """Interface for discovering videos matching topic rules."""

    @abstractmethod
    def search_videos(
        self,
        rules: QueryRule,
        cursor: str | None = None,
    ) -> SearchPage:
        """Search for videos matching the given rules."""

    @abstractmethod
    def get_video_details(
        self,
        video_ids: list[str],
    ) -> list[DiscoveredVideo]:
        """Fetch detailed metadata for specific video IDs."""

    @abstractmethod
    def health_check(self) -> ProviderHealthCheck:
        """Check provider availability."""


class LanguageModelProvider(ABC):
    """Interface for LLM-assisted workflows.

    Every method returns a *proposal* that must be validated and
    user-accepted before it changes any persisted data.
    """

    @abstractmethod
    def propose_query_rules(self, intent: str) -> QueryRuleProposal:
        """Convert natural-language intent into a search-rule draft."""

    @abstractmethod
    def classify_videos(
        self,
        videos: list[DiscoveredVideo],
        rules: QueryRule,
    ) -> list[VideoClassification]:
        """Classify retrieved videos by match quality."""

    @abstractmethod
    def suggest_rule_changes(
        self,
        feedback: list[tuple[str, bool]],
        rules: QueryRule,
    ) -> RuleChangeProposal:
        """Propose rule changes based on relevant/irrelevant feedback."""

    @abstractmethod
    def structure_record(
        self,
        rough_notes: str,
    ) -> RecordStructureProposal:
        """Turn rough viewing notes into a structured proposal."""

    @abstractmethod
    def suggest_title_summary(
        self,
        rough_notes: str,
    ) -> tuple[str, str]:
        """Suggest a title and summary for a private record."""
