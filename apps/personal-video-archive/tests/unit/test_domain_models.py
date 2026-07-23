"""Unit tests for domain models and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    DefaultSort,
    DurationPreference,
    Provenance,
    ShortsPreference,
    ViewingState,
)
from app.domain.models import (
    DiscoveredVideo,
    PrivateViewingRecord,
    QueryRule,
    TimestampReference,
    Topic,
)


class TestTopicValidation:
    def test_create_valid_topic(self):
        topic = Topic(
            id="t1", name="ChatGPT updates",
            intent="Show me new ChatGPT videos",
        )
        assert topic.name == "ChatGPT updates"
        assert topic.is_archived is False

    def test_name_stripped(self):
        topic = Topic(id="t1", name="  ChatGPT  ", intent="intent")
        assert topic.name == "ChatGPT"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            Topic(id="t1", name="", intent="intent")

    def test_empty_intent_rejected(self):
        with pytest.raises(ValidationError):
            Topic(id="t1", name="test", intent="")


class TestQueryRuleValidation:
    def test_create_valid_rule(self):
        rule = QueryRule(
            id="r1", topic_id="t1",
            primary_query="ChatGPT update",
        )
        assert rule.primary_query == "ChatGPT update"
        assert rule.default_sort == DefaultSort.NEWEST
        assert rule.shorts_preference == ShortsPreference.INCLUDE

    def test_excluded_terms_stripped(self):
        rule = QueryRule(
            id="r1", topic_id="t1",
            primary_query="test",
            excluded_terms=["  reaction  ", "meme"],
        )
        assert rule.excluded_terms == ["reaction", "meme"]

    def test_duplicate_excluded_terms_rejected(self):
        with pytest.raises(ValidationError):
            QueryRule(
                id="r1", topic_id="t1",
                primary_query="test",
                excluded_terms=["reaction", "reaction"],
            )

    def test_date_window_validation(self):
        with pytest.raises(ValidationError):
            QueryRule(
                id="r1", topic_id="t1",
                primary_query="test",
                date_window_start="2026-07-10",
                date_window_end="2026-07-05",
            )

    def test_valid_date_window_accepted(self):
        rule = QueryRule(
            id="r1", topic_id="t1",
            primary_query="test",
            date_window_start="2026-07-01",
            date_window_end="2026-07-10",
        )
        assert rule.date_window_start == "2026-07-01"

    def test_invalid_date_format_rejected(self):
        with pytest.raises(ValidationError):
            QueryRule(
                id="r1", topic_id="t1",
                primary_query="test",
                date_window_start="07/01/2026",
            )


class TestDiscoveredVideoValidation:
    def test_valid_youtube_url(self):
        video = DiscoveredVideo(
            id="v1", provider="youtube",
            provider_video_id="dQw4w9WgXcQ",
            canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test Video",
            published_at="2026-07-15T10:00:00Z",
        )
        assert video.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_invalid_url_rejected(self):
        with pytest.raises(ValidationError):
            DiscoveredVideo(
                id="v1", provider="youtube",
                provider_video_id="dQw4w9WgXcQ",
                canonical_url="https://example.com/watch?v=test",
                title="Test",
                published_at="2026-07-15T10:00:00Z",
            )

    def test_bare_id_url_normalized(self):
        video = DiscoveredVideo(
            id="v1", provider="youtube",
            provider_video_id="dQw4w9WgXcQ",
            canonical_url="dQw4w9WgXcQ",
            title="Test",
            published_at="2026-07-15T10:00:00Z",
        )
        assert video.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_shorts_url_accepted(self):
        video = DiscoveredVideo(
            id="v1", provider="youtube",
            provider_video_id="dQw4w9WgXcQ",
            canonical_url="https://youtube.com/shorts/dQw4w9WgXcQ",
            title="Test",
            published_at="2026-07-15T10:00:00Z",
        )
        assert video.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_negative_duration_rejected(self):
        with pytest.raises(ValidationError):
            DiscoveredVideo(
                id="v1", provider="youtube",
                provider_video_id="dQw4w9WgXcQ",
                canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                title="Test",
                published_at="2026-07-15T10:00:00Z",
                duration_seconds=-10,
            )

    def test_invalid_tag_rejected(self):
        with pytest.raises(ValidationError):
            DiscoveredVideo(
                id="v1", provider="youtube",
                provider_video_id="dQw4w9WgXcQ",
                canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                title="Test",
                published_at="2026-07-15T10:00:00Z",
                tags=["valid", "1invalid"],
            )


class TestViewingRecordValidation:
    def test_default_state_unseen(self):
        record = PrivateViewingRecord(
            id="r1", topic_video_id="tv1",
        )
        assert record.viewing_state == ViewingState.UNSEEN

    def test_rating_range(self):
        record = PrivateViewingRecord(
            id="r1", topic_video_id="tv1", rating=3,
        )
        assert record.rating == 3

    def test_invalid_rating_rejected(self):
        with pytest.raises(ValidationError):
            PrivateViewingRecord(
                id="r1", topic_video_id="tv1", rating=6,
            )

    def test_opened_before_completed(self):
        with pytest.raises(ValidationError):
            PrivateViewingRecord(
                id="r1", topic_video_id="tv1",
                opened_date="2026-07-10",
                completed_date="2026-07-05",
            )

    def test_tags_deduplication_rejected(self):
        with pytest.raises(ValidationError):
            PrivateViewingRecord(
                id="r1", topic_video_id="tv1",
                tags=["ai", "ai"],
            )

    def test_invalid_tag_format_rejected(self):
        with pytest.raises(ValidationError):
            PrivateViewingRecord(
                id="r1", topic_video_id="tv1",
                tags=["@invalid"],
            )


class TestTimestampReference:
    def test_valid_timestamp(self):
        ts = TimestampReference(
            id="ts1", record_id="r1",
            timestamp_seconds=150, label="key point",
        )
        assert ts.timestamp_seconds == 150

    def test_negative_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            TimestampReference(
                id="ts1", record_id="r1",
                timestamp_seconds=-5,
            )


class TestProvenance:
    def test_video_provenance_youtube(self):
        video = DiscoveredVideo(
            id="v1", provider="youtube",
            provider_video_id="dQw4w9WgXcQ",
            canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test",
            published_at="2026-07-15T10:00:00Z",
        )
        assert video.provenance == Provenance.YOUTUBE

    def test_record_provenance_user(self):
        record = PrivateViewingRecord(id="r1", topic_video_id="tv1")
        assert record.provenance == Provenance.USER
