"""Integration tests for the full topic-to-feed-to-record workflow."""

from __future__ import annotations

import pytest

from app.domain.enums import ViewingState
from app.domain.models import QueryRuleProposal


class TestTopicWorkflow:
    def test_create_topic_and_propose_rules(self, topic_service):
        topic, proposal = topic_service.create_topic(
            name="ChatGPT updates",
            intent="Show me ChatGPT update videos excluding Shorts",
        )
        assert topic.name == "ChatGPT updates"
        assert len(proposal.primary_query) > 0
        assert proposal.default_sort.value == "newest"

    def test_accept_rule_draft(self, topic_service):
        topic, proposal = topic_service.create_topic(
            name="Test", intent="test intent",
        )
        rule = topic_service.accept_rule_draft(topic.id, proposal)
        assert rule.topic_id == topic.id
        assert rule.is_active is True

    def test_previous_rule_deactivated(self, topic_service):
        topic, proposal = topic_service.create_topic(
            name="Test", intent="test intent",
        )
        rule1 = topic_service.accept_rule_draft(topic.id, proposal)

        # Create a second rule
        proposal2 = QueryRuleProposal(
            primary_query="updated query",
        )
        rule2 = topic_service.accept_rule_draft(topic.id, proposal2)

        # Re-fetch rule1 to check its current state
        rule1_fresh = topic_service._rules.get(rule1.id)
        assert rule1_fresh.is_active is False
        assert rule2.is_active is True


