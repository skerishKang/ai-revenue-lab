"""The shipped COM2 build_app installs HMAC app ingress, without browser auth."""
import hashlib
import hmac
import json
import os
import time

from starlette.testclient import TestClient

from app.local_cpython import build_app


def test_host_composition_requires_app_signature_even_without_browser_auth(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(("PADIEM_", "PC_QUEUE_")):
            monkeypatch.delenv(name)
    settings = {
        "PADIEM_CHAT_CPYTHON_HOST": "1",
        "PADIEM_CHAT_RUNTIME_MODE": "mock",
        "PADIEM_CHAT_AUTH_MODE": "password",
        "PADIEM_CHAT_SESSION_SECRET": "fixture-chat-session-0123456789abcdef",
        "PADIEM_CHAT_WEB_PROVIDER": "off",
        "PADIEM_CHAT_LIVE_ENABLED": "false",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.example.com",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
        "BOOKAI_COM2_AI_SECRET": "fixture-bookai-app-signature",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    app = build_app()
    payload = {
        "app_id": "b61",
        "agent": {"model_policy": {"model": "google/gemini-3.1-flash-lite", "max_retries": 0}, "max_tokens": 900},
        "context_permission_required": True, "context_permission": {},
    }
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    canonical = "\n".join(("POST", "/api/apps/ai", timestamp, "sub_app_bookai", hashlib.sha256(body).hexdigest()))
    headers = {
        "content-type": "application/json", "x-bookai-subject": "sub_app_bookai",
        "x-bookai-timestamp": timestamp,
        "x-bookai-signature": hmac.new(settings["BOOKAI_COM2_AI_SECRET"].encode(), canonical.encode(), hashlib.sha256).hexdigest(),
    }
    with TestClient(app) as client:
        unsigned = client.post("/api/apps/ai", content=body, headers={"content-type": "application/json", "x-bookai-subject": "sub_app_bookai"})
        assert unsigned.status_code == 401
        assert unsigned.json()["error"]["code"] == "invalid_app_signature"
        # No P01 is configured in this isolated host. A signed call reaches that
        # exact boundary; it cannot return a mock Chat/model answer.
        signed = client.post("/api/apps/ai", content=body, headers=headers)
        assert signed.status_code == 503
        assert signed.json()["error"]["code"] == "p01_not_configured"
        assert client.get("/api/apps/ai").status_code == 404
