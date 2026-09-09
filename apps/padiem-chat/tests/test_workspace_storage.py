from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.workspace_storage import (
    DOCX_MEDIA_TYPE,
    GENERATED_DOCUMENT_RETENTION_DAYS,
    SINGLE_FILE_MAX_BYTES,
    WorkspaceDocumentStore,
    WorkspaceStorageAccessError,
)

NOW = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
TENANT = "tenant_0123456789abcdef0123456789abcdef"
OTHER_TENANT = "tenant_fedcba9876543210fedcba9876543210"


class MemoryMetadata:
    def __init__(self):
        self.rows = {}
        self.deleted = []

    async def insert(self, metadata):
        self.rows[metadata.document_id] = metadata

    async def get_active(self, document_id):
        return self.rows.get(document_id)

    async def mark_deleted(self, document_id, deleted_at):
        self.rows.pop(document_id, None)
        self.deleted.append((document_id, deleted_at))


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


def store():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    return WorkspaceDocumentStore(metadata, r2), metadata, r2


async def test_generated_docx_uses_server_generated_private_workspace_key() -> None:
    storage, metadata, r2 = store()

    saved = await storage.put_generated_docx(
        tenant_id=TENANT,
        filename="../unsafe quote 2026",
        body=b"PK-docx-bytes",
        now=NOW,
    )

    assert saved.document_id.startswith("doc_")
    assert saved.filename == "unsafe-quote-2026.docx"
    assert saved.object_key == f"workspaces/{TENANT}/claw/documents/{saved.document_id}/{saved.filename}"
    assert saved.media_type == DOCX_MEDIA_TYPE
    assert saved.byte_length == len(b"PK-docx-bytes")
    assert saved.expires_at == NOW + timedelta(days=GENERATED_DOCUMENT_RETENTION_DAYS)
    assert r2.put_calls[0][0] == saved.object_key
    assert "public" not in saved.public_projection()
    assert "object_key" not in saved.public_projection()
    assert "body" not in saved.public_projection()
    assert saved.document_id in metadata.rows


async def test_same_canonical_tenant_can_read_but_cross_tenant_is_denied() -> None:
    storage, _, _ = store()
    saved = await storage.put_generated_docx(
        tenant_id=TENANT,
        filename="quote.docx",
        body=b"private-docx",
        now=NOW,
    )

    metadata, body = await storage.get_for_tenant(
        tenant_id=TENANT,
        document_id=saved.document_id,
        now=NOW + timedelta(minutes=1),
    )
    assert metadata.document_id == saved.document_id
    assert body == b"private-docx"

    with pytest.raises(WorkspaceStorageAccessError):
        await storage.get_for_tenant(
            tenant_id=OTHER_TENANT,
            document_id=saved.document_id,
            now=NOW + timedelta(minutes=1),
        )


async def test_expired_generated_document_is_deleted_and_not_returned() -> None:
    storage, metadata, r2 = store()
    saved = await storage.put_generated_docx(
        tenant_id=TENANT,
        filename="quote.docx",
        body=b"private-docx",
        now=NOW,
    )

    result = await storage.get_for_tenant(
        tenant_id=TENANT,
        document_id=saved.document_id,
        now=saved.expires_at,
    )

    assert result is None
    assert saved.object_key in r2.delete_calls
    assert saved.document_id not in metadata.rows


async def test_single_file_bound_is_enforced_before_r2_write() -> None:
    storage, _, r2 = store()

    with pytest.raises(ValueError):
        await storage.put_generated_docx(
            tenant_id=TENANT,
            filename="too-large.docx",
            body=b"x" * (SINGLE_FILE_MAX_BYTES + 1),
            now=NOW,
        )

    assert r2.put_calls == []


async def test_caller_cannot_supply_object_key_or_document_id() -> None:
    storage, _, _ = store()
    method_params = storage.put_generated_docx.__signature__ if hasattr(storage.put_generated_docx, "__signature__") else None
    # API shape itself accepts only tenant, filename, bytes and optional time.
    import inspect

    names = set(inspect.signature(storage.put_generated_docx).parameters)
    assert "object_key" not in names
    assert "document_id" not in names
    assert method_params is None


def test_d1_metadata_schema_stores_no_binary_body_and_enforces_10mb_limit() -> None:
    migration = (Path(__file__).resolve().parents[1] / "migrations" / "008_claw_document_metadata.sql").read_text()

    assert "claw_document_metadata" in migration
    assert "tenant_id TEXT NOT NULL" in migration
    assert "object_key TEXT NOT NULL UNIQUE" in migration
    assert "byte_length INTEGER NOT NULL" in migration
    assert "10485760" in migration
    lowered = migration.lower()
    assert "blob" not in lowered
    assert "document_bytes" not in lowered
    assert "refresh_token" not in lowered
    assert "access_token" not in lowered