class TestDiscoveryWorkflow:
    def test_sync_creates_videos(self, created_topic, discovery_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        assert run.status.value == "completed"
        assert len(feed) > 0

    def test_deduplication(self, created_topic, discovery_service):
        """Running sync twice should not duplicate videos."""
        run1, feed1 = discovery_service.sync_topic(created_topic.id)
        count1 = len(feed1)

        run2, feed2 = discovery_service.sync_topic(created_topic.id)
        count2 = len(feed2)

        assert count1 == count2  # Same videos, no duplicates

    def test_newest_first_ordering(self, created_topic, discovery_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        published = [v.published_at for _, v in feed]
        assert published == sorted(published, reverse=True)

    def test_sync_audit_recorded(self, created_topic, discovery_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        assert run.videos_found > 0
        assert run.quota_cost >= 0

        # Verify sync run is persisted
        runs = repos["sync"].list_for_topic(created_topic.id)
        assert len(runs) == 1
        assert runs[0].id == run.id

    def test_quota_ledger_recorded(self, created_topic, discovery_service, repos):
        discovery_service.sync_topic(created_topic.id)
        total = repos["quota"].total_cost(created_topic.id)
        assert total >= 0


class TestViewingStateTransitions:
    def test_opened_does_not_imply_completed(
        self, created_topic, discovery_service, record_service, repos
    ):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]

        # Get or create record
        record = record_service.get_or_create_record(tv.id)
        assert record.viewing_state == ViewingState.UNSEEN

        # Mark as opened
        record_service.update_record(record.id, viewing_state="opened")
        record = repos["record"].get(record.id)
        assert record.viewing_state == ViewingState.OPENED
        assert record.viewing_state != ViewingState.COMPLETED

    def test_state_transitions(self, created_topic, discovery_service, record_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)

        # unseen -> opened
        record_service.update_record(record.id, viewing_state="opened")
        assert repos["record"].get(record.id).viewing_state == ViewingState.OPENED

        # opened -> completed
        record_service.update_record(record.id, viewing_state="completed")
        assert repos["record"].get(record.id).viewing_state == ViewingState.COMPLETED

        # completed -> revisit
        record_service.update_record(record.id, viewing_state="revisit")
        assert repos["record"].get(record.id).viewing_state == ViewingState.REVISIT

        # revisit -> irrelevant
        record_service.update_record(record.id, viewing_state="irrelevant")
        assert repos["record"].get(record.id).viewing_state == ViewingState.IRRELEVANT

    def test_opened_sets_opened_date(self, created_topic, discovery_service, record_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)

        record_service.update_record(record.id, viewing_state="opened")
        record = repos["record"].get(record.id)
        assert record.opened_date is not None

    def test_completed_sets_completed_date(self, created_topic, discovery_service, record_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)

        record_service.update_record(record.id, viewing_state="completed")
        record = repos["record"].get(record.id)
        assert record.completed_date is not None


class TestCanonicalUrl:
    def test_canonical_url_format(self, created_topic, discovery_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        for _, video in feed:
            assert video.canonical_url.startswith("https://www.youtube.com/watch?v=")
            assert len(video.canonical_url) == len("https://www.youtube.com/watch?v=") + 11

    def test_no_short_or_embed_urls(self, created_topic, discovery_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        for _, video in feed:
            assert "youtube.com/shorts/" not in video.canonical_url
            assert "youtu.be/" not in video.canonical_url
            assert "embed" not in video.canonical_url


class TestProvenanceSeparation:
    def test_video_is_youtube_provenance(self, created_topic, discovery_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        for _, video in feed:
            assert video.provenance.value == "youtube"

    def test_topic_video_is_application_provenance(self, created_topic, discovery_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        for tv, _ in feed:
            assert tv.provenance.value == "application"

    def test_record_is_user_provenance(self, created_topic, discovery_service, record_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)
        assert record.provenance.value == "user"


class TestRecordWorkflow:
    def test_create_and_update_record(self, created_topic, discovery_service, record_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]

        record = record_service.get_or_create_record(tv.id)
        record_service.update_record(
            record.id,
            viewing_state="completed",
            rating=5,
            reflection="Great video!",
            follow_up_plan="Try this feature",
            tags=["ai", "chatgpt"],
        )

        updated = repos["record"].get(record.id)
        assert updated.viewing_state == ViewingState.COMPLETED
        assert updated.rating == 5
        assert updated.reflection == "Great video!"
        assert updated.follow_up_plan == "Try this feature"
        assert "ai" in updated.tags

    def test_search_records(self, created_topic, discovery_service, record_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)
        record_service.update_record(
            record.id,
            free_form_note="Important note about ChatGPT",
            tags=["ai", "important"],
        )

        results = record_service.search_records(
            topic_id=created_topic.id,
            query="ChatGPT",
        )
        assert len(results) == 1

    def test_search_by_tag(self, created_topic, discovery_service, record_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)
        record_service.update_record(
            record.id,
            tags=["ai", "important"],
        )

        results = record_service.search_records(
            topic_id=created_topic.id,
            tags=["important"],
        )
        assert len(results) == 1

    def test_search_by_state(self, created_topic, discovery_service, record_service):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)
        record_service.update_record(
            record.id,
            viewing_state="completed",
        )

        results = record_service.search_records(
            topic_id=created_topic.id,
            state="completed",
        )
        assert len(results) == 1

        results = record_service.search_records(
            topic_id=created_topic.id,
            state="unseen",
        )
        assert len(results) == 0


class TestStructureProposal:
    def test_propose_and_accept(self, created_topic, discovery_service, record_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)

        original_note = "reflection: Great video\nplan: Try this\nrating: 4"
        repos["record"].update(record.id, free_form_note=original_note)

        proposal = record_service.propose_structure(record.id, original_note)
        assert proposal.status.value == "pending"

        record_service.accept_structure_proposal(proposal.id)

        updated = repos["record"].get(record.id)
        assert updated.reflection == "Great video"
        assert updated.follow_up_plan == "Try this"
        assert updated.rating == 4
        # Original note preserved
        assert updated.free_form_note == original_note

    def test_reject_proposal(self, created_topic, discovery_service, record_service, repos):
        run, feed = discovery_service.sync_topic(created_topic.id)
        tv, video = feed[0]
        record = record_service.get_or_create_record(tv.id)

        proposal = record_service.propose_structure(record.id, "test notes")
        record_service.reject_structure_proposal(proposal.id)

        updated = repos["proposal"].get(proposal.id)
        assert updated.status.value == "rejected"
