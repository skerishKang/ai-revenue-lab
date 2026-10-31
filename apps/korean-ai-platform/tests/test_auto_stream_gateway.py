"""The staged b14/auto stream preview is retired (B7): route and module are gone."""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.factory import create_app


AUTO_STREAM_URL = "/api/pilot/v1/chat/completions/auto-stream-preview"
AUTO = {"model": "b14/auto", "messages": [{"role": "user", "content": "synthetic"}]}


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_auto_stream_preview_route_is_gone(client):
    assert client.post(AUTO_STREAM_URL, json={**AUTO, "stream": True}).status_code == 404
    assert client.get(AUTO_STREAM_URL).status_code == 404


def test_auto_stream_gateway_module_does_not_exist():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "app" / "pilot" / "auto_stream_gateway.py").exists()
    with pytest.raises(ModuleNotFoundError):
        import app.pilot.auto_stream_gateway  # noqa: F401
