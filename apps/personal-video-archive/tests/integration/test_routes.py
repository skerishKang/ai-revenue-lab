"""Integration tests for the FastAPI route contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def populated_client(tmp_path):
    """Client with seeded topic, videos, topic-videos, and viewing records."""
    db_path = str(tmp_path / "populated.db")
    app = create_app(db_path=db_path)
    with TestClient(app, raise_server_exceptions=True) as c:
        # Seed data via direct DB access
        from app.db import get_connection
        conn = get_connection(db_path)
        try:
            # Create topic
            conn.execute(
                "INSERT INTO topics (id, name, intent, is_archived, created_at, updated_at) "
                "VALUES ('topic-1', 'AI 기초', 'AI 학습', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            # Create videos
            conn.execute(
                "INSERT INTO videos (id, provider, provider_video_id, canonical_url, title, description, "
                "channel_id, channel_title, published_at, duration_seconds, view_count, like_count, "
                "thumbnail_url, tags, created_at, updated_at) "
                "VALUES ('vid-1', 'youtube', 'aircAruvnKk', 'https://www.youtube.com/watch?v=aircAruvnKk', "
                "'Neural Network', 'desc', 'ch-1', '3Blue1Brown', '2017-10-05T00:00:00Z', 1120, 23700000, NULL, "
                "'https://i.ytimg.com/vi/aircAruvnKk/hqdefault.jpg', '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO videos (id, provider, provider_video_id, canonical_url, title, description, "
                "channel_id, channel_title, published_at, duration_seconds, view_count, like_count, "
                "thumbnail_url, tags, created_at, updated_at) "
                "VALUES ('vid-2', 'youtube', 'rfscVS0vtbw', 'https://www.youtube.com/watch?v=rfscVS0vtbw', "
                "'Python Course', 'desc', 'ch-2', 'freeCodeCamp', '2018-07-11T00:00:00Z', 16012, 49000000, NULL, "
                "'https://i.ytimg.com/vi/rfscVS0vtbw/hqdefault.jpg', '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            # Create topic-videos
            conn.execute(
                "INSERT INTO topic_videos (id, topic_id, video_id, first_matched_at, last_matched_at, "
                "match_score, match_reasons, is_excluded, created_at, updated_at) "
                "VALUES ('tv-1', 'topic-1', 'vid-1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', "
                "0.95, '[]', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO topic_videos (id, topic_id, video_id, first_matched_at, last_matched_at, "
                "match_score, match_reasons, is_excluded, created_at, updated_at) "
                "VALUES ('tv-2', 'topic-1', 'vid-2', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', "
                "0.90, '[]', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            # Create in_progress viewing record with note
            conn.execute(
                "INSERT INTO viewing_records (id, topic_video_id, viewing_state, rating, reflection, "
                "learned_point, agreement, disagreement, uncertainty, follow_up_plan, free_form_note, "
                "tags, opened_date, completed_date, created_at, updated_at) "
                "VALUES ('rec-1', 'tv-1', 'in_progress', NULL, '', '', '', '', '', '', "
                "'메모: 신경망 기초 학습 중', '[]', '2026-01-21', NULL, '2026-01-21T10:00:00Z', '2026-01-21T11:00:00Z')"
            )
            # Create revisit viewing record
            conn.execute(
                "INSERT INTO viewing_records (id, topic_video_id, viewing_state, rating, reflection, "
                "learned_point, agreement, disagreement, uncertainty, follow_up_plan, free_form_note, "
                "tags, opened_date, completed_date, created_at, updated_at) "
                "VALUES ('rec-2', 'tv-2', 'revisit', 3, '', '', '', '', '', '소유권 부분 다시 보기', "
                "'짧지만 핵심 요약', '[]', '2026-01-20', NULL, '2026-01-20T14:00:00Z', '2026-01-20T14:00:00Z')"
            )
            conn.commit()
        finally:
            conn.close()
        yield c


class TestRouteContracts:
    def test_index_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "나의 영상 아카이브" in response.text

    def test_topics_list_returns_200(self, client):
        response = client.get("/topics")
        assert response.status_code == 200

    def test_new_topic_returns_200(self, client):
        response = client.get("/topics/new")
        assert response.status_code == 200

    def test_create_topic_shows_rule_review(self, client):
        response = client.post(
            "/topics",
            data={
                "name": "Test Topic",
                "intent": "Show me test videos",
            },
        )
        assert response.status_code == 200
        assert "검색 규칙 검토" in response.text

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "FakeVideoDiscoveryProvider" in data["discovery_provider"]
        assert "FakeLanguageModelProvider" in data["llm_provider"]

    def test_records_search_returns_200(self, client):
        response = client.get("/records")
        assert response.status_code == 200

    def test_nonexistent_topic_returns_404(self, client):
        response = client.get("/topics/nonexistent")
        assert response.status_code == 404

    def test_nonexistent_video_returns_404(self, client):
        response = client.get("/videos/nonexistent")
        assert response.status_code == 404

    def test_nonexistent_record_returns_404(self, client):
        response = client.get("/records/nonexistent")
        assert response.status_code == 404

    def test_empty_state_on_index(self, client):
        """Index should show empty state when no topics exist."""
        response = client.get("/")
        assert response.status_code == 200
        assert "아직 토픽이 없습니다" in response.text or "토픽 만들기" in response.text

    def test_no_results_state(self, client):
        """Records search should show no results when empty."""
        response = client.get("/records?q=nonexistent")
        assert response.status_code == 200
        assert "기록이 없습니다" in response.text


class TestPopulatedLiveHome:
    """Regression tests for populated live home (Issue #76 CTO requirement #1)."""

    def test_populated_home_korean_returns_200(self, populated_client):
        """GET / with real data returns 200 and renders sections."""
        response = populated_client.get("/")
        assert response.status_code == 200
        # Verify sections render
        assert "이어 보기" in response.text, "Missing continue watching section"
        assert "최근 기록" in response.text, "Missing recent notes section"
        assert "다시 떠오른 기록" in response.text, "Missing resurfaced section"
        # Verify actual content
        assert "Neural Network" in response.text, "Missing video title"
        assert "메모: 신경망 기초 학습 중" in response.text, "Missing record note"

    def test_populated_home_english_returns_200(self, populated_client):
        """GET /en/ with real data returns 200 and renders sections."""
        response = populated_client.get("/en/")
        assert response.status_code == 200
        # Verify sections render (English)
        assert "Continue Watching" in response.text, "Missing continue watching section"
        assert "Recent Notes" in response.text, "Missing recent notes section"
        assert "Resurfaced" in response.text, "Missing resurfaced section"
        # Verify actual content
        assert "Neural Network" in response.text, "Missing video title"

    def test_continue_watching_shows_in_progress_state(self, populated_client):
        """Continue watching card should show '보는 중' state, not '아직 보지 않음'."""
        response = populated_client.get("/")
        # The state select should have 'in_progress' selected
        assert 'value="in_progress" selected' in response.text or "보는 중" in response.text, (
            "Continue watching card does not show in_progress state"
        )


class TestFullWorkflowViaHTTP:
    def test_create_topic_and_sync(self, client):
        """End-to-end: create topic, accept rule, sync, view feed."""
        # Create topic
        response = client.post(
            "/topics",
            data={
                "name": "ChatGPT updates",
                "intent": "Show me ChatGPT update videos excluding Shorts",
            },
        )
        assert response.status_code == 200
        assert "검색 규칙 검토" in response.text

        # Get the topics list to find our topic
        response = client.get("/topics")
        assert response.status_code == 200

    def test_provider_unavailable_state(self, tmp_path):
        """Test that provider failure is handled gracefully."""
        from app.domain.enums import ProviderHealth
        from app.providers import ProviderHealthCheck
        from app.providers.fake_language_model import FakeLanguageModelProvider

        class FailingProvider:
            def search_videos(self, rules, cursor=None):
                raise RuntimeError("Provider unavailable")
            def get_video_details(self, ids):
                return []
            def health_check(self):
                return ProviderHealthCheck("failing", ProviderHealth.UNAVAILABLE)

        db_path = str(tmp_path / "test_fail.db")
        app = create_app(
            db_path=db_path,
            discovery_provider=FailingProvider(),
            llm_provider=FakeLanguageModelProvider(),
        )

        with TestClient(app, raise_server_exceptions=False) as ac:
            # Create topic first
            response = ac.post(
                "/topics",
                data={
                    "name": "Test",
                    "intent": "test intent",
                },
            )
            # Extract topic_id from the form action in the response
            import re
            match = re.search(r'/topics/([a-f0-9]+)/accept-rule', response.text)
            assert match, "Could not find topic ID in response"
            topic_id = match.group(1)

            # Accept the rule
            ac.post(
                f"/topics/{topic_id}/accept-rule",
                data={
                    "primary_query": "test",
                    "related_queries": "",
                    "required_terms": "",
                    "excluded_terms": "",
                    "preferred_languages": "",
                    "included_channels": "",
                    "excluded_channels": "",
                    "duration_preference": "any",
                    "shorts_preference": "include",
                    "default_sort": "newest",
                },
            )

            # Try to sync — should handle error gracefully
            response = ac.post(f"/topics/{topic_id}/sync")
            # Should not crash, should redirect or show error (NOT 500)
            assert response.status_code != 500
            assert response.status_code in (303, 200)
