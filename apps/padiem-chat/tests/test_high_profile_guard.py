from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.model_policy import (
    HIGH_B14_MODEL_ID,
    HIGH_CONTRIBUTOR_ACK_VERSION,
    LOW_B14_MODEL_ID,
    MEDIUM_B14_MODEL_ID,
)
from app.profile_guard import guard_app


BASE_PAYLOAD = {
    "messages": [{"role": "user", "content": "안녕하세요"}],
    "mode": "auto",
    "skill": "auto",
}


def _app():
    async def unexpected_network(request):
        raise AssertionError(f"mock profile guard made a network call: {request.url}")

    inner = create_app(
        Settings(runtime_mode="mock"),
        transport=httpx.MockTransport(unexpected_network),
    )
    return guard_app(inner)


async def _post(client: httpx.AsyncClient, payload=None, *, profile=None, ack=None):
    headers = {}
    if profile is not None:
        headers["X-Padiem-Model-Profile"] = profile
    if ack is not None:
        headers["X-Padiem-High-Contributor-Ack"] = ack
    return await client.post("/api/chat", json=payload or BASE_PAYLOAD, headers=headers)


@pytest.mark.asyncio
async def test_default_and_low_profiles_are_explicit_manual_routes_and_context_resets():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://test") as client:
        default = await _post(client)
        assert default.status_code == 200
        assert default.json()["route"]["model"] == MEDIUM_B14_MODEL_ID

        low = await _post(client, profile="low")
        assert low.status_code == 200
        assert low.json()["route"]["model"] == LOW_B14_MODEL_ID

        after = await _post(client)
        assert after.status_code == 200
        assert after.json()["route"]["model"] == MEDIUM_B14_MODEL_ID


@pytest.mark.asyncio
async def test_high_requires_exact_versioned_ack_and_routes_only_after_ack():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://test") as client:
        missing = await _post(client, profile="high")
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "high_contributor_ack_required"

        stale = await _post(client, profile="high", ack="contributor-v0")
        assert stale.status_code == 422
        assert stale.json()["error"]["code"] == "invalid_high_contributor_ack"

        accepted = await _post(client, profile="high", ack=HIGH_CONTRIBUTOR_ACK_VERSION)
        assert accepted.status_code == 200
        assert accepted.json()["route"]["model"] == HIGH_B14_MODEL_ID


@pytest.mark.asyncio
async def test_high_rejects_attachment_project_and_tool_before_dispatch():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://test") as client:
        cases = [
            {**BASE_PAYLOAD, "attachments": [{"type": "document", "name": "private.txt", "text": "private"}]},
            {**BASE_PAYLOAD, "project_id": "project-private"},
            {**BASE_PAYLOAD, "tool": "web_search", "tool_input": "private query"},
        ]
        for payload in cases:
            response = await _post(
                client,
                payload,
                profile="high",
                ack=HIGH_CONTRIBUTOR_ACK_VERSION,
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "high_reference_context_blocked"


@pytest.mark.asyncio
async def test_malformed_profile_or_unexpected_ack_fails_closed():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://test") as client:
        unknown = await _post(client, profile="ultra")
        assert unknown.status_code == 422
        assert unknown.json()["error"]["code"] == "unknown_profile"

        unexpected = await _post(client, profile="medium", ack=HIGH_CONTRIBUTOR_ACK_VERSION)
        assert unexpected.status_code == 422
        assert unexpected.json()["error"]["code"] == "unexpected_high_contributor_ack"
