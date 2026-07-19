import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok_with_mock_defaults(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "status": "ok",
            "ai_provider": settings.ai_provider,
            "ai_model": settings.ai_model,
        }

    def test_health_response_shape(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "ai_provider" in data
        assert "ai_model" in data
        assert data["status"] == "ok"
        assert data["ai_provider"] == "mock"
        assert data["ai_model"] == "mock-personal-edition-v1"
