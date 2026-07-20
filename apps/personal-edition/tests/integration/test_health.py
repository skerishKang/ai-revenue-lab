import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.config import Settings, settings
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
            "actual_provider": "mockprovider",
            "actual_model": settings.ai_model,
        }

    def test_health_response_shape(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "ai_provider" in data
        assert "ai_model" in data
        assert "actual_provider" in data
        assert "actual_model" in data
        assert data["status"] == "ok"
        assert data["ai_provider"] == "mock"
        assert data["ai_model"] == "mock-personal-edition-v1"
        assert data["actual_provider"] == "mockprovider"
        assert data["actual_model"] == "mock-personal-edition-v1"


class TestSettingsValidation:
    def test_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            Settings(ai_timeout_seconds=0)

    def test_timeout_negative_rejected(self):
        with pytest.raises(ValidationError):
            Settings(ai_timeout_seconds=-5)
