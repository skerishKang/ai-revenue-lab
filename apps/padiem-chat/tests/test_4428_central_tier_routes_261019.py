"""#4428 follow-up: central product/tier routes reach the product dispatch path."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sqlite3

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.central_model_route_d1 import D1CentralModelRouteStore
from app.central_model_route_runtime import (
    resolve_claw_tier_model_from_stores,
    resolve_tier_route,
)
from app.config import Settings
from app.main import create_app
from app.model_policy import (
    FREE_B14_MODEL_ID,
    request_tier_context,
    resolve_tier_policy,
)
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.model_assignment_policy import (
    CatalogModel, ModelChange, ModelPolicySnapshot, VerifiedModelAdminGrant,
)
from padiem_control_plane.model_tier_routes import (
    TierRoute, TierRouteChange, TierRouteSnapshot, effective_tier_route,
)

BASE = "https://chat.test"
MIGRATION = Path(__file__).parents[1] / "migrations" / "050_central_model_tier_routes.sql"
NOW = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
USER = "usr_" + "a" * 32
ALPHA = "google/alpha-safe"
BETA = "google/beta-safe"
OFFLINE = "google/offline-safe"
CATALOG = {
    ALPHA: CatalogModel(ALPHA, True, True, True, True, frozenset({"chat"})),
    BETA: CatalogModel(BETA, True, True, True, True, frozenset({"chat"})),
    OFFLINE: CatalogModel(OFFLINE, True, False, True, True, frozenset({"chat"})),
}


class Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        rows = self.db.conn.execute(self.sql, self.params).fetchall()
        return SimpleNamespace(results=[dict(row) for row in rows])

    async def all(self):
        rows = self.db.conn.execute(self.sql, self.params).fetchall()
        return [dict(row) for row in rows]


class FakeD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(MIGRATION.read_text(encoding="utf8"))
        self.batches: list[int] = []

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        self.batches.append(len(statements))
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                results.append(SimpleNamespace(results=[dict(row) for row in cursor.fetchall()]))
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


def grant(**overrides):
    values = dict(
        subject_id=USER, workspace_id="padiem-global", product=None,
        permissions=frozenset({"preview", "apply", "rollback"}),
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        authority_ref="canonical-google-d1-global-admin",
    )
    values.update(overrides)
    return VerifiedModelAdminGrant(**values)


def commit(store, changes, revision, *, nonce="a" * 32, operation="apply"):
    return asyncio.run(store.commit(
        grant=grant(), workspace_id="padiem-global", expected_revision=revision,
        nonce=nonce, operation=operation, changes=tuple(changes),
        catalog=CATALOG, now=NOW,
    ))


def test_contract_rejects_ambiguous_route_and_never_widens_to_unconfigured_models():
    with pytest.raises(ControlPlaneContractError):
        TierRouteChange("chat", "FREE", "set", ALPHA, ALPHA, True)
    with pytest.raises(ControlPlaneContractError):
        TierRouteChange("b14-router", "FREE", "set", ALPHA, None, True)
    with pytest.raises(ControlPlaneContractError):
        TierRouteChange("chat", "FREE", "reset", ALPHA, None, True)

    snapshot = TierRouteSnapshot("padiem-global", 2, (
        TierRoute("chat", "FREE", ALPHA, BETA, True),
        TierRoute("claw", "PLUS", ALPHA, None, False),
    ))
    chosen = effective_tier_route(
        snapshot, workspace_id="padiem-global", product="chat", tier="FREE",
        static_primary=BETA,
    )
    assert (chosen.ok, chosen.model_id, chosen.fallback_model_id, chosen.source) == (
        True, ALPHA, BETA, "central",
    )
    blocked = effective_tier_route(
        snapshot, workspace_id="padiem-global", product="chat", tier="FREE",
        static_primary=BETA, blocked_model_ids=frozenset({ALPHA}),
    )
    assert (blocked.ok, blocked.model_id) == (True, BETA)
    denied = effective_tier_route(
        snapshot, workspace_id="padiem-global", product="claw", tier="PLUS",
        static_primary=ALPHA,
    )
    assert (denied.ok, denied.reason) == (False, "central_route_disabled")
    # A different workspace cannot borrow another tenant's rows.
    other = effective_tier_route(
        snapshot, workspace_id="another", product="chat", tier="FREE",
        static_primary=BETA,
    )
    assert (other.ok, other.model_id, other.source) == (True, BETA, "static")


def test_d1_route_store_cas_nonce_audit_and_rollback_history():
    db = FakeD1()
    store = D1CentralModelRouteStore(db)
    first = commit(store, [TierRouteChange("chat", "FREE", "set", ALPHA, BETA, True)], 0)
    assert first.revision == 1
    assert first.lookup("chat", "FREE").primary_model_id == ALPHA
    assert db.batches == [7]  # state, CAS, nonce, delete, insert, history, audit

    with pytest.raises(ControlPlaneContractError) as stale:
        commit(store, [TierRouteChange("chat", "FREE", "set", BETA, None, True)],
               0, nonce="b" * 32)
    assert stale.value.code == "model_route_revision_conflict"

    second = commit(store, [TierRouteChange("chat", "FREE", "set", BETA, None, False)],
                    1, nonce="c" * 32)
    assert second.revision == 2
    assert second.lookup("chat", "FREE").enabled is False

    with pytest.raises(ControlPlaneContractError) as replay:
        commit(store, [TierRouteChange("chat", "FREE", "reset")],
               2, nonce="c" * 32)
    assert replay.value.code == "model_route_receipt_replayed"

    previous = asyncio.run(store.previous_revision("padiem-global", 1))
    assert previous.lookup("chat", "FREE").primary_model_id == ALPHA
    events = asyncio.run(store.audit("padiem-global"))
    assert [event["revision"] for event in events] == [2, 1]


def test_d1_route_store_rejects_unregistered_or_offline_models():
    store = D1CentralModelRouteStore(FakeD1())
    for model_id, code in (("google/not-registered", "model_route_unknown_model"),
                           (OFFLINE, "model_route_offline_model")):
        with pytest.raises(ControlPlaneContractError) as exc:
            commit(store, [TierRouteChange("chat", "FREE", "set", model_id, None, True)], 0)
        assert exc.value.code == code
    assert asyncio.run(store.snapshot("padiem-global")).revision == 0


class RouteStore:
    def __init__(self, snapshot):
        self.snapshot_value = snapshot

    async def snapshot(self, workspace_id):
        if isinstance(self.snapshot_value, Exception):
            raise self.snapshot_value
        return self.snapshot_value


class PolicyStore:
    def __init__(self, snapshot):
        self.snapshot_value = snapshot

    async def snapshot(self, workspace_id):
        return self.snapshot_value


def request_state(*, routes=None, policy=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        central_model_route_store=routes,
        central_model_policy_store=policy,
    )))


def test_runtime_uses_central_route_and_configured_fallback_only():
    routes = RouteStore(TierRouteSnapshot("padiem-global", 4, (
        TierRoute("chat", "FREE", ALPHA, BETA, True),
    )))
    resolution = asyncio.run(resolve_tier_route(
        request_state(routes=routes), product="chat", tier="FREE",
        static_primary=BETA, static_fallback=None,
    ))
    assert (resolution.ok, resolution.model_id, resolution.fallback_model_id) == (
        True, ALPHA, BETA,
    )

    policy = PolicyStore(ModelPolicySnapshot("padiem-global", 1, (
        ModelChange("central", "FREE", ALPHA, "block"),
    )))
    resolution = asyncio.run(resolve_tier_route(
        request_state(routes=routes, policy=policy), product="chat", tier="FREE",
        static_primary=BETA,
    ))
    assert (resolution.ok, resolution.model_id) == (True, BETA)

    disabled = RouteStore(TierRouteSnapshot("padiem-global", 5, (
        TierRoute("chat", "FREE", ALPHA, None, False),
    )))
    resolution = asyncio.run(resolve_tier_route(
        request_state(routes=disabled), product="chat", tier="FREE",
        static_primary=BETA,
    ))
    assert (resolution.ok, resolution.reason) == (False, "central_route_disabled")


def test_runtime_preserves_static_contract_when_ledger_is_absent_or_unreadable():
    static = asyncio.run(resolve_tier_route(
        request_state(), product="chat", tier="FREE",
        static_primary=BETA, static_fallback=ALPHA,
    ))
    assert (static.ok, static.model_id, static.source) == (True, BETA, "static")

    broken = asyncio.run(resolve_tier_route(
        request_state(routes=RouteStore(RuntimeError("no such table"))),
        product="chat", tier="FREE", static_primary=BETA,
    ))
    assert (broken.ok, broken.model_id, broken.source) == (True, BETA, "static")


def test_store_based_claw_resolver_serves_the_cron_automation_path():
    plus = RouteStore(TierRouteSnapshot("padiem-global", 1, (
        TierRoute("claw", "PLUS", ALPHA, BETA, True),
    )))
    resolution = asyncio.run(resolve_claw_tier_model_from_stores(plus, None, "plus"))
    assert (resolution.ok, resolution.model_id, resolution.fallback_model_id) == (
        True, ALPHA, BETA,
    )
    assert resolution.source == "central"

    # Without a central row the cron path keeps the historical static route.
    from padiem_control_plane.product_tier_routes import (
        ProductTierLabel,
        active_route_for,
    )

    absent = asyncio.run(resolve_claw_tier_model_from_stores(
        RouteStore(TierRouteSnapshot("padiem-global", 0, ())), None, "plus",
    ))
    static_plus = active_route_for(ProductTierLabel.PLUS)
    assert (absent.ok, absent.model_id, absent.source) == (
        True, static_plus.model_id, "static",
    )

    blocked = PolicyStore(ModelPolicySnapshot("padiem-global", 1, (
        ModelChange("claw", "PLUS", ALPHA, "block"),
    )))
    resolution = asyncio.run(resolve_claw_tier_model_from_stores(
        plus, blocked, "plus",
    ))
    assert (resolution.ok, resolution.model_id) == (True, BETA)

    with pytest.raises(ValueError):
        asyncio.run(resolve_claw_tier_model_from_stores(plus, None, "vip"))


def test_chat_model_policy_uses_only_the_request_scoped_central_override():
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("free", model_id=ALPHA):
        assert resolve_tier_policy(messages, "free").model_id == ALPHA
        assert resolve_tier_policy(messages, "plus").model_id != ALPHA
    assert resolve_tier_policy(messages, "free").model_id == FREE_B14_MODEL_ID


def test_b66_helpers_use_the_central_b66_route():
    from app.b66_grade_models import b66_grade_model_id_for_request

    routes = RouteStore(TierRouteSnapshot("padiem-global", 1, (
        TierRoute("b66", "FREE", ALPHA, BETA, True),
    )))
    assert asyncio.run(b66_grade_model_id_for_request(
        request_state(routes=routes), "free")) == ALPHA
    disabled = RouteStore(TierRouteSnapshot("padiem-global", 2, (
        TierRoute("b66", "FREE", ALPHA, None, False),
    )))
    assert asyncio.run(b66_grade_model_id_for_request(
        request_state(routes=disabled), "free")) is None


def test_claw_adapter_accepts_a_server_resolved_central_route():
    from kagent.p01_adapter import P01AdapterError, _agent_profile
    from padiem_control_plane.product_tier_routes import ProductTierLabel

    profile = _agent_profile(
        ProductTierLabel.FREE, central_route_model_id="google/central-free",
    )
    assert profile.model_policy["model"] == "google/central-free"
    assert profile.model_policy["product_tier"] == "free"

    with pytest.raises(P01AdapterError):
        _agent_profile(
            ProductTierLabel.FREE, selected_model_id="google/central-free",
            central_route_model_id="google/central-free",
        )
    with pytest.raises(P01AdapterError):
        _agent_profile(ProductTierLabel.FREE, selected_model_id="google/central-free")


class GlobalAdmin:
    def __init__(self, allowed=True):
        self.allowed = allowed

    async def is_global_model_admin(self, *, user_id):
        return self.allowed


class Resolver:
    async def list_selectable_models(self):
        return [{"model_id": ALPHA, "name": "Alpha"}, {"model_id": BETA, "name": "Beta"}]

    async def list_registered_models(self):
        return [
            {"model_id": ALPHA, "name": "Alpha", "provider_id": "google",
             "b14_enabled": True, "owner_excluded": False, "capabilities": ["chat"]},
            {"model_id": BETA, "name": "Beta", "provider_id": "google",
             "b14_enabled": True, "owner_excluded": False, "capabilities": ["chat"]},
            # Registered but absent from the selectable list => offline.
            {"model_id": OFFLINE, "name": "Offline", "provider_id": "google",
             "b14_enabled": True, "owner_excluded": False, "capabilities": ["chat"]},
        ]


def built_app(*, admin=True, store=None):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="4428-central-route-test-session-secret",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings=settings, history_store=SimpleNamespace(),
        central_model_admin_authorizer=GlobalAdmin(admin),
        central_model_route_store=store,
        central_model_policy_signing_key="a" * 64,
    )
    app.state.b14_model_choice_resolver = Resolver()
    return app, settings


def call(app, settings, method, path, body=None, *, owner=USER, origin=BASE):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if owner is not None:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, owner))
            # The autouse test transport fixture fills a missing Origin with the
            # reviewed browser origin; the marker keeps this assertion honest.
            headers = {"Origin": origin} if origin else {"x-test-no-origin": "1"}
            return await client.request(method, path, json=body, headers=headers)
    return asyncio.run(inner())


def test_admin_route_preview_apply_and_read_back_are_admin_and_origin_gated():
    store = D1CentralModelRouteStore(FakeD1())
    app, settings = built_app(store=store)
    body = {
        "product": "chat", "tier": "FREE", "action": "set",
        "primary_model_id": ALPHA, "fallback_model_id": BETA, "enabled": True,
    }
    assert call(app, settings, "POST", "/api/admin/models/route-preview",
                body, owner=None).status_code == 401
    assert call(app, settings, "POST", "/api/admin/models/route-preview",
                body, origin=None).status_code == 403

    preview = call(app, settings, "POST", "/api/admin/models/route-preview", body)
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["persisted"] is False and payload["runtime_enforced"] is True
    assert payload["diff"][0]["previous"] is None
    receipt = payload["confirmation_receipt"]

    applied = call(app, settings, "POST", "/api/admin/models/route-apply",
                   {"confirmation_receipt": receipt})
    assert applied.status_code == 200
    assert applied.json()["revision"] == 1
    assert applied.json()["runtime_enforced"] is True

    me = call(app, settings, "GET", "/api/admin/models/me")
    assert me.status_code == 200
    assert me.json()["routes_write_enabled"] is True

    replayed = call(app, settings, "POST", "/api/admin/models/route-apply",
                    {"confirmation_receipt": receipt})
    assert replayed.status_code == 409
    assert replayed.json()["error"]["code"] in {
        "model_route_revision_conflict", "model_route_receipt_replayed",
    }

    read = call(app, settings, "GET", "/api/admin/models/routes")
    assert read.status_code == 200
    assert read.json()["revision"] == 1
    assert read.json()["routes"][0]["primary_model_id"] == ALPHA

    snapshot = call(app, settings, "GET", "/api/admin/models/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["routes_runtime_enforced"] is True
    assert snapshot.json()["routes"]["revision"] == 1

    denied, denied_settings = built_app(admin=False, store=store)
    assert call(denied, denied_settings, "GET", "/api/admin/models/routes").status_code == 403


def test_admin_route_preview_rejects_offline_or_unregistered_model():
    app, settings = built_app(store=D1CentralModelRouteStore(FakeD1()))
    for model_id, code in (("google/not-registered", "model_route_unknown_model"),
                           (OFFLINE, "model_route_offline_model")):
        response = call(app, settings, "POST", "/api/admin/models/route-preview", {
            "product": "chat", "tier": "FREE", "action": "set",
            "primary_model_id": model_id, "fallback_model_id": None, "enabled": True,
        })
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code
