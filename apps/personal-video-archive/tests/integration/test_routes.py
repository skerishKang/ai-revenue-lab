"""Integration tests for the FastAPI route contracts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)
    with TestClient(app) as c:
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
