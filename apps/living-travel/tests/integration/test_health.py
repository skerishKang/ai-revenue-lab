"""Integration tests for /health endpoint."""

import tempfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        database_url=str(tmp_path / "test.db"),
        environment="test",
    )
    return create_app(settings)


class TestHealth:
    @pytest.mark.anyio
    async def test_health_returns_ok(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
