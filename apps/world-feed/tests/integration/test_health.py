import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.factory import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["ai_provider"] == settings.ai_provider
        assert data["ai_model"] == settings.ai_model

    def test_health_reports_exact_provider_identity(self, client):
        resp = client.get("/health")
        data = resp.json()
        # The runtime provider route and model identity must be recorded exactly.
        assert data["ai_provider"] == "mock"
        assert data["ai_model"] == "mock-world-feed-v1"
