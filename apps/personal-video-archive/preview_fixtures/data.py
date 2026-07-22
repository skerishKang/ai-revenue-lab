"""Synthetic, deterministic fixtures for the static UI preview.

These fixtures contain ONLY fake data: no real personal data, no real
YouTube identifiers, no secrets, and no production URLs.  Every id and
timestamp is a fixed constant so that repeated builds produce
byte-identical output (a hard requirement for the preview build).

The fixtures reuse the real domain models so the preview renders exactly
the same shapes the live templates consume.
"""

from __future__ import annotations

import json

from app.domain.enums import (
    DefaultSort,
    DurationPreference,
    ProposalStatus,
    ProposalType,
    ShortsPreference,
    ValidationStatus,
    ViewingState,
)
from app.domain.models import (
    DiscoveredVideo,
    PrivateViewingRecord,
    ProposalRecord,
    QueryRule,
    QueryRuleProposal,
    TimestampReference,
    Topic,
    TopicVideo,
)

# Local placeholder thumbnail so the preview never references an external
# image host (and never leaks a production CDN URL).
THUMBNAIL_URL = "/static/preview-thumb.svg"


def _ytid(n: int) -> str:
    """Deterministic synthetic 11-char YouTube-shaped id."""
    return f"pvvid{n:06d}"


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def make_topics() -> list[Topic]:
    return [
        Topic(
            id="pv-topic-0001",
            name="PyTorch deep-dive tutorials",
            intent=(
                "Newly published, in-depth PyTorch tutorials and lectures, "
                "preferably with code walkthroughs. Exclude shorts and "
                "promotional clips."
            ),
            is_archived=False,
            created_at="2026-01-05T09:00:00Z",
            updated_at="2026-01-05T09:00:00Z",
        ),
        Topic(
            id="pv-topic-0002",
            name="Rust for systems programmers",
            intent=(
                "Practical Rust systems-programming videos: ownership, async "
                "runtimes, and FFI. English or Korean."
            ),
            is_archived=False,
            created_at="2026-01-08T11:30:00Z",
            updated_at="2026-01-08T11:30:00Z",
        ),
        Topic(
            id="pv-topic-0003",
            name="Urban sketching techniques",
            intent="Urban sketching demonstrations and pen-and-ink techniques.",
            is_archived=True,
            created_at="2025-11-20T08:00:00Z",
            updated_at="2025-12-01T08:00:00Z",
        ),
    ]


def make_topic(topic_id: str = "pv-topic-0001") -> Topic:
    for topic in make_topics():
        if topic.id == topic_id:
            return topic
    return make_topics()[0]


# ---------------------------------------------------------------------------
# Query rule + LLM rule proposal
# ---------------------------------------------------------------------------

def make_query_rule() -> QueryRule:
    return QueryRule(
        id="pv-rule-0001",
        topic_id="pv-topic-0001",
        primary_query="PyTorch tutorial",
        related_queries=["pytorch deep dive", "pytorch lightning"],
        required_terms=["pytorch"],
        excluded_terms=["shorts", "reaction"],
        preferred_languages=["en", "ko"],
        included_channels=[],
        excluded_channels=[],
        duration_preference=DurationPreference.MEDIUM,
        shorts_preference=ShortsPreference.EXCLUDE,
        default_sort=DefaultSort.NEWEST,
        is_active=True,
        created_at="2026-01-05T09:05:00Z",
        updated_at="2026-01-05T09:05:00Z",
    )


def make_query_rule_proposal() -> QueryRuleProposal:
    return QueryRuleProposal(
        primary_query="PyTorch tutorial",
        related_queries=["pytorch deep dive", "pytorch lightning"],
        required_terms=["pytorch"],
        excluded_terms=["shorts", "reaction"],
        preferred_languages=["en", "ko"],
        included_channels=[],
        excluded_channels=[],
        duration_preference=DurationPreference.MEDIUM,
        shorts_preference=ShortsPreference.EXCLUDE,
        default_sort=DefaultSort.NEWEST,
        date_window_start="2025-07-01",
        date_window_end=None,
        rationale=(
            "Synthetic suggestion: prioritise medium-length, newest-first "
            "tutorials that explicitly mention PyTorch, while filtering out "
            "shorts and reaction content."
        ),
    )


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

