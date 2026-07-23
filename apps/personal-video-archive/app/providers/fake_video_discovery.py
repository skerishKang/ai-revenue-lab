"""Deterministic fake video discovery provider.

Returns synthetic, reproducible video fixtures based on the search rules.
No network calls are made.  The same rules always produce the same set
of videos, so test results are stable across runs.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.domain.enums import ProviderHealth
from app.domain.models import DiscoveredVideo, QueryRule
from app.providers import (
    ProviderHealthCheck,
    SearchPage,
    VideoDiscoveryProvider,
)


# Synthetic channel pool — deterministic, no real channel IDs.
_SYNTHETIC_CHANNELS = [
    ("UC_synthetic_ai_01", "AI Pulse Daily"),
    ("UC_synthetic_ai_02", "Tech Insights Weekly"),
    ("UC_synthetic_ai_03", "Future Tools"),
    ("UC_synthetic_ai_04", "Code & Coffee"),
    ("UC_synthetic_ai_05", "Research Digest"),
    ("UC_synthetic_ai_06", "Startup Stories"),
    ("UC_synthetic_ai_07", "Dev Tools Today"),
    ("UC_synthetic_ai_08", "AI Ethics Watch"),
]

# Synthetic video templates — the fake provider generates variations
# deterministically from a hash of the primary query.
_VIDEO_TEMPLATES = [
    {
        "title": "{q} — latest update explained",
        "description": "A concise walkthrough of the newest developments in {q}. "
                       "Timestamps included in the video.",
        "duration": 600,
        "views": 12000,
    },
    {
        "title": "{q} tutorial for beginners",
        "description": "Step-by-step tutorial covering {q} fundamentals.",
        "duration": 900,
        "views": 45000,
    },
    {
        "title": "What's new in {q} this week",
        "description": "Weekly roundup of {q} news and releases.",
        "duration": 480,
        "views": 8800,
    },
    {
        "title": "{q} deep dive: architecture",
        "description": "Deep technical analysis of {q} architecture and design.",
        "duration": 1800,
        "views": 22000,
    },
    {
        "title": "Building with {q} — practical guide",
        "description": "Practical examples and best practices for {q}.",
        "duration": 1200,
        "views": 35000,
    },
    {
        "title": "{q} vs alternatives comparison",
        "description": "Comparing {q} against other solutions in the space.",
        "duration": 720,
        "views": 18000,
    },
    {
        "title": "Common mistakes with {q}",
        "description": "Avoid these pitfalls when working with {q}.",
        "duration": 540,
        "views": 15000,
    },
    {
        "title": "{q} roadmap and future features",
        "description": "What's coming next for {q}.",
        "duration": 660,
        "views": 9500,
    },
]


def _deterministic_seed(*parts: str) -> int:
    """Hash input parts into a stable integer seed."""
    h = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return int(h[:12], 16)


def _generate_video_id(seed: int, index: int) -> str:
    """Generate a deterministic 11-char YouTube-style video ID."""
    h = hashlib.sha256(f"{seed}-{index}".encode("utf-8")).hexdigest()
    # YouTube video IDs use base64url-ish characters
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    return "".join(chars[int(h[i], 16) % len(chars)] for i in range(11))


def _generate_published_at(seed: int, index: int) -> str:
    """Generate a deterministic published timestamp, newest first."""
    # Each video is published 1-30 days ago, decreasing by index
    days_ago = 30 - (index % 30)
    hours_ago = (seed % 24) + index
    # Use a fixed base date for determinism
    base_year = 2026
    base_month = 7
    base_day = 15
    day = base_day - days_ago
    if day < 1:
        day += 30
        month = base_month - 1
    else:
        month = base_month
    return f"{base_year}-{month:02d}-{day:02d}T{hours_ago % 24:02d}:00:00Z"


class FakeVideoDiscoveryProvider(VideoDiscoveryProvider):
    """Deterministic fake provider returning synthetic video fixtures.

    The same QueryRule always yields the same video set, sorted newest-first.
    No network calls are ever made.
    """

    def __init__(self, video_count: int = 12):
        self._video_count = video_count
        self._provider_name = "fake-video-discovery"

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @staticmethod
    def _sanitize_tag(text: str) -> str:
        """Convert a query string into a valid tag (no spaces)."""
        return text.replace(" ", "-").replace("_", "-")[:40] or "video"

    def _build_videos(self, rules: QueryRule) -> list[DiscoveredVideo]:
        """Generate deterministic synthetic videos for the given rules."""
        seed = _deterministic_seed(
            rules.primary_query,
            ",".join(rules.related_queries),
            ",".join(rules.excluded_terms),
            ",".join(rules.preferred_languages),
        )

        videos: list[DiscoveredVideo] = []
        count = min(self._video_count, 20)

        for i in range(count):
            template = _VIDEO_TEMPLATES[i % len(_VIDEO_TEMPLATES)]
            channel = _SYNTHETIC_CHANNELS[i % len(_SYNTHETIC_CHANNELS)]
            video_id = _generate_video_id(seed, i)
            title = template["title"].format(q=rules.primary_query)
            description = template["description"].format(q=rules.primary_query)
            published_at = _generate_published_at(seed, i)

            # If shorts are excluded, mark some as shorts and skip them
            is_short = (i % 5 == 0)
            if rules.shorts_preference == "exclude" and is_short:
                continue

            # If excluded terms appear in title, skip
            title_lower = title.lower()
            if any(term.lower() in title_lower for term in rules.excluded_terms):
                continue

            # If required terms are specified, ensure at least one appears
            if rules.required_terms:
                if not any(
                    term.lower() in title_lower
                    for term in rules.required_terms
                ):
                    continue

            video = DiscoveredVideo(
                id=f"v_{video_id}",
                provider="youtube",
                provider_video_id=video_id,
                canonical_url=f"https://www.youtube.com/watch?v={video_id}",
                title=title,
                description=description,
                channel_id=channel[0],
                channel_title=channel[1],
                published_at=published_at,
                duration_seconds=template["duration"],
                view_count=template["views"] + (seed % 1000),
                like_count=template["views"] // 10 + (seed % 500),
                thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                tags=[self._sanitize_tag(rules.primary_query), "synthetic"],
            )
            videos.append(video)

        # Sort newest-first by published_at (descending)
        videos.sort(key=lambda v: v.published_at, reverse=True)

        return videos

    def search_videos(
        self,
        rules: QueryRule,
        cursor: str | None = None,
    ) -> SearchPage:
        all_videos = self._build_videos(rules)

        # Simple cursor-based pagination: cursor is an offset index
        page_size = 12
        offset = 0
        if cursor:
            try:
                offset = int(cursor)
            except ValueError:
                offset = 0

        page_videos = all_videos[offset:offset + page_size]
        next_cursor = None
        if offset + page_size < len(all_videos):
            next_cursor = str(offset + page_size)

        return SearchPage(
            videos=page_videos,
            next_cursor=next_cursor,
            total_estimate=len(all_videos),
            provider=self._provider_name,
            quota_cost=1,
            raw_response=None,
        )

    def get_video_details(
        self,
        video_ids: list[str],
    ) -> list[DiscoveredVideo]:
        """Return synthetic details for the given video IDs.

        Since the fake provider generates videos from rules, we reconstruct
        a minimal set of videos by searching with a default rule and filtering.
        """
        # Build a default rule to generate the full synthetic pool
        default_rules = QueryRule(
            id="default",
            topic_id="default",
            primary_query="video",
        )
        all_videos = self._build_videos(default_rules)
        by_id = {v.provider_video_id: v for v in all_videos}

        result = []
        for vid in video_ids:
            # Strip prefix if present
            clean_id = vid.replace("v_", "") if vid.startswith("v_") else vid
            if clean_id in by_id:
                result.append(by_id[clean_id])
            else:
                # Generate a single video for unknown IDs
                seed = _deterministic_seed(clean_id)
                template = _VIDEO_TEMPLATES[0]
                channel = _SYNTHETIC_CHANNELS[0]
                video = DiscoveredVideo(
                    id=f"v_{clean_id}",
                    provider="youtube",
                    provider_video_id=clean_id,
                    canonical_url=f"https://www.youtube.com/watch?v={clean_id}",
                    title=template["title"].format(q="video"),
                    description=template["description"].format(q="video"),
                    channel_id=channel[0],
                    channel_title=channel[1],
                    published_at=_generate_published_at(seed, 0),
                    duration_seconds=template["duration"],
                    view_count=template["views"],
                    like_count=template["views"] // 10,
                    thumbnail_url=f"https://i.ytimg.com/vi/{clean_id}/hqdefault.jpg",
                    tags=["synthetic"],
                )
                result.append(video)

        return result

    def health_check(self) -> ProviderHealthCheck:
        return ProviderHealthCheck(
            provider=self._provider_name,
            status=ProviderHealth.HEALTHY,
            message="fake provider is always healthy",
            quota_remaining=10000,
        )
