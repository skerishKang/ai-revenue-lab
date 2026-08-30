from __future__ import annotations

import hashlib
import secrets
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test_candidate"))

from candidate_app import TEST_GUARD_HEADER, create_app  # noqa: E402

BASE_URL = "https://padiem-chat.charliekant.workers.dev"


def _guard() -> tuple[str, str]:
    raw = secrets.token_hex(32)
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


def test_candidate_runtime_exposes_api_routes_only() -> None:
    _, digest = _guard()
    app = create_app(None, digest)

    assert [getattr(route, "path", None) for route in app.routes] == [
        "/health",
        "/api/chat",
        "/api/chat/stream",
    ]
    assert all(route.__class__.__name__ != "Mount" for route in app.routes)


@pytest.mark.asyncio
async def test_candidate_root_is_not_served_from_local_filesystem() -> None:
    raw, digest = _guard()
    app = create_app(None, digest)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.get("/", headers={TEST_GUARD_HEADER: raw})

    assert response.status_code == 404