def _make_video(
    n: int,
    title: str,
    published_at: str,
    duration_seconds: int,
    view_count: int,
    description: str,
    channel_title: str = "Synthetic Learning Channel",
) -> DiscoveredVideo:
    ytid = _ytid(n)
    return DiscoveredVideo(
        id=f"pv-video-{n:04d}",
        provider="youtube",
        provider_video_id=ytid,
        canonical_url=f"https://www.youtube.com/watch?v={ytid}",
        title=title,
        description=description,
        channel_id=f"pv-channel-{n:04d}",
        channel_title=channel_title,
        published_at=published_at,
        duration_seconds=duration_seconds,
        view_count=view_count,
        like_count=view_count // 40,
        thumbnail_url=THUMBNAIL_URL,
        tags=[],
        created_at="2026-01-21T00:00:00Z",
        updated_at="2026-01-21T00:00:00Z",
    )


def make_topic1_videos() -> list[DiscoveredVideo]:
    return [
        _make_video(
            1,
            "Synthetic PyTorch Tutorial 1: Tensors and Autograd",
            "2026-01-20T10:00:00Z",
            1320,
            18400,
            "A synthetic, in-depth walkthrough of tensors and automatic "
            "differentiation. Generated for UI preview only.",
        ),
        _make_video(
            2,
            "Synthetic PyTorch Tutorial 2: Building a Data Pipeline",
            "2026-01-18T09:00:00Z",
            960,
            9200,
            "Synthetic demonstration of a reproducible data pipeline. "
            "Generated for UI preview only.",
        ),
        _make_video(
            3,
            "Synthetic Deep Dive: Custom CUDA Kernels",
            "2026-01-15T14:00:00Z",
            2100,
            30150,
            "Synthetic deep dive into custom kernels. Generated for UI "
            "preview only.",
        ),
        _make_video(
            4,
            "Synthetic PyTorch Lightning Crash Course",
            "2026-01-12T08:00:00Z",
            720,
            5400,
            "Synthetic crash course. Generated for UI preview only.",
        ),
        _make_video(
            5,
            "Synthetic Lecture: Optimization Internals",
            "2026-01-10T16:00:00Z",
            3000,
            12700,
            "Synthetic lecture on optimizer internals. Generated for UI "
            "preview only.",
        ),
    ]


def make_topic2_videos() -> list[DiscoveredVideo]:
    return [
        _make_video(
            101,
            "Synthetic Rust 1: Ownership Explained",
            "2026-01-19T10:00:00Z",
            1500,
            22100,
            "Synthetic Rust ownership explainer. Generated for UI preview only.",
            channel_title="Synthetic Systems Channel",
        ),
        _make_video(
            102,
            "Synthetic Rust 2: Tokio Async Runtime",
            "2026-01-14T10:00:00Z",
            1800,
            14300,
            "Synthetic async runtime tour. Generated for UI preview only.",
            channel_title="Synthetic Systems Channel",
        ),
    ]


# ---------------------------------------------------------------------------
# Topic-video associations
# ---------------------------------------------------------------------------

def _make_topic_video(
    n: int,
    topic_id: str,
    video_id: str,
    match_score: float | None,
    match_reasons: list[str],
    first_matched_at: str,
) -> TopicVideo:
    return TopicVideo(
        id=f"pv-tv-{n:04d}",
        topic_id=topic_id,
        video_id=video_id,
        first_matched_at=first_matched_at,
        last_matched_at=first_matched_at,
        match_score=match_score,
        match_reasons=match_reasons,
        is_excluded=False,
        created_at=first_matched_at,
        updated_at=first_matched_at,
    )


