"""Regression coverage for Drive OAuth form encoding (#2206)."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx

from app.drive_port_httpx import HttpxDriveReadPort
from padiem_ai_core.drive_capability import DRIVE_BASE_URL, DRIVE_READONLY_SCOPE


def test_oauth_refresh_percent_encodes_reserved_credential_characters() -> None:
    token_request_bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            body = request.content.decode("utf-8")
            token_request_bodies.append(body)
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "expires_in": 3600,
                    "scope": DRIVE_READONLY_SCOPE,
                },
            )
        return httpx.Response(200, json={"files": []})

    credentials = {
        "client_id": "client+id@example.com",
        "client_secret": "secret&with=reserved+chars%",
        "refresh_token": "refresh/token?x=1&y=2+z",
    }
    port = HttpxDriveReadPort(
        **credentials,
        transport=httpx.MockTransport(handler),
    )

    asyncio.run(
        port.get_json(
            binding_ref="bind:1",
            actor_ref="actor:1",
            required_scopes=(DRIVE_READONLY_SCOPE,),
            base_url=DRIVE_BASE_URL,
            path="/files",
            query={},
            timeout_seconds=30,
            max_response_bytes=1_000_000,
        )
    )

    assert len(token_request_bodies) == 1
    parsed = parse_qs(token_request_bodies[0], keep_blank_values=True)
    assert parsed == {
        "client_id": [credentials["client_id"]],
        "client_secret": [credentials["client_secret"]],
        "refresh_token": [credentials["refresh_token"]],
        "grant_type": ["refresh_token"],
    }
