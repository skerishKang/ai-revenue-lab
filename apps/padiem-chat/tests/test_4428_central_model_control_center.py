"""#4428 Central model control center: global role isolation and safe preview."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app

BASE = "https://chat.test"


class GlobalAdmin:
    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.calls: list[str] = []

    async def is_global_model_admin(self, *, user_id: str):
        self.calls.append(user_id)
        return self.allowed


class Catalog:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [
            {"model_id": "google/gemini-safe", "name": "Gemini 테스트"},
            {"model_id": "google/gemma-safe", "name": "Gemma 테스트"},
        ]

    async def list_selectable_models(self):
        return self.rows


class B66Store:
    async def model_policy(self):
        return {
            "revision": 7, "active": True,
            "tiers": {
                "FREE": ["google/gemini-safe"], "PLUS": ["google/gemini-safe"],
                "PRO": ["google/gemma-safe"], "MAX": [],
            },
            "disabled_models": ["google/gemma-safe"],
        }


def built_app(*, admin=None, resolver=None, store=None):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="4428-central-model-center-test-session-secret",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings=settings, history_store=SimpleNamespace(),
        central_model_admin_authorizer=admin,
    )
    app.state.b14_model_choice_resolver = resolver if resolver is not None else Catalog()
    app.state.b66_member_admin_store = store
    return app, settings


def request(app, settings, path, *, owner="usr_4428_central", body=None, content_type=None, method="GET", query=None):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if owner is not None:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, owner))
            headers = {"Content-Type": content_type} if content_type else {}
            return await client.request(
                method, path, params=query, json=body if content_type is None else None,
                content=body if content_type is not None else None, headers=headers,
            )
    return asyncio.run(inner())


@pytest.mark.parametrize("endpoint,method", [
    ("/api/admin/models/me", "GET"),
    ("/api/admin/models/snapshot", "GET"),
    ("/api/admin/models/preview", "POST"),
])
def test_anonymous_cannot_read_any_admin_model_endpoint(endpoint, method):
    app, settings = built_app(admin=GlobalAdmin())
    response = request(app, settings, endpoint, owner=None, method=method)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_unconfigured_global_role_default_denies_even_with_b66_store():
    app, settings = built_app(store=B66Store())
    response = request(app, settings, "/api/admin/models/snapshot")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "central_admin_not_configured"


def test_b66_scoped_admin_is_not_global_admin():
    policy_admin = GlobalAdmin(allowed=False)
    app, settings = built_app(admin=policy_admin, store=B66Store())
    assert request(app, settings, "/api/admin/models/snapshot").status_code == 403
    assert request(app, settings, "/api/admin/models/preview", method="POST").status_code == 403
    assert len(policy_admin.calls) == 2


def test_authorized_model_snapshot_uses_actual_b14_subset_and_b66_d1_policy():
    app, settings = built_app(admin=GlobalAdmin(), store=B66Store())
    result = request(app, settings, "/api/admin/models/snapshot")
    assert result.status_code == 200
    assert result.headers["cache-control"].startswith("private, no-store")
    data = result.json()
    assert data["write_enabled"] is False and data["mode"] == "read_only"
    assert data["b14"]["complete_registration_inventory"] is False
    assert [m["model_id"] for m in data["b14"]["models"]] == [
        "google/gemma-safe", "google/gemini-safe",
    ]
    assert data["products"]["b66"]["status"] == "connected"
    assert data["products"]["b66"]["revision"] == 7
    assert data["products"]["b66"]["disabled_models"] == ["google/gemma-safe"]
    assert data["products"]["central"]["status"] == "not_wired"
    assert data["products"]["chat"]["status"] == "not_wired"
    assert "model_api_key" not in result.text


def test_missing_b66_store_is_not_misreported_as_connected():
    app, settings = built_app(admin=GlobalAdmin())
    response = request(app, settings, "/api/admin/models/snapshot")
    assert response.status_code == 200
    assert response.json()["products"]["b66"]["status"] == "unavailable"


@pytest.mark.parametrize("rows", [
    [{"model_id": "google/safe", "name": "X"}, {"model_id": "google/safe", "name": "X"}],
    [{"model_id": "google/safe?token=secret", "name": "X"}],
    [{"model_id": "google/safe", "name": "X\u0000secret"}],
    [{"model_id": "google/safe", "name": ""}],
    ["not a record"],
    [None],
])
def test_bad_catalog_is_fail_closed(rows):
    app, settings = built_app(admin=GlobalAdmin(), resolver=Catalog(rows))
    response = request(app, settings, "/api/admin/models/snapshot")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "b14_catalog_unavailable"


def test_query_cannot_choose_tenant_model_or_product():
    app, settings = built_app(admin=GlobalAdmin())
    response = request(app, settings, "/api/admin/models/snapshot", query={"user_id": "foreign"})
    assert response.status_code == 400


def test_exact_model_batch_preview_is_non_mutating():
    app, settings = built_app(admin=GlobalAdmin(), store=B66Store())
    before = request(app, settings, "/api/admin/models/snapshot").json()
    response = request(app, settings, "/api/admin/models/preview", method="POST", body={
        "model_id": "google/gemini-safe",
        "targets": [
            {"product_id": "central", "tier": "PLUS", "action": "allow"},
            {"product_id": "chat", "tier": "PLUS", "action": "allow"},
            {"product_id": "b66", "tier": "PRO", "action": "block"},
        ],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "preview_only"
    assert data["applied"] is False and data["persisted"] is False
    assert data["dispatch_authorized"] is False
    assert data["targets"] == [
        {"product_id": "central", "tier": "PLUS", "action": "allow"},
        {"product_id": "chat", "tier": "PLUS", "action": "allow"},
        {"product_id": "b66", "tier": "PRO", "action": "block"},
    ]
    assert request(app, settings, "/api/admin/models/snapshot").json() == before


@pytest.mark.parametrize("body", [
    {"model_id": "hidden/model", "targets": [{"product_id":"chat","tier":"PLUS","action":"allow"}]},
])
def test_unready_model_cannot_be_staged(body):
    app, settings = built_app(admin=GlobalAdmin())
    result = request(app, settings, "/api/admin/models/preview", method="POST", body=body)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "model_not_live_ready"


@pytest.mark.parametrize("targets", [
    [{"product_id": "chat", "tier": "PLUS", "action": "enable-everywhere"}],
    [{"product_id": "chat", "tier": "PLUS", "action": "allow", "owner":"other"}],
    [{"product_id": "chat", "tier": "PLUS", "action": "allow"}] * 2,
    [{"product_id": "bogus", "tier": "PLUS", "action": "allow"}],
    [{"product_id": "chat", "tier": "ADMIN", "action": "allow"}],
    [],
    [None],
])
def test_invalid_preview_target_list_denied(targets):
    app, settings = built_app(admin=GlobalAdmin())
    result = request(app, settings, "/api/admin/models/preview", method="POST",
                     body={"model_id": "google/gemini-safe", "targets": targets})
    assert result.status_code == 400


def test_content_type_and_size_bounded():
    app, settings = built_app(admin=GlobalAdmin())
    assert request(
        app, settings, "/api/admin/models/preview", method="POST",
        body='{"model_id":"google/gemini-safe","targets":[]}',
        content_type="text/plain",
    ).status_code == 415
    assert request(
        app, settings, "/api/admin/models/preview", method="POST",
        body="x" * 9000, content_type="application/json",
    ).status_code == 400


def test_only_get_and_preview_post_no_apply_endpoints():
    app, _ = built_app()
    paths = {(r.path, tuple(sorted(r.methods))) for r in app.routes if r.path.startswith("/api/admin/models/")}
    assert paths == {
        ("/api/admin/models/me", ("GET", "HEAD")),
        ("/api/admin/models/snapshot", ("GET", "HEAD")),
        ("/api/admin/models/preview", ("POST",)),
    } or paths == {
        ("/api/admin/models/me", ("GET",)),
        ("/api/admin/models/snapshot", ("GET",)),
        ("/api/admin/models/preview", ("POST",)),
    }


def test_ui_is_independent_and_does_not_hide_a_mutating_submit():
    root = Path(__file__).parents[1] / "static"
    html = (root / "admin-models.html").read_text(encoding="utf-8")
    js = (root / "admin-models.js").read_text(encoding="utf-8")
    css = (root / "admin-models.css").read_text(encoding="utf-8")
    assert "모델 흐름을 한 곳에서 관리" in html
    assert 'id="targetGrid"' in html and 'id="tierSelect"' in html
    assert 'id="previewBtn"' in html
    assert "/api/admin/models/snapshot" in js
    assert "/api/admin/models/preview" in js
    assert "result.applied !== false" in js
    assert "/api/b66/admin/model-policy" not in js
    assert "localStorage" not in js
    assert "model_api_key" not in html + js + css
