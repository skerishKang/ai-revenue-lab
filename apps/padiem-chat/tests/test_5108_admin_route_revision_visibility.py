"""#5108 follow-up: applied revision visibility and the paid-lane bypass.

Complements tests/test_5108_admin_route_projection.py, which covers the free
lane projection. This file pins the two remaining gaps:

* the product model read path states the applied ledger revision that governs
  the grade, so an operator can tell an applied decision from the static
  declaration without opening the admin ledger;
* a stored per-grade route is authoritative for a paid grade too, so the model
  offered by the chooser and the model that actually runs cannot diverge.

Network-free: no provider call, no production mutation, and no model name is
hardcoded in the assertions - the expected model always comes from the applied
route row itself.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app import auth_routes
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.owner_model_preview_routes import claw_verified_model_choices
from padiem_control_plane.model_tier_routes import TierRoute, TierRouteSnapshot

BASE = "https://chat.example.test"
USER = "usr_" + "c" * 32
# Synthetic identifiers for the applied route and the surrounding catalog. They
# are never a real provider model and are never asserted as literals.
APPLIED = "vendor/applied-model"
SECONDARY = "vendor/secondary-model"
OTHER = "vendor/other-model"


class _RouteStore:
    """Minimal central route ledger read surface."""

    def __init__(self, snapshot):
        self._snapshot = snapshot

    async def snapshot(self, workspace_id):
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot


class _Catalog:
    """B14 owner-allowed, live-ready selectable subset."""

    def __init__(self, rows):
        self.rows = list(rows)

    async def list_selectable_models(self):
        return list(self.rows)


def _choice_client(monkeypatch, *, routes=None, rows=()):
    monkeypatch.setattr(auth_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(
        auth_routes, "current_user_id", lambda request: "usr_fixture",
    )
    app = Starlette(routes=[Route("/choices", claw_verified_model_choices)])
    app.state.b14_model_choice_resolver = _Catalog(rows)
    app.state.central_model_route_store = routes
    # Mock runtime: the member grade check has no live membership source here,
    # so the fixture account keeps the maximum verified grade.
    app.state.settings = SimpleNamespace(runtime_mode="mock")
    return TestClient(app)


def test_product_model_list_states_the_applied_ledger_revision(monkeypatch):
    """The chooser reports which applied revision governs the grade."""
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 7, (
        TierRoute("claw", "PLUS", APPLIED, SECONDARY, True),
    )))
    with _choice_client(monkeypatch, routes=routes, rows=[
        {"model_id": APPLIED, "name": "Applied"},
        {"model_id": SECONDARY, "name": "Secondary"},
        {"model_id": OTHER, "name": "Other"},
    ]) as client:
        response = client.get("/choices?tier=plus")
    assert response.status_code == 200
    body = response.json()
    assert body["route_source"] == "central"
    assert body["route_revision"] == 7
    assert [row["model_id"] for row in body["model_choices"]] == [APPLIED, SECONDARY]


def test_product_model_list_reports_no_revision_without_an_applied_route(monkeypatch):
    """A grade no stored row governs reports 0, never an unrelated revision."""
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 7, (
        TierRoute("chat", "PLUS", APPLIED, None, True),
    )))
    with _choice_client(monkeypatch, routes=routes, rows=[
        {"model_id": APPLIED, "name": "Applied"},
        {"model_id": OTHER, "name": "Other"},
    ]) as client:
        response = client.get("/choices?tier=free")
    assert response.status_code == 200
    body = response.json()
    assert body["route_source"] == "static"
    assert body["route_revision"] == 0


class _AuthStore:
    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id):
        return None


def _dispatch_client(adapter, *, routes, rows):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url=BASE,
        google_client_id="route-revision-test.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret="synthetic-secret-for-tests-only-not-real",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings=settings, history_store=_AuthStore(), claw_p01_adapter=adapter,
        central_model_route_store=routes,
    )
    app.state.b14_model_choice_resolver = _Catalog(rows)
    client = TestClient(app, base_url=BASE)
    client.cookies.set(
        SESSION_COOKIE, create_session_token(settings, USER),
        domain="chat.example.test", path="/",
    )
    return client


def _adapter():
    mock = MagicMock()
    mock.subject_identity_lane = False
    projection = MagicMock()
    projection.status.value = "completed"
    projection.run_id = "run_route_revision"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = "applied route answer"
    outcome.p01_run_id = "p01_route_revision"
    outcome.p01_event_count = 1
    mock.execute = AsyncMock(return_value=outcome)
    return mock


def test_paid_lane_explicit_choice_cannot_replace_the_applied_route():
    """A stored paid-grade row is authoritative for the explicit pick too."""
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 8, (
        TierRoute("claw", "PLUS", APPLIED, SECONDARY, True),
    )))
    rows = [
        {"model_id": APPLIED, "name": "Applied"},
        {"model_id": SECONDARY, "name": "Secondary"},
        {"model_id": OTHER, "name": "Other"},
    ]
    adapter = _adapter()
    with _dispatch_client(adapter, routes=routes, rows=rows) as client:
        replaced = client.post("/api/claw/general", json={
            "tier": "plus", "model_id": OTHER,
            "messages": [{"role": "user", "content": "안녕하세요"}],
        })
        applied = client.post("/api/claw/general", json={
            "tier": "plus", "model_id": APPLIED,
            "messages": [{"role": "user", "content": "안녕하세요"}],
        })
    assert replaced.status_code == 403
    assert replaced.json()["error"]["code"] == "model_not_available_for_tier"
    assert applied.status_code == 200
    assert adapter.execute.await_args.kwargs["central_route_model_id"] == APPLIED


def test_paid_lane_without_an_applied_route_keeps_the_explicit_choice():
    """Without a stored row the paid-grade explicit choice is unchanged."""
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 0, ()))
    rows = [
        {"model_id": APPLIED, "name": "Applied"},
        {"model_id": OTHER, "name": "Other"},
    ]
    adapter = _adapter()
    with _dispatch_client(adapter, routes=routes, rows=rows) as client:
        chosen = client.post("/api/claw/general", json={
            "tier": "plus", "model_id": OTHER,
            "messages": [{"role": "user", "content": "안녕하세요"}],
        })
    assert chosen.status_code == 200
    assert adapter.execute.await_args.kwargs["selected_model_id"] == OTHER