def make_topic1_topic_videos() -> list[TopicVideo]:
    videos = make_topic1_videos()
    return [
        _make_topic_video(
            1, "pv-topic-0001", videos[0].id, 0.94,
            ["Contains required term 'pytorch'",
             "Published within the last 30 days"],
            "2026-01-21T00:05:00Z",
        ),
        _make_topic_video(
            2, "pv-topic-0001", videos[1].id, 0.88,
            ["Matches related query 'pytorch data pipeline'"],
            "2026-01-21T00:05:00Z",
        ),
        _make_topic_video(
            3, "pv-topic-0001", videos[2].id, 0.81,
            ["Contains required term 'pytorch'", "Long-form deep dive"],
            "2026-01-21T00:05:00Z",
        ),
        _make_topic_video(
            4, "pv-topic-0001", videos[3].id, None, [],
            "2026-01-21T00:05:00Z",
        ),
        _make_topic_video(
            5, "pv-topic-0001", videos[4].id, 0.72,
            ["Matches primary query"],
            "2026-01-21T00:05:00Z",
        ),
    ]


def make_topic2_topic_videos() -> list[TopicVideo]:
    videos = make_topic2_videos()
    return [
        _make_topic_video(
            101, "pv-topic-0002", videos[0].id, 0.9,
            ["Contains required term 'rust'"],
            "2026-01-21T00:06:00Z",
        ),
        _make_topic_video(
            102, "pv-topic-0002", videos[1].id, 0.85,
            ["Matches related query 'tokio async'"],
            "2026-01-21T00:06:00Z",
        ),
    ]


# ---------------------------------------------------------------------------
# Private viewing records
# ---------------------------------------------------------------------------

def make_record_completed() -> PrivateViewingRecord:
    """An accepted, fully structured private record."""
    return PrivateViewingRecord(
        id="pv-rec-0001",
        topic_video_id="pv-tv-0001",
        viewing_state=ViewingState.COMPLETED,
        rating=5,
        reflection=(
            "Clear explanation of how autograd builds the computation graph "
            "on the fly. The backward pass demo made the gradient flow click."
        ),
        learned_point=(
            "detach() and torch.no_grad() serve different purposes: detach "
            "splits the graph, no_grad disables tracking entirely."
        ),
        agreement="Gradient accumulation across steps matches my mental model.",
        disagreement="The claim that in-place ops are always slower seemed oversimplified.",
        uncertainty="Still unsure how this interacts with mixed-precision scaling.",
        follow_up_plan="Reproduce the autograd example and add a custom backward.",
        free_form_note=(
            "Rough note kept verbatim: tensors are views vs copies — watch out "
            "for the .data escape hatch. This original text is never "
            "overwritten by AI suggestions."
        ),
        tags=["pytorch", "autograd"],
        opened_date="2026-01-21",
        completed_date="2026-01-22",
        timestamp_references=[],
        created_at="2026-01-21T10:00:00Z",
        updated_at="2026-01-22T18:00:00Z",
    )


def make_record_in_progress() -> PrivateViewingRecord:
    """A record mid-viewing with rough notes and a pending AI proposal."""
    return PrivateViewingRecord(
        id="pv-rec-0002",
        topic_video_id="pv-tv-0002",
        viewing_state=ViewingState.IN_PROGRESS,
        rating=None,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="",
        free_form_note=(
            "rough notes: dataloader workers, pin_memory helps gpu transfer, "
            "collate_fn custom batching... need to rewatch the sampler part"
        ),
        tags=["pytorch"],
        opened_date="2026-01-21",
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-21T11:00:00Z",
        updated_at="2026-01-21T11:30:00Z",
    )


