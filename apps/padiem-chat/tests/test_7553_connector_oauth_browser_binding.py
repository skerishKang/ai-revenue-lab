"""#7553 — Chat binds a Google connection start to the requesting browser.

The start answer sets a one-time cookie for the OAuth callback path and sends
only its SHA-256 to the OAuth edge with the private connect ticket.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import httpx
import pytest

from app.auth import SESSION_COOKIE
from test_google_connector_ticket_bridge import (
    NOW,
    FakeControlPlaneBinding,
    app_fixture,
    cookie_for,
)

COOKIE = "padiem_google_oauth_bind"


@pytest.mark.asyncio
async def test_start_sets_the_callback_cookie_and_sends_only_its_digest():
    binding = FakeControlPlaneBinding()
    sent: list[dict] = []

    async def oauth_edge(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "authorization": {
                    "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=t",
                    "connector_id": "gmail",
                    "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
                },
            },
        )

    app, history, _, _, _ = app_fixture(binding=binding, auth_transport=httpx.MockTransport(oauth_edge))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test", path="/")
        response = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": "https://chat.example.test"},
            json={"connector_id": "gmail", "begin_oauth": True},
        )

    assert response.status_code == 200, response.text
    headers = [h for h in response.headers.get_list("set-cookie") if h.startswith(COOKIE + "=")]
    assert len(headers) == 1
    header = headers[0]
    value = header.split(";", 1)[0].split("=", 1)[1]
    assert len(value) >= 32
    lowered = header.lower()
    for attribute in ("domain=padiem.net", "path=/v1/google/callback", "httponly", "secure", "samesite=lax", "max-age=600"):
        assert attribute in lowered, attribute
    assert sent == [{
        "connect_ticket": binding.ticket,
        "browser_binding_digest": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }]
    assert value not in response.text
