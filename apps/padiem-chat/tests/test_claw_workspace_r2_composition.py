"""Worker-runtime composition tests for the Claw workspace R2 binding (#2266).

`PADIEM_WORKSPACE_FILES` must be resolved from trusted Worker bindings and
passed into `create_app` together with the existing D1 binding so that
`WorkspaceDocumentStore` is composed only when both exist. Every path here is
network-free: the doubles below are plain in-memory objects, and no browser or
caller input can influence binding selection.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.app_factory import create_app
from app.config import Settings
from app.worker_config import D1_BINDING_NAME, WORKSPACE_R2_BINDING_NAME
from app.workspace_storage import (
    D1ClawDocumentMetadataStore,
    WorkspaceDocumentStore,
    WorkspaceStorageAccessError,
)

NOW = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
TENANT = "tenant_0123456789abcdef0123456789abcdef"
OTHER_TENANT = "tenant_fedcba9876543210fedcba9876543210"


class _FakeStatement:
    def __init__(self, db: _FakeD1, sql: str) -> None:
        self._db = db
        self._sql = sql
        self._values: tuple[object, ...] = ()

    def bind(self, *values: object) -> _FakeStatement:
        self._values = values
        return self

    async def run(self) -> dict[str, object]:
        sql = self._sql
        if sql.startswith("INSERT INTO claw_document_metadata"):
            (document_id, tenant_id, object_key, filename, media_type,
             byte_length, created_at, expires_at) = self._values
            self._db.rows[document_id] = {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "object_key": object_key,
                "filename": filename,
                "media_type": media_type,
                "byte_length": byte_length,
                "created_at": created_at,
                "expires_at": expires_at,
            }
            return {"success": True}
        if sql.startswith("UPDATE claw_document_metadata SET deleted_at"):
            deleted_at, document_id = self._values
            row = self._db.rows.get(document_id)
            if row is not None:
                row["deleted_at"] = deleted_at
            return {"success": True}
        raise AssertionError(f"unexpected SQL: {sql!r}")

    async def first(self) -> dict[str, object] | None:
        (document_id,) = self._values
        row = self._db.rows.get(document_id)
        if row is None or row.get("deleted_at") is not None:
            return None
        return {k: v for k, v in row.items() if k != "deleted_at"}


class _FakeD1:
    """Minimal D1 binding double: prepare/bind/run/first only, no network."""

    def __init__(self) -> None:
        self.rows: dict[object, dict[str, object]] = {}

    def prepare(self, sql: str) -> _FakeStatement:
        return _FakeStatement(self, sql)


class _FakeR2Object:
    def __init__(self, body: bytes) -> None:
        self.body = body


class _FakeR2:
    """Minimal private-R2 binding double: put/get/delete only, no network."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, body: bytes, **kwargs: object) -> None:
        self.objects[key] = bytes(body)

    async def get(self, key: str) -> _FakeR2Object | None:
        body = self.objects.get(key)
        return None if body is None else _FakeR2Object(body)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def _settings() -> Settings:
    return Settings.from_values(runtime_mode="mock", live_enabled="false")


def test_workspace_r2_binding_name_is_canonical() -> None:
    assert WORKSPACE_R2_BINDING_NAME == "PADIEM_WORKSPACE_FILES"
    assert D1_BINDING_NAME == "PADIEM_CHAT_DB"


async def test_both_bindings_compose_a_tenant_bound_workspace_store() -> None:
    app = create_app(settings=_settings(), d1_binding=_FakeD1(), r2_binding=_FakeR2())

    store = app.state.workspace_document_store
    assert isinstance(store, WorkspaceDocumentStore)
    assert isinstance(app.state._workspace_metadata_store, D1ClawDocumentMetadataStore)

    saved = await store.put_generated_docx(
        tenant_id=TENANT, filename="quote.docx", body=b"PK-docx-bytes", now=NOW
    )
    assert saved.object_key.startswith(f"workspaces/{TENANT}/claw/documents/{saved.document_id}/")

    metadata, body = await store.get_for_tenant(
        tenant_id=TENANT, document_id=saved.document_id, now=NOW
    )
    assert body == b"PK-docx-bytes"
    with pytest.raises(WorkspaceStorageAccessError):
        await store.get_for_tenant(
            tenant_id=OTHER_TENANT, document_id=saved.document_id, now=NOW
        )


def test_missing_r2_binding_fails_closed_without_store() -> None:
    app = create_app(settings=_settings(), d1_binding=_FakeD1(), r2_binding=None)
    assert app.state.workspace_document_store is None
    assert app.state._workspace_metadata_store is None


def test_missing_d1_binding_fails_closed_without_store() -> None:
    app = create_app(settings=_settings(), d1_binding=None, r2_binding=_FakeR2())
    assert app.state.workspace_document_store is None
    assert app.state._workspace_metadata_store is None


def test_default_app_has_no_workspace_store_fallback() -> None:
    app = create_app(settings=_settings())
    assert app.state.workspace_document_store is None
    assert app.state._workspace_metadata_store is None


def test_binding_selection_has_no_caller_authority() -> None:
    params = set(inspect.signature(create_app).parameters)
    assert {"d1_binding", "r2_binding"} <= params
    assert not ({"request", "body", "cookie", "token", "tenant_id"} & params)


def test_worker_resolves_the_canonical_r2_name_from_trusted_env_only() -> None:
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf-8")

    assert "WORKSPACE_R2_BINDING_NAME" in worker
    assert "PADIEM_WORKSPACE_FILES" not in worker
    assert "r2_binding = binding_value(self.env, WORKSPACE_R2_BINDING_NAME)" in worker
    assert "d1_binding=db_binding" in worker
    assert "r2_binding=r2_binding" in worker
