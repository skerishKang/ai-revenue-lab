"""The /health answer carries no configuration detail for the public lane.

The bounded public body is ``{"status": "ok", "app": "padiem-chat"}``. The
readiness detail stays with the machine's own view — direct loopback callers
(the local QA and monitor lanes), the in-process test harness and a signed-in
admin — and never with a request forwarded through the public edge (the front
marks every proxied request with forwarding headers).

The admin leg is proven against the gate decision itself: the session
machinery behind ``current_user_id`` has its own suites, so those tests patch
the resolver and pin the admin-store boundary of this gate.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app.config import Settings
from app.main import create_app


ORIGIN = "https://chat.example.test"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="health-gate-client.apps.googleusercontent.com",
        google_client_secret="health-gate-secret",
        session_secret="health-gate-session-secret-0123456789abcdef",
        session_max_age_seconds=3600,
    )


class _AuthReadyStore:
    async def get_user(self, user_id: str):
        return None

    async def list_projects(self, user_id: str):
        return []


def _app() -> object:
    return create_app(settings=_settings(), history_store=_AuthReadyStore())


def _assert_detail(body: dict) -> None:
    # The detail view keeps every readiness boolean.
    assert body["status"] == "ok"
    assert body["app"] == "padiem-chat"
    assert "runtime" in body
    assert "live_enabled" in body
    assert "auth_configured" in body


def _assert_minimal(body: dict) -> None:
    assert body == {"status": "ok", "app": "padiem-chat"}


def test_the_in_process_test_harness_reads_the_detail_view():
    with TestClient(_app(), base_url=ORIGIN) as client:
        response = client.get("/health")
    assert response.status_code == 200
    _assert_detail(response.json())


@pytest.mark.asyncio
async def test_a_direct_loopback_caller_reads_the_detail_view():
    # httpx's ASGI transport connects from 127.0.0.1 — the local QA lanes.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()),
                                 base_url=ORIGIN) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    _assert_detail(response.json())


def test_a_forwarded_request_answers_the_bounded_public_body():
    with TestClient(_app(), base_url=ORIGIN) as client:
        forwarded = client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"})
        real_ip = client.get("/health", headers={"X-Real-IP": "203.0.113.9"})
    _assert_minimal(forwarded.json())
    _assert_minimal(real_ip.json())


@pytest.mark.asyncio
async def test_a_forwarded_loopback_looking_request_answers_minimal():
    # The public edge lands on a loopback-reachable host with forwarding
    # headers attached: the headers, not the socket, decide the lane.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()),
                                 base_url=ORIGIN) as client:
        response = await client.get("/health",
                                    headers={"X-Forwarded-For": "203.0.113.9"})
    _assert_minimal(response.json())


@pytest.mark.asyncio
async def test_a_signed_in_admin_reads_the_detail_view_through_the_public_lane(monkeypatch):
    from app import auth_routes

    class _AdminStore:
        async def is_google_admin(self, uid):
            return uid == "usr_admin"

    monkeypatch.setattr(auth_routes, "current_user_id", lambda request: "usr_admin")
    app = _app()
    app.state.b66_member_admin_store = _AdminStore()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url=ORIGIN) as client:
        response = await client.get("/health",
                                    headers={"X-Forwarded-For": "203.0.113.9"})
    assert response.status_code == 200
    _assert_detail(response.json())


@pytest.mark.asyncio
async def test_a_signed_in_non_admin_through_the_public_lane_answers_minimal(monkeypatch):
    from app import auth_routes

    class _AdminStore:
        async def is_google_admin(self, uid):
            return False

    monkeypatch.setattr(auth_routes, "current_user_id", lambda request: "usr_member")
    app = _app()
    app.state.b66_member_admin_store = _AdminStore()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url=ORIGIN) as client:
        response = await client.get("/health",
                                    headers={"X-Forwarded-For": "203.0.113.9"})
    _assert_minimal(response.json())


@pytest.mark.asyncio
async def test_a_signed_in_user_without_an_admin_store_answers_minimal(monkeypatch):
    from app import auth_routes

    monkeypatch.setattr(auth_routes, "current_user_id", lambda request: "usr_member")
    app = _app()
    app.state.b66_member_admin_store = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url=ORIGIN) as client:
        response = await client.get("/health",
                                    headers={"X-Forwarded-For": "203.0.113.9"})
    _assert_minimal(response.json())
