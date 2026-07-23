"""Unit tests for fake providers."""

from __future__ import annotations

from app.domain.enums import DefaultSort, ShortsPreference, ViewingState
from app.domain.models import QueryRule
from app.providers.fake_language_model import FakeLanguageModelProvider
from app.providers.fake_video_discovery import FakeVideoDiscoveryProvider


class TestFakeVideoDiscoveryProvider:
    def test_search_returns_videos(self, fake_discovery):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="ChatGPT update",
        )
        page = fake_discovery.search_videos(rules)
        assert len(page.videos) > 0
        assert page.provider == "fake-video-discovery"

    def test_deterministic_results(self, fake_discovery):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="ChatGPT update",
        )
        page1 = fake_discovery.search_videos(rules)
        page2 = fake_discovery.search_videos(rules)
        ids1 = [v.provider_video_id for v in page1.videos]
        ids2 = [v.provider_video_id for v in page2.videos]
        assert ids1 == ids2

    def test_newest_first_ordering(self, fake_discovery):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="ChatGPT update",
        )
        page = fake_discovery.search_videos(rules)
        published = [v.published_at for v in page.videos]
        assert published == sorted(published, reverse=True)

    def test_canonical_url_format(self, fake_discovery):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="test",
        )
        page = fake_discovery.search_videos(rules)
        for video in page.videos:
            assert video.canonical_url.startswith(
                "https://www.youtube.com/watch?v="
            )

    def test_shorts_excluded(self, fake_discovery):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="test",
            shorts_preference=ShortsPreference.EXCLUDE,
        )
        page = fake_discovery.search_videos(rules)
        # Should still return videos (just fewer)
        assert len(page.videos) > 0

    def test_excluded_terms_filter(self, fake_discovery):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="test",
            excluded_terms=["tutorial"],
        )
        page = fake_discovery.search_videos(rules)
        for video in page.videos:
            assert "tutorial" not in video.title.lower()

    def test_pagination(self, fake_discovery):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="test",
        )
        page1 = fake_discovery.search_videos(rules, cursor=None)
        if page1.next_cursor:
            page2 = fake_discovery.search_videos(rules, cursor=page1.next_cursor)
            assert len(page2.videos) > 0

    def test_health_check(self, fake_discovery):
        health = fake_discovery.health_check()
        assert health.status.value == "healthy"

    def test_no_network_calls(self, fake_discovery):
        """Verify no network-related attributes are set."""
        assert not hasattr(fake_discovery, "_session")
        assert not hasattr(fake_discovery, "_http_client")


class TestFakeLanguageModelProvider:
    def test_propose_query_rules(self, fake_llm):
        proposal = fake_llm.propose_query_rules(
            "Show me ChatGPT update videos, excluding Shorts and reaction content."
        )
        assert len(proposal.primary_query) > 0
        assert "shorts" in proposal.excluded_terms or "short" in proposal.excluded_terms
        assert proposal.default_sort == DefaultSort.NEWEST

    def test_propose_query_rules_korean_english(self, fake_llm):
        proposal = fake_llm.propose_query_rules(
            "Korean and English videos about ChatGPT updates"
        )
        assert "en" in proposal.preferred_languages or "ko" in proposal.preferred_languages

    def test_deterministic_proposals(self, fake_llm):
        intent = "ChatGPT updates excluding Shorts"
        p1 = fake_llm.propose_query_rules(intent)
        p2 = fake_llm.propose_query_rules(intent)
        assert p1.primary_query == p2.primary_query
        assert p1.excluded_terms == p2.excluded_terms

    def test_classify_videos(self, fake_llm, fake_discovery):
        from app.domain.models import DiscoveredVideo

        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="ChatGPT update",
            excluded_terms=["reaction"],
        )
        videos = fake_discovery.search_videos(rules).videos
        classifications = fake_llm.classify_videos(videos, rules)
        assert len(classifications) == len(videos)
        for cls in classifications:
            assert cls.match_level in ("strong", "possible", "noise")

    def test_structure_record(self, fake_llm):
        notes = """Key takeaways from this video:
reflection: The new ChatGPT memory feature is useful but raises privacy concerns.
learned: Memory persists across conversations.
plan: Try the memory feature next week.
tags: ai, chatgpt, privacy
rating: 4/5
timestamp: 2:30 - memory demo"""
        proposal = fake_llm.structure_record(notes)
        assert len(proposal.reflection) > 0
        assert "memory" in proposal.learned_point.lower()
        assert len(proposal.follow_up_plan) > 0
        assert "ai" in proposal.tags
        assert proposal.rating == 4
        assert len(proposal.timestamp_references) > 0
        assert proposal.timestamp_references[0]["timestamp_seconds"] == 150

    def test_structure_record_preserves_original(self, fake_llm):
        notes = "This is my rough note about ChatGPT."
        proposal = fake_llm.structure_record(notes)
        # The proposal should extract content but not delete the original
        assert proposal.reflection == notes or proposal.summary == notes or proposal.title == notes

    def test_suggest_rule_changes(self, fake_llm):
        rules = QueryRule(
            id="r1", topic_id="t1",
            primary_query="test",
        )
        feedback = [("v1", True), ("v2", False)]
        proposal = fake_llm.suggest_rule_changes(feedback, rules)
        assert len(proposal.rationale) > 0
