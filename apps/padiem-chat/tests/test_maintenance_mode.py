"""Stage-3 write window: reads pass, mutations answer 503 `maintenance` (#5573)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.config import Settings
from app.local_cpython import build_app
from app.maintenance_mode import MAINTENANCE_CODE


@pytest.fixture()
def maintenance_client(tmp_path, monkeypatch):
    sentinel = tmp_path / "MAINTENANCE"
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8773")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    monkeypatch.setenv("PADIEM_CHAT_MAINTENANCE_SENTINEL", str(sentinel))
    app = build_app()
    with TestClient(app, headers={"Origin": "http://127.0.0.1:8773"}) as client:
        yield client, sentinel


def test_mutations_are_refused_only_while_the_sentinel_exists(maintenance_client):
    client, sentinel = maintenance_client

    # No sentinel: the same request reaches the app (mock stream succeeds).
    open_stream = client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
    assert open_stream.status_code == 200

    sentinel.write_text("maintenance\n", encoding="utf-8")
    refused = client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == MAINTENANCE_CODE
    assert refused.headers["retry-after"] == "120"
    assert "점검" in refused.json()["error"]["message"]

    # Reads keep working during the window.
    health = client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    status = client.get("/api/auth/status")
    assert status.status_code == 200

    sentinel.unlink()
    reopened = client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
    assert reopened.status_code == 200


def test_without_the_env_no_middleware_is_composed(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8773")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    monkeypatch.delenv("PADIEM_CHAT_MAINTENANCE_SENTINEL", raising=False)
    app = build_app()
    from app.maintenance_mode import MaintenanceModeMiddleware
    assert not isinstance(app, MaintenanceModeMiddleware)
