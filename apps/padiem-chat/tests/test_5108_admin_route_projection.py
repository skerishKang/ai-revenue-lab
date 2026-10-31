"""#5108: the administrator's applied model route reaches the product model lists.

Central route Preview -> Apply -> stored revision -> Chat/Claw/B66 model-list
read -> the actually selectable model. Network-free: no provider call, no
production mutation, and no model name is hardcoded in the assertions - the
expected model is always derived from the shared product-tier declaration or
from the applied route row itself.
"""
from __future__ import annotations

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
from padiem_control_plane.product_tier_routes import (
    FREE_FALLBACK_B14_MODEL_ID,
    FREE_PRIMARY_B14_MODEL_ID,
)

BASE = "https://chat.example.test"
USER = "usr_" + "a" * 32
# Synthetic model identifiers for the applied route and the surrounding catalog.
# They are never a real provider model and are never asserted as literals.
APPLIED = "vendor/applied-model"
SECONDARY = "vendor/secondary-model"
UNRELATED = "vendor/unrelated-model"
OUTSIDE = "vendor/outside-grant-list"


class _RouteStore:
    """Minimal central route ledger read surface."""

    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.reads = 0

    async def snapshot(self, workspace_id):
        self.reads += 1
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot


class _Catalog:
    """B14 owner-allowed, live-ready selectable subset."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = 0

    async def list_selectable_models(self):
        self.calls += 1
        return list(self.rows)


class _MemberStore:
    """B66 product-local membership and per-grade grant policy."""

    def __init__(self, *, tier="free", model_ids=(), disabled=(), active=True,
                 admin=False):
        self.tier = tier
        self.model_ids = list(model_ids)
        self.disabled = list(disabled)
        self.active = active
        self.admin = admin

    async def is_google_admin(self, user_id):
        return self.admin

    async def runtime_access(self, user_id):
        return {
            "status": "approved", "tier": self.tier,
            "active_policy": self.active,
            "disabled_models": list(self.disabled),
            "model_ids": list(self.model_ids),
        }


def _claw_choice_client(monkeypatch, *, routes=None, rows=()):
    monkeypatch.setattr(auth_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(
        auth_routes, "current_user_id", lambda request: "usr_fixture",
    )
    app = Starlette(routes=[Route("/choices", claw_verified_model_choices)])
    app.state.b14_model_choice_resolver = _Catalog(rows)
    app.state.central_model_route_store = routes
    return TestClient(app)


def test_claw_model_list_shows_the_applied_central_route_not_the_static_lane(monkeypatch):
    """A stored Claw route replaces the static free lane in the model picker."""
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 4, (
        TierRoute("claw", "FREE", APPLIED, SECONDARY, True),
    )))
    with _claw_choice_client(monkeypatch, routes=routes, rows=[
        {"model_id": APPLIED, "name": "Applied"},
        {"model_id": SECONDARY, "name": "Secondary"},
        {"model_id": FREE_PRIMARY_B14_MODEL_ID, "name": "Static free"},
        {"model_id": FREE_FALLBACK_B14_MODEL_ID, "name": "Static fallback"},
        {"model_id": UNRELATED, "name": "Unrelated"},
    ]) as client:
        response = client.get("/choices?tier=free")
    assert response.status_code == 200
    body = response.json()
    assert body["route_source"] == "central"
    assert [row["model_id"] for row in body["model_choices"]] == [APPLIED, SECONDARY]
    # The replaced static lane is no longer offered to the customer.
    assert FREE_PRIMARY_B14_MODEL_ID not in {
        row["model_id"] for row in body["model_choices"]
    }


def test_claw_model_list_keeps_the_static_lane_without_an_applied_route(monkeypatch):
    """No stored row keeps the shared static contract; the ledger never widens it."""
    with _claw_choice_client(monkeypatch, rows=[
        {"model_id": FREE_PRIMARY_B14_MODEL_ID, "name": "Static free"},
        {"model_id": FREE_FALLBACK_B14_MODEL_ID, "name": "Static fallback"},
        {"model_id": UNRELATED, "name": "Unrelated"},
    ]) as client:
        response = client.get("/choices?tier=free")
    assert response.status_code == 200
    body = response.json()
    assert body["route_source"] == "static"
    assert {row["model_id"] for row in body["model_choices"]} == {
        FREE_PRIMARY_B14_MODEL_ID, FREE_FALLBACK_B14_MODEL_ID,
    }


def test_claw_model_list_fails_closed_on_an_unreadable_route_ledger(monkeypatch):
    """A ledger read failure keeps the historical static contract, not a wider set."""
    routes = _RouteStore(RuntimeError("no such table"))
    with _claw_choice_client(monkeypatch, routes=routes, rows=[
        {"model_id": FREE_PRIMARY_B14_MODEL_ID, "name": "Static free"},
        {"model_id": UNRELATED, "name": "Unrelated"},
    ]) as client:
        response = client.get("/choices?tier=free")
    assert response.status_code == 200
    body = response.json()
    assert body["route_source"] == "static"
    assert {row["model_id"] for row in body["model_choices"]} == {
        FREE_PRIMARY_B14_MODEL_ID,
    }


def test_claw_model_list_reports_a_disabled_applied_route_instead_of_falling_back(
    monkeypatch,
):
    """A disabled central grade is unavailable, never silently the old lane."""
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 5, (
        TierRoute("claw", "FREE", APPLIED, None, False),
    )))
    with _claw_choice_client(monkeypatch, routes=routes, rows=[
        {"model_id": APPLIED, "name": "Applied"},
        {"model_id": FREE_PRIMARY_B14_MODEL_ID, "name": "Static free"},
    ]) as client:
        response = client.get("/choices?tier=free")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "tier_unavailable"
    assert "model_choices" not in body


class _AuthStore:
    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id):
        return None


def _claw_dispatch_client(adapter, *, routes, rows):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url=BASE,
        google_client_id="route-projection-test.apps.googleusercontent.com",
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
    projection.run_id = "run_route_projection"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = "applied route answer"
    outcome.p01_run_id = "p01_route_projection"
    outcome.p01_event_count = 1
    mock.execute = AsyncMock(return_value=outcome)
    return mock


def test_claw_dispatch_uses_the_applied_route_and_refuses_the_replaced_model():
    """The applied route decides the selectable model; the old one is refused."""
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 6, (
        TierRoute("claw", "FREE", APPLIED, None, True),
    )))
    rows = [
        {"model_id": APPLIED, "name": "Applied"},
        {"model_id": FREE_PRIMARY_B14_MODEL_ID, "name": "Static free"},
    ]
    adapter = _adapter()
    with _claw_dispatch_client(adapter, routes=routes, rows=rows) as client:
        applied = client.post("/api/claw/general", json={
            "tier": "free", "model_id": APPLIED,
            "messages": [{"role": "user", "content": "안녕하세요"}],
        })
        replaced = client.post("/api/claw/general", json={
            "tier": "free", "model_id": FREE_PRIMARY_B14_MODEL_ID,
            "messages": [{"role": "user", "content": "안녕하세요"}],
        })
    assert applied.status_code == 200
    assert adapter.execute.await_args.kwargs["central_route_model_id"] == APPLIED
    assert replaced.status_code == 403
    assert replaced.json()["error"]["code"] == "model_not_available_for_tier"


class _QuoteStore:
    def __init__(self, user_id, saved_id, row):
        self.user_id = user_id
        self.saved_id = saved_id
        self.row = row

    async def get_skill(self, *, user_id, workspace_id, saved_skill_id):
        if user_id != self.user_id or saved_skill_id != self.saved_id:
            return None
        return self.row


class _QuoteInterpreter:
    def __init__(self):
        self.calls = []

    async def interpret(self, **kwargs):
        self.calls.append(kwargs)
        from app.b66_quote_conversation import B66QuoteConversationProjection

        return B66QuoteConversationProjection(
            recipient={"company": "테스트상사", "person": None,
                       "address": None, "email": None},
            quote_no=None, issue_date=None,
            items=({"name": "배관", "qty": 20, "unitPrice": 30000},),
            memo=None, tax_mode=None, missing=(),
        )


def _b66_client(*, routes, rows, member_store, saved_row, saved_id):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url=BASE,
        google_client_id="b66-route-projection.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret="synthetic-secret-for-tests-only-not-real",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings=settings, history_store=MagicMock(),
        b66_saved_quote_skill_store=_QuoteStore(USER, saved_id, saved_row),
        b66_quote_interpreter=_QuoteInterpreter(),
        central_model_route_store=routes,
    )
    app.state.b66_quote_model_resolver = _Catalog(rows)
    app.state.b66_member_admin_store = member_store
    app.state.b66_membership_enforced = True
    client = TestClient(app, base_url=BASE)
    client.cookies.set(
        SESSION_COOKIE, create_session_token(settings, USER),
        domain="chat.example.test", path="/",
    )
    return client


def _saved_row(saved_id):
    return {
        "saved_skill_id": saved_id,
        "workspace_id": f"owner:{USER}",
        "skill_id": "saved-skill-1",
        "skill_name": "우리 견적서",
        "skill_fingerprint": "d" * 64,
        "skill_version": 1,
        "status": "approved",
        "skill": {
            "schemaVersion": 1, "id": "saved-skill-1", "name": "우리 견적서",
            "fixedDefaults": {"sender": {"company": "테스트상사"}, "validDays": 30,
                              "taxMode": "EXCLUSIVE", "memo": ""},
            "variableSchema": {"recipient": True, "quoteNo": True, "issueDate": True,
                               "items": True, "memo": True, "taxMode": True},
            "internalTemplate": {"id": "template-private", "title": {"text": "견 적 서"}},
            "approval": {"status": "approved"},
            "fingerprint": "d" * 64,
            "rendererContract": "quote-template-renderer.v1",
            "calculationAuthority": "quote-core",
        },
    }


def test_b66_model_list_keeps_the_applied_grade_when_the_product_grant_list_excludes_it():
    """A central grade change is never silently dropped from the B66 picker."""
    saved_id = "b66skill_" + "c" * 32
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 7, (
        TierRoute("b66", "FREE", APPLIED, None, True),
    )))
    member = _MemberStore(tier="free", model_ids=[UNRELATED], disabled=[])
    with _b66_client(
        routes=routes,
        rows=[{"model_id": APPLIED, "name": "Applied"},
              {"model_id": SECONDARY, "name": "Secondary"},
              {"model_id": UNRELATED, "name": "Unrelated"},
              {"model_id": OUTSIDE, "name": "Outside"}],
        member_store=member, saved_row=_saved_row(saved_id), saved_id=saved_id,
    ) as client:
        response = client.get("/api/b66/quote/models")
    assert response.status_code == 200
    tiers = response.json()["tiers"]
    assert [row["tier"] for row in tiers] == ["free"]
    assert tiers[0]["model_id"] == APPLIED
    assert response.json()["default_tier"] == "free"
    # The product-local grant list still narrows the free-choice models.
    assert [row["model_id"] for row in response.json()["models"]] == [UNRELATED]


def test_b66_model_list_still_honours_the_global_model_off_list():
    """An explicit model OFF still removes the grade model from the picker."""
    saved_id = "b66skill_" + "c" * 32
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 8, (
        TierRoute("b66", "FREE", APPLIED, None, True),
    )))
    member = _MemberStore(tier="free", model_ids=[APPLIED], disabled=[APPLIED])
    with _b66_client(
        routes=routes,
        rows=[{"model_id": APPLIED, "name": "Applied"}],
        member_store=member, saved_row=_saved_row(saved_id), saved_id=saved_id,
    ) as client:
        response = client.get("/api/b66/quote/models")
    assert response.status_code == 200
    assert response.json()["tiers"] == []
    assert response.json()["default_tier"] is None


def test_b66_dispatch_uses_the_applied_grade_model_but_keeps_the_member_restriction():
    """The applied grade model dispatches; a member-chosen model outside the
    product grant list is still refused, and a higher grade stays refused."""
    saved_id = "b66skill_" + "c" * 32
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 9, (
        TierRoute("b66", "FREE", APPLIED, None, True),
        TierRoute("b66", "PLUS", SECONDARY, None, True),
    )))
    member = _MemberStore(tier="free", model_ids=[UNRELATED], disabled=[])
    with _b66_client(
        routes=routes,
        rows=[{"model_id": APPLIED, "name": "Applied"},
              {"model_id": SECONDARY, "name": "Secondary"},
              {"model_id": UNRELATED, "name": "Unrelated"},
              {"model_id": OUTSIDE, "name": "Outside"}],
        member_store=member, saved_row=_saved_row(saved_id), saved_id=saved_id,
    ) as client:
        applied = client.post("/api/b66/quote/interpret", json={
            "saved_skill_id": saved_id, "tier": "free",
            "message": "테스트 견적",
        })
        foreign = client.post("/api/b66/quote/interpret", json={
            "saved_skill_id": saved_id, "model_id": OUTSIDE,
            "message": "테스트 견적",
        })
        higher = client.post("/api/b66/quote/interpret", json={
            "saved_skill_id": saved_id, "tier": "plus",
            "message": "테스트 견적",
        })
    assert applied.status_code == 200
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "model_tier_forbidden"
    # Product grade separation is unchanged: a free member never reaches plus.
    assert higher.status_code == 403
    assert higher.json()["error"]["code"] == "tier_not_available"


def test_b66_administrator_lane_keeps_its_own_grant_restriction():
    """The administrator grade is not a centrally routed grade, so the product
    grant list still decides whether its model may be used."""
    saved_id = "b66skill_" + "c" * 32
    routes = _RouteStore(TierRouteSnapshot("padiem-global", 10, (
        TierRoute("b66", "FREE", APPLIED, None, True),
    )))
    member = _MemberStore(tier="max", model_ids=[UNRELATED], disabled=[], admin=True)
    with _b66_client(
        routes=routes,
        rows=[{"model_id": APPLIED, "name": "Applied"},
              {"model_id": UNRELATED, "name": "Unrelated"}],
        member_store=member, saved_row=_saved_row(saved_id), saved_id=saved_id,
    ) as client:
        response = client.post("/api/b66/quote/interpret", json={
            "saved_skill_id": saved_id, "tier": "admin",
            "message": "테스트 견적",
        })
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_tier_forbidden"


def test_admin_console_projects_the_route_ledger_into_the_placement_panel():
    """The console must not keep a fixed "not wired" label for a connected route."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "static" / "admin-models.js"
    ).read_text(encoding="utf-8")
    assert 'state.routeConnected' in source
    assert 'routeTile("chat"' in source
    assert 'routeTile("claw"' in source
    assert 'routeTile("b66"' in source
    # The runtime-enforced ledger is read from the server, never from a
    # browser-held or hardcoded model list.
    assert '"/api/admin/models/routes"' in source
    assert "localStorage" not in source
