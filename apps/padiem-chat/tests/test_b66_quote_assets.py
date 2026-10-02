"""Network-free tests for private account-bound B66 quote assets (#3402)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_assets import (
    B66QuoteAssetError,
    B66QuoteAssetMetadata,
    B66QuoteAssetStore,
    MAX_B66_QUOTE_ASSET_BYTES,
)
from app.config import Settings

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
WORKSPACE_A = f"owner:{USER_A}"
ASSET_ID = "b66asset_" + "c" * 32
PNG = b"\x89PNG\r\n\x1a\nprivate-logo"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="asset.apps.googleusercontent.com",
        google_client_secret="asset-google-secret",
        session_secret="asset-session-secret-not-real-0000",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


def _metadata(*, asset_id=ASSET_ID, user_id=USER_A, workspace_id=WORKSPACE_A, body=PNG):
    import hashlib

    return B66QuoteAssetMetadata(
        asset_id=asset_id,
        user_id=user_id,
        workspace_id=workspace_id,
        asset_kind="logo",
        media_type="image/png",
        object_key=f"b66/quote-assets/{asset_id}.png",
        byte_length=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        status="approved",
        created_at="2026-10-02T00:00:00.000Z",
        updated_at="2026-10-02T00:00:00.000Z",
    )


class MemoryMetadata:
    def __init__(self):
        self.rows = {}
        self.fail_insert = False

    async def insert(self, metadata):
        if self.fail_insert:
            raise RuntimeError("synthetic d1 failure")
        self.rows[(metadata.user_id, metadata.workspace_id, metadata.asset_id)] = metadata

    async def get_active(self, *, asset_id, user_id, workspace_id):
        return self.rows.get((user_id, workspace_id, asset_id))


class R2Object:
    def __init__(self, body):
        self.body = body


class MemoryR2:
    def __init__(self):
        self.objects = {}
        self.put_calls = []
        self.delete_calls = []

    async def put(self, key, body, **kwargs):
        self.put_calls.append((key, bytes(body), kwargs))
        self.objects[key] = bytes(body)

    async def get(self, key):
        body = self.objects.get(key)
        return None if body is None else R2Object(body)

    async def delete(self, key):
        self.delete_calls.append(key)
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_private_asset_round_trip_is_owner_workspace_scoped():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66QuoteAssetStore(metadata, r2)

    saved = await store.put_approved_asset(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        asset_kind="logo",
        media_type="image/png",
        body=PNG,
    )
    assert saved.asset_id.startswith("b66asset_")
    assert saved.object_key.startswith("b66/quote-assets/")
    assert "usr_" not in saved.object_key
    assert r2.put_calls[0][2]["httpMetadata"]["contentType"] == "image/png"

    own = await store.get_for_owner(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        asset_id=saved.asset_id,
    )
    assert own is not None
    assert own[1] == PNG

    foreign = await store.get_for_owner(
        user_id=USER_B,
        workspace_id=f"owner:{USER_B}",
        asset_id=saved.asset_id,
    )
    assert foreign is None


@pytest.mark.asyncio
async def test_asset_bounds_and_magic_fail_before_r2_write():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66QuoteAssetStore(metadata, r2)

    with pytest.raises(B66QuoteAssetError, match="media type"):
        await store.put_approved_asset(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            asset_kind="logo",
            media_type="image/png",
            body=b"not-a-png",
        )

    with pytest.raises(B66QuoteAssetError, match="size"):
        await store.put_approved_asset(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            asset_kind="stamp",
            media_type="image/png",
            body=b"\x89PNG\r\n\x1a\n" + b"x" * MAX_B66_QUOTE_ASSET_BYTES,
        )
    assert r2.put_calls == []


@pytest.mark.asyncio
async def test_metadata_failure_cleans_private_r2_object():
    metadata = MemoryMetadata()
    metadata.fail_insert = True
    r2 = MemoryR2()
    store = B66QuoteAssetStore(metadata, r2)

    with pytest.raises(B66QuoteAssetError, match="storage failed"):
        await store.put_approved_asset(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            asset_kind="stamp",
            media_type="image/png",
            body=PNG,
        )
    assert len(r2.put_calls) == 1
    key = r2.put_calls[0][0]
    assert key in r2.delete_calls
    assert key not in r2.objects


class RouteStore:
    def __init__(self):
        self.calls = []

    async def get_for_owner(self, *, user_id, workspace_id, asset_id):
        self.calls.append((user_id, workspace_id, asset_id))
        if user_id != USER_A or workspace_id != WORKSPACE_A or asset_id != ASSET_ID:
            return None
        return _metadata(), PNG


def _client(*, user_id=USER_A, signed_in=True, store=None):
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_quote_asset_store=store or RouteStore(),
    )
    client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id),
            domain="chat.example.test",
            path="/",
        )
    return client


def test_asset_route_requires_login_and_hides_foreign_assets():
    store = RouteStore()
    anonymous = _client(store=store, signed_in=False)
    assert anonymous.get(f"/api/b66/assets/{ASSET_ID}").status_code == 401
    assert store.calls == []

    owner = _client(store=store)
    response = owner.get(f"/api/b66/assets/{ASSET_ID}")
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"].startswith("private, no-store")
    assert response.headers["x-content-type-options"] == "nosniff"

    other = _client(user_id=USER_B, store=store)
    denied = other.get(f"/api/b66/assets/{ASSET_ID}")
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "quote_asset_not_found"


def test_asset_route_rejects_malformed_id_before_store_call():
    store = RouteStore()
    client = _client(store=store)
    response = client.get("/api/b66/assets/not-an-asset")
    assert response.status_code == 400
    assert store.calls == []


def test_migration_022_stores_metadata_only():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "022_b66_quote_asset.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b66_quote_asset" in migration
    assert "user_id TEXT NOT NULL REFERENCES users(id)" in migration
    assert "workspace_id TEXT NOT NULL" in migration
    assert "object_key TEXT NOT NULL UNIQUE" in migration
    assert "262144" in migration
    lowered = migration.lower()
    for forbidden in (" blob", "base64", "asset_bytes", "image_bytes", "data_url"):
        assert forbidden not in lowered


def test_asset_route_is_registered_but_no_public_upload_route_exists():
    app = create_app(
        settings=Settings.from_values(runtime_mode="mock", auth_mode="off", live_enabled="false")
    )
    matching = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/b66/assets/{asset_id}"
    ]
    assert len(matching) == 1
    assert matching[0].methods == {"GET", "HEAD"}
