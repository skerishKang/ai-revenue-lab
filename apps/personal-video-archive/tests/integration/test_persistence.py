"""Integration tests for persistence and audit behavior."""

from __future__ import annotations

import pytest

from app.db import apply_migrations, get_connection
from app.domain.enums import SyncStatus, ViewingState
from app.domain.models import (
    DiscoveredVideo,
    PrivateViewingRecord,
    QueryRuleProposal,
    Topic,
)
from app.providers.fake_language_model import FakeLanguageModelProvider
from app.providers.fake_video_discovery import FakeVideoDiscoveryProvider
from app.repositories import (
    ProposalRepository,
    QuotaLedgerRepository,
    QueryRuleRepository,
    SyncRunRepository,
    TopicRepository,
    TopicVideoRepository,
    VideoRepository,
    ViewingRecordRepository,
)
from app.services import (
    DiscoveryService,
    RecordService,
    TopicService,
)


class TestPersistenceRoundTrip:
    def test_topic_persistence(self, conn):
        repo = TopicRepository(conn)
        topic = repo.create("Test Topic", "test intent")
        fetched = repo.get(topic.id)
        assert fetched is not None
        assert fetched.name == "Test Topic"
        assert fetched.intent == "test intent"

    def test_video_upsert(self, conn):
        repo = VideoRepository(conn)
        video = DiscoveredVideo(
            id="v1", provider="youtube",
            provider_video_id="dQw4w9WgXcQ",
            canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test Video",
            published_at="2026-07-15T10:00:00Z",
        )
        repo.upsert(video)
        fetched = repo.get("v1")
        assert fetched.title == "Test Video"

        # Update
        video2 = video.model_copy(update={"title": "Updated Title"})
        repo.upsert(video2)
        fetched = repo.get("v1")
        assert fetched.title == "Updated Title"

    def test_record_persistence(self, conn):
        topic_repo = TopicRepository(conn)
        rule_repo = QueryRuleRepository(conn)
        video_repo = VideoRepository(conn)
        tv_repo = TopicVideoRepository(conn)
        record_repo = ViewingRecordRepository(conn)

        topic = topic_repo.create("Test", "intent")
        rule = rule_repo.create_from_proposal(topic.id, QueryRuleProposal(
            primary_query="test",
        ))
        video = video_repo.upsert(DiscoveredVideo(
            id="v1", provider="youtube",
            provider_video_id="dQw4w9WgXcQ",
            canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test",
            published_at="2026-07-15T10:00:00Z",
        ))
        tv = tv_repo.link(topic.id, video.id)
        record = record_repo.create(tv.id)

        record_repo.update(record.id, viewing_state="completed", rating=5)
        fetched = record_repo.get(record.id)
        assert fetched.viewing_state == ViewingState.COMPLETED
        assert fetched.rating == 5


class TestSyncAudit:
    def test_sync_run_completed(self, created_topic, discovery_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        assert run.status == SyncStatus.COMPLETED
        assert run.completed_at is not None
        assert run.videos_found == len(feed)

    def test_sync_run_failed_on_error(self, repos, fake_llm):
        """Sync should record failure when provider raises."""
        class FailingProvider:
            def search_videos(self, rules, cursor=None):
                raise RuntimeError("Provider unavailable")
            def get_video_details(self, ids):
                return []
            def health_check(self):
                from app.domain.enums import ProviderHealth
                from app.providers import ProviderHealthCheck
                return ProviderHealthCheck("failing", ProviderHealth.UNAVAILABLE)

        topic = repos["topic"].create("Test", "intent")
        repos["rule"].create_from_proposal(topic.id, QueryRuleProposal(
            primary_query="test",
        ))

        discovery = DiscoveryService(
            repos["topic"], repos["rule"], repos["video"],
            repos["topic_video"], repos["sync"], repos["quota"],
            FailingProvider(), fake_llm,
        )

        with pytest.raises(RuntimeError):
            discovery.sync_topic(topic.id)

        runs = repos["sync"].list_for_topic(topic.id)
        assert len(runs) == 1
        assert runs[0].status == SyncStatus.FAILED
        assert "Provider unavailable" in runs[0].error_message

    def test_quota_ledger_entries(self, created_topic, discovery_service, repos):
        discovery_service.sync_topic(created_topic.id)
        total = repos["quota"].total_cost(created_topic.id)
        assert total >= 0


class TestMultipleTopicsSameVideo:
    def test_video_in_multiple_topics(self, repos, fake_discovery, fake_llm):
        """A single video can be associated with multiple topics."""
        topic1 = repos["topic"].create("Topic 1", "intent 1")
        topic2 = repos["topic"].create("Topic 2", "intent 2")

        repos["rule"].create_from_proposal(topic1.id, QueryRuleProposal(
            primary_query="shared topic",
        ))
        repos["rule"].create_from_proposal(topic2.id, QueryRuleProposal(
            primary_query="shared topic",
        ))

        video = repos["video"].upsert(DiscoveredVideo(
            id="v1", provider="youtube",
            provider_video_id="dQw4w9WgXcQ",
            canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Shared Video",
            published_at="2026-07-15T10:00:00Z",
        ))

        tv1 = repos["topic_video"].link(topic1.id, video.id)
        tv2 = repos["topic_video"].link(topic2.id, video.id)

        assert tv1.id != tv2.id
        assert tv1.topic_id == topic1.id
        assert tv2.topic_id == topic2.id
        assert tv1.video_id == tv2.video_id


class TestMigrationsIdempotent:
    def test_migrations_idempotent(self):
        """Running migrations twice should not fail."""
        from pathlib import Path
        conn = get_connection(":memory:")
        migrations_dir = str(
            Path(__file__).resolve().parent.parent.parent / "migrations"
        )
        apply_migrations(conn, migrations_dir)
        # Second run should be a no-op
        versions = apply_migrations(conn, migrations_dir)
        assert versions == []
        conn.close()

    def test_migrations_from_fresh_db(self):
        """Migrations should work from a completely fresh database."""
        from pathlib import Path
        conn = get_connection(":memory:")
        migrations_dir = str(
            Path(__file__).resolve().parent.parent.parent / "migrations"
        )
        versions = apply_migrations(conn, migrations_dir)
        assert len(versions) >= 1
        conn.close()