def make_record_saved() -> PrivateViewingRecord:
    """A minimal saved record used for the detail/edit example."""
    return PrivateViewingRecord(
        id="pv-rec-0003",
        topic_video_id="pv-tv-0003",
        viewing_state=ViewingState.SAVED,
        rating=4,
        reflection="",
        learned_point="",
        agreement="",
        disagreement="",
        uncertainty="",
        follow_up_plan="Watch the kernel launch section again this weekend.",
        free_form_note="Saved for later — the CUDA kernel section looks useful.",
        tags=["cuda"],
        opened_date=None,
        completed_date=None,
        timestamp_references=[],
        created_at="2026-01-21T12:00:00Z",
        updated_at="2026-01-21T12:00:00Z",
    )


def make_timestamps() -> list[TimestampReference]:
    return [
        TimestampReference(
            id="pv-ts-0001",
            record_id="pv-rec-0001",
            timestamp_seconds=125,
            label="Autograd intro",
            created_at="2026-01-22T18:00:00Z",
        ),
        TimestampReference(
            id="pv-ts-0002",
            record_id="pv-rec-0001",
            timestamp_seconds=754,
            label="Backprop walkthrough",
            created_at="2026-01-22T18:00:00Z",
        ),
    ]


# ---------------------------------------------------------------------------
# LLM structure proposal (pending)
# ---------------------------------------------------------------------------

def make_structure_proposal() -> ProposalRecord:
    proposed = {
        "title": "Synthetic PyTorch Data Pipeline",
        "summary": "Reproducible data loading with workers and custom collation.",
        "reflection": "pin_memory speeds up host-to-device transfer.",
        "learned_point": "collate_fn controls how samples are batched.",
        "agreement": "Worker prefetching matches observed speedups.",
        "disagreement": "",
        "uncertainty": "Sampler behaviour with distributed training.",
        "follow_up_plan": "Rewatch the sampler section and take notes.",
        "tags": ["pytorch", "dataloader"],
        "rating": 4,
    }
    return ProposalRecord(
        id="pv-prop-0001",
        topic_id=None,
        record_id="pv-rec-0002",
        proposal_type=ProposalType.RECORD_STRUCTURE,
        status=ProposalStatus.PENDING,
        input_text=(
            "rough notes: dataloader workers, pin_memory helps gpu transfer, "
            "collate_fn custom batching"
        ),
        proposed_json=json.dumps(proposed, ensure_ascii=False, indent=2, sort_keys=True),
        validation_status=ValidationStatus.VALID,
        validation_error="",
        created_at="2026-01-21T11:45:00Z",
        decided_at=None,
    )


# ---------------------------------------------------------------------------
# Feed assembly helpers
# ---------------------------------------------------------------------------

def make_topic1_feed() -> list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]]:
    """Newest-first feed for topic 1 with a mix of viewing states."""
    videos = make_topic1_videos()
    tvs = make_topic1_topic_videos()
    rec_completed = make_record_completed()
    rec_in_progress = make_record_in_progress()
    rec_saved = make_record_saved()
    records_by_tv = {
        "pv-tv-0001": rec_completed,
        "pv-tv-0002": rec_in_progress,
        "pv-tv-0003": rec_saved,
    }
    return [
        (tvs[i], videos[i], records_by_tv.get(tvs[i].id))
        for i in range(len(videos))
    ]


def make_topic2_feed() -> list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]]:
    videos = make_topic2_videos()
    tvs = make_topic2_topic_videos()
    return [(tvs[i], videos[i], None) for i in range(len(videos))]


def filter_feed_by_state(
    feed: list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]],
    state: str,
) -> list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]]:
    """Mirror the app's viewing-state filter for the preview."""
    out = []
    for tv, video, record in feed:
        record_state = record.viewing_state.value if record else ViewingState.UNSEEN.value
        if record_state == state:
            out.append((tv, video, record))
    return out


def make_search_results() -> list[tuple[PrivateViewingRecord, TopicVideo, DiscoveredVideo]]:
    videos = make_topic1_videos()
    tvs = make_topic1_topic_videos()
    return [
        (make_record_completed(), tvs[0], videos[0]),
        (make_record_in_progress(), tvs[1], videos[1]),
        (make_record_saved(), tvs[2], videos[2]),
    ]
