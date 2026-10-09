"""Network-free tests for private account-bound B66 template source custody (#3884 Slice 1)."""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_template_source import (
    B66TemplateSourceError,
    B66TemplateSourceMetadata,
    B66TemplateSourceStore,
    D1B66TemplateSourceMetadataStore,
    MAX_B66_TEMPLATE_SOURCE_BYTES,
    sanitize_original_filename,
)
from app.config import Settings

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
WORKSPACE_A = f"owner:{USER_A}"
WORKSPACE_B = f"owner:{USER_B}"
TEMPLATE_SOURCE_ID = "b66tplsrc_" + "c" * 32

XLSX_BODY = b"PK\x03\x04customer-original-quotation"
PDF_BODY = b"%PDF-1.4\noriginal-quotation\n%%EOF\n"


def _real_xlsx_bytes() -> bytes:
    """Minimal genuine OOXML package: PK magic + central directory + markers."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return buffer.getvalue()


def _real_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return buffer.getvalue()


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="tplsrc.apps.googleusercontent.com",
        google_client_secret="tplsrc-google-secret",
        session_secret="tplsrc-session-secret-not-real-0000",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


def _metadata(
    *,
    template_source_id=TEMPLATE_SOURCE_ID,
    user_id=USER_A,
    workspace_id=WORKSPACE_A,
    body=XLSX_BODY,
    filename="견적서.xlsx",
):
    return B66TemplateSourceMetadata(
        template_source_id=template_source_id,
        user_id=user_id,
        workspace_id=workspace_id,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        original_filename=filename,
        object_key=(
            "b66/template-source/"
            f"{template_source_id}"
            ".xlsx"
        ),
        byte_length=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        status="uploaded",
        created_at="2026-10-09T00:00:00.000Z",
        updated_at="2026-10-09T00:00:00.000Z",
    )


class MemoryMetadata:
    def __init__(self):
        self.rows = {}
        self.fail_insert = False

    async def insert(self, metadata):
        if self.fail_insert:
            raise RuntimeError("synthetic d1 failure")
        self.rows[
            (metadata.user_id, metadata.workspace_id, metadata.template_source_id)
        ] = metadata

    async def get_active(self, *, template_source_id, user_id, workspace_id):
        return self.rows.get((user_id, workspace_id, template_source_id))

    async def list_for_owner(self, *, user_id, workspace_id, limit=50):
        items = [
            meta
            for (uid, wid, _tid), meta in self.rows.items()
            if uid == user_id and wid == workspace_id
        ]
        items.sort(key=lambda meta: (meta.created_at, meta.template_source_id), reverse=True)
        return items[:limit]


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


def _store(*, metadata=None, r2=None) -> B66TemplateSourceStore:
    return B66TemplateSourceStore(metadata or MemoryMetadata(), r2 or MemoryR2())


@pytest.mark.asyncio
async def test_upload_round_trip_is_owner_workspace_scoped_and_bytes_identical():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66TemplateSourceStore(metadata, r2)

    saved = await store.put_template_source(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        original_filename="견적서.xlsx",
        body=_real_xlsx_bytes(),
    )
    assert saved.template_source_id.startswith("b66tplsrc_")
    assert saved.object_key.startswith("b66/template-source/")
    assert "usr_" not in saved.object_key
    assert saved.status == "uploaded"
    assert saved.sha256 == hashlib.sha256(_real_xlsx_bytes()).hexdigest()
    assert r2.put_calls[0][2]["httpMetadata"]["contentType"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    own = await store.get_for_owner(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        template_source_id=saved.template_source_id,
    )
    assert own is not None
    fetched_metadata, payload = own
    assert payload == _real_xlsx_bytes()  # byte-identical original
    assert fetched_metadata.sha256 == hashlib.sha256(payload).hexdigest()
    assert fetched_metadata.status == "uploaded"

    foreign = await store.get_for_owner(
        user_id=USER_B,
        workspace_id=WORKSPACE_B,
        template_source_id=saved.template_source_id,
    )
    assert foreign is None


@pytest.mark.asyncio
async def test_bounds_and_magic_fail_before_r2_write():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66TemplateSourceStore(metadata, r2)

    with pytest.raises(B66TemplateSourceError, match="media type"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/pdf",
            original_filename="form.pdf",
            body=b"not-a-pdf",
        )

    with pytest.raises(B66TemplateSourceError, match="size"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename="big.xlsx",
            body=b"PK\x03\x04" + b"x" * MAX_B66_TEMPLATE_SOURCE_BYTES,
        )
    assert r2.put_calls == []


@pytest.mark.asyncio
async def test_csv_body_is_accepted_without_binary_magic():
    store = _store()
    csv_body = "품목,수량,단가\n노트,10,1000\n".encode("utf-8")
    saved = await store.put_template_source(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        media_type="text/csv",
        original_filename="form.csv",
        body=csv_body,
    )
    assert saved.object_key.endswith(".csv")
    fetched_metadata, payload = await store.get_for_owner(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        template_source_id=saved.template_source_id,
    )
    assert payload == csv_body
    assert fetched_metadata.media_type == "text/csv"


@pytest.mark.asyncio
async def test_metadata_failure_cleans_private_r2_object():
    metadata = MemoryMetadata()
    metadata.fail_insert = True
    r2 = MemoryR2()
    store = B66TemplateSourceStore(metadata, r2)

    with pytest.raises(B66TemplateSourceError, match="storage failed"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/pdf",
            original_filename="form.pdf",
            body=PDF_BODY,
        )
    assert len(r2.put_calls) == 1
    key = r2.put_calls[0][0]
    assert key in r2.delete_calls
    assert key not in r2.objects


@pytest.mark.asyncio
async def test_r2_object_mutation_fails_integrity_check():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66TemplateSourceStore(metadata, r2)

    saved = await store.put_template_source(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        media_type="application/pdf",
        original_filename="form.pdf",
        body=PDF_BODY,
    )
    # Simulate silent object corruption in private storage.
    r2.objects[saved.object_key] = b"%PDF-1.4\nTAMPERED-QUOTATION"
    with pytest.raises(B66TemplateSourceError, match="integrity check failed"):
        await store.get_for_owner(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            template_source_id=saved.template_source_id,
        )


class _D1Statement:
    def __init__(self, row):
        self.row = row

    def bind(self, *values):
        return self

    async def first(self):
        return self.row


class _D1:
    def __init__(self, row):
        self.row = row

    def prepare(self, sql):
        return _D1Statement(self.row)


@pytest.mark.asyncio
async def test_d1_metadata_cannot_redirect_id_to_another_r2_object():
    row = {
        "id": TEMPLATE_SOURCE_ID,
        "user_id": USER_A,
        "workspace_id": WORKSPACE_A,
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "original_filename": "견적서.xlsx",
        "object_key": "workspaces/other/private-object.xlsx",
        "byte_length": len(XLSX_BODY),
        "sha256": hashlib.sha256(XLSX_BODY).hexdigest(),
        "status": "uploaded",
        "created_at": "2026-10-09T00:00:00.000Z",
        "updated_at": "2026-10-09T00:00:00.000Z",
    }
    store = D1B66TemplateSourceMetadataStore(_D1(row))

    with pytest.raises(B66TemplateSourceError, match="metadata is invalid"):
        await store.get_active(
            template_source_id=TEMPLATE_SOURCE_ID,
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
        )


def test_sanitize_original_filename_strips_paths_and_bounds():
    assert sanitize_original_filename(None) == "original"
    assert sanitize_original_filename("") == "original"
    assert sanitize_original_filename("../../../etc/passwd") == "passwd"
    assert sanitize_original_filename("C:\\evil\\form.xlsx") == "form.xlsx"
    assert sanitize_original_filename(" 견적서.xlsx ") == "견적서.xlsx"
    with pytest.raises(B66TemplateSourceError):
        sanitize_original_filename("x" * 201)


def test_ooxml_requires_real_zip_structure_not_just_pk_magic():
    """Placeholder removed: superseded by the async coverage below."""
    assert True


@pytest.mark.asyncio
async def test_pk_magic_only_xlsx_is_rejected_before_r2_write():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66TemplateSourceStore(metadata, r2)
    with pytest.raises(B66TemplateSourceError, match="does not match"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename="fake.xlsx",
            body=b"PK\x03\x04not-a-real-zip-package",
        )
    assert r2.put_calls == []


@pytest.mark.asyncio
async def test_genuine_ooxml_packages_are_accepted():
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66TemplateSourceStore(metadata, r2)
    saved = await store.put_template_source(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        original_filename="real.xlsx",
        body=_real_xlsx_bytes(),
    )
    fetched, payload = await store.get_for_owner(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        template_source_id=saved.template_source_id,
    )
    assert payload == _real_xlsx_bytes()

    docx_store = B66TemplateSourceStore(MemoryMetadata(), MemoryR2())
    docx_saved = await docx_store.put_template_source(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        original_filename="real.docx",
        body=_real_docx_bytes(),
    )
    assert docx_saved.object_key.endswith(".docx")


@pytest.mark.asyncio
async def test_xlsx_media_type_rejects_docx_container_and_vice_versa():
    store = _store()
    with pytest.raises(B66TemplateSourceError, match="does not match"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename="mislabeled.xlsx",
            body=_real_docx_bytes(),
        )
    with pytest.raises(B66TemplateSourceError, match="does not match"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            original_filename="mislabeled.docx",
            body=_real_xlsx_bytes(),
        )


@pytest.mark.asyncio
async def test_ooxml_with_path_traversal_or_encrypted_entries_is_rejected():
    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("../evil.xml", "<evil/>")
    store = _store()
    with pytest.raises(B66TemplateSourceError, match="does not match"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename="traversal.xlsx",
            body=traversal.getvalue(),
        )

    encrypted = io.BytesIO()
    with zipfile.ZipFile(encrypted, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        # zipfile.writestr resets flag_bits, so forge the raw central-directory
        # entry: set the encrypted bit via a comment-free manual ZipInfo hack —
        # instead we patch the validator input by wrapping the archive bytes with
        # a manually built central directory entry carrying flag bit 0x1.
        archive.writestr("xl/workbook.xml", "<workbook/>")
    raw = bytearray(encrypted.getvalue())
    # Locate the central directory header (PK\x01\x02) for xl/workbook.xml and
    # set its general-purpose flag bit 0 (offset 8, little-endian) to 0x0001.
    idx = bytes(raw).find(b"PK\x01\x02\x14\x00")
    assert idx != -1
    flags = int.from_bytes(raw[idx + 8 : idx + 10], "little") | 0x1
    raw[idx + 8 : idx + 10] = flags.to_bytes(2, "little")
    with pytest.raises(B66TemplateSourceError, match="does not match"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename="encrypted.xlsx",
            body=bytes(raw),
        )


@pytest.mark.asyncio
async def test_truncated_pdf_without_eof_marker_is_rejected():
    store = _store()
    with pytest.raises(B66TemplateSourceError, match="does not match"):
        await store.put_template_source(
            user_id=USER_A,
            workspace_id=WORKSPACE_A,
            media_type="application/pdf",
            original_filename="truncated.pdf",
            body=b"%PDF-1.4\ntruncated-stream-without-eof",
        )


@pytest.mark.asyncio
async def test_redownload_integrity_check_stays_magic_plus_hash_only():
    # Custody guarantee: a previously accepted original must remain returnable
    # even if upload-time structure rules tighten later. get_for_owner must not
    # apply the upload-time OOXML/PDF structural inspection.
    metadata = MemoryMetadata()
    r2 = MemoryR2()
    store = B66TemplateSourceStore(metadata, r2)
    saved = await store.put_template_source(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        media_type="application/pdf",
        original_filename="ok.pdf",
        body=b"%PDF-1.4\nq\n%%EOF\n",
    )
    fetched_metadata, payload = await store.get_for_owner(
        user_id=USER_A,
        workspace_id=WORKSPACE_A,
        template_source_id=saved.template_source_id,
    )
    assert payload == b"%PDF-1.4\nq\n%%EOF\n"
    assert fetched_metadata.sha256 == hashlib.sha256(payload).hexdigest()


class RouteStore:
    """Owner-checked fake store driving route-level assertions."""

    def __init__(self):
        self.calls = []
        self.upload_calls = []
        self.items = []
        self.unavailable = False

    async def put_template_source(self, *, user_id, workspace_id, media_type,
                                  original_filename=None, body):
        self.upload_calls.append((user_id, workspace_id, media_type))
        if media_type not in (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/csv",
        ):
            raise B66TemplateSourceError("media_type is invalid")
        # Emulate the real store contract: magic/structure/size validation
        # happens before any R2 write and raises before metadata is created.
        if media_type == "application/pdf" and not (
            body.startswith(b"%PDF-") and b"%%EOF" in body
        ):
            raise B66TemplateSourceError(
                "template source media type does not match bytes"
            )
        if media_type in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ) and not body.startswith(b"PK\x03\x04"):
            raise B66TemplateSourceError(
                "template source media type does not match bytes"
            )
        if user_id != USER_A or workspace_id != WORKSPACE_A:
            raise B66TemplateSourceError("user_id is invalid")
        metadata = _metadata(
            template_source_id=TEMPLATE_SOURCE_ID,
            user_id=user_id,
            workspace_id=workspace_id,
            body=body,
            filename=original_filename or "original",
        )
        self.items.append(metadata)
        return metadata

    async def list_for_owner(self, *, user_id, workspace_id, limit=50):
        self.calls.append(("list", user_id, workspace_id))
        if self.unavailable:
            raise B66TemplateSourceError("template source metadata is invalid")
        return [
            item
            for item in self.items
            if item.user_id == user_id and item.workspace_id == workspace_id
        ][:limit]

    async def get_for_owner(self, *, user_id, workspace_id, template_source_id):
        self.calls.append(("get", user_id, workspace_id, template_source_id))
        if user_id != USER_A or workspace_id != WORKSPACE_A:
            return None
        if template_source_id != TEMPLATE_SOURCE_ID:
            return None
        return _metadata(body=XLSX_BODY), XLSX_BODY


def _client(*, user_id=USER_A, signed_in=True, store=None) -> TestClient:
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_template_source_store=store if store is not None else RouteStore(),
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


def _upload_payload(*, media_type=None, filename="견적서.xlsx", body=None):
    return {
        "media_type": media_type
        or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "filename": filename,
        "content_base64": base64.b64encode(body if body is not None else XLSX_BODY).decode(
            "ascii"
        ),
    }


def test_upload_requires_login_and_never_trusts_client_owner():
    store = RouteStore()
    anonymous = _client(store=store, signed_in=False)
    response = anonymous.post("/api/b66/template-sources", json=_upload_payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert store.upload_calls == []

    owner_payload = _upload_payload()
    owner_payload["workspace"] = WORKSPACE_B
    owner = _client(store=store)
    rejected = owner.post("/api/b66/template-sources", json=owner_payload)
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "template_source_owner_not_allowed"
    assert store.upload_calls == []


def test_upload_success_returns_only_projected_fields():
    store = RouteStore()
    client = _client(store=store)
    response = client.post("/api/b66/template-sources", json=_upload_payload())
    assert response.status_code == 201
    assert response.headers["cache-control"].startswith("private, no-store")
    payload = response.json()
    assert payload["ok"] is True
    projected = payload["template_source"]
    assert set(projected) == {
        "template_source_id",
        "media_type",
        "original_filename",
        "byte_length",
        "sha256",
        "status",
        "created_at",
    }
    assert projected["status"] == "uploaded"
    assert "object_key" not in projected
    assert len(store.upload_calls) == 1


def test_upload_rejects_invalid_base64_media_type_and_body():
    store = RouteStore()
    client = _client(store=store)

    bad_base64 = _upload_payload()
    bad_base64["content_base64"] = "!!!not-base64!!!"
    response = client.post("/api/b66/template-sources", json=bad_base64)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "template_source_body_invalid"
    assert store.upload_calls == []

    wrong_media = _upload_payload(media_type="application/zip")
    response = client.post("/api/b66/template-sources", json=wrong_media)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "template_source_media_type_invalid"

    bad_bytes = _upload_payload(
        media_type="application/pdf", body=b"PK\x03\x04-not-a-pdf"
    )
    response = client.post("/api/b66/template-sources", json=bad_bytes)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "template_source_body_invalid"
    # Attempts may reach the store (validation authority), but no upload ever
    # succeeds: no metadata/R2 write is represented by store.items.
    assert store.items == []


def test_download_is_owner_scoped_and_non_disclosing():
    store = RouteStore()
    owner = _client(store=store)
    response = owner.get(f"/api/b66/template-sources/{TEMPLATE_SOURCE_ID}")
    assert response.status_code == 200
    assert response.content == XLSX_BODY
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["cache-control"].startswith("private, no-store")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")

    other = _client(user_id=USER_B, store=store)
    denied = other.get(f"/api/b66/template-sources/{TEMPLATE_SOURCE_ID}")
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "template_source_not_found"

    anonymous = _client(store=store, signed_in=False)
    assert anonymous.get(
        f"/api/b66/template-sources/{TEMPLATE_SOURCE_ID}"
    ).status_code == 401


def test_download_rejects_malformed_id_before_store_call():
    store = RouteStore()
    client = _client(store=store)
    response = client.get("/api/b66/template-sources/not-an-id")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "template_source_id_invalid"
    assert ("get", USER_A, WORKSPACE_A, "not-an-id") not in store.calls


def test_list_is_owner_scoped():
    store = RouteStore()
    client = _client(store=store)
    uploaded = client.post("/api/b66/template-sources", json=_upload_payload())
    assert uploaded.status_code == 201

    listing = client.get("/api/b66/template-sources")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["ok"] is True
    assert len(payload["template_sources"]) == 1
    assert payload["template_sources"][0]["template_source_id"] == TEMPLATE_SOURCE_ID

    other = _client(user_id=USER_B, store=store)
    foreign = other.get("/api/b66/template-sources")
    assert foreign.status_code == 200
    assert foreign.json()["template_sources"] == []


def test_migration_026_stores_metadata_only():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "026_b66_template_source.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b66_template_source" in migration
    assert "user_id TEXT NOT NULL REFERENCES users(id)" in migration
    assert "workspace_id TEXT NOT NULL" in migration
    assert "object_key TEXT NOT NULL UNIQUE" in migration
    assert "10485760" in migration
    assert "'uploaded'" in migration
    lowered = migration.lower()
    for forbidden in (" blob", "base64", "template_bytes", "file_bytes", "content"):
        assert forbidden not in lowered


def test_routes_are_registered_and_composition_fails_closed():
    app = create_app(
        settings=Settings.from_values(runtime_mode="mock", auth_mode="off", live_enabled="false")
    )
    assert app.state.b66_template_source_store is None
    paths = {
        (route.path, tuple(sorted(getattr(route, "methods", []) or [])))
        for route in app.routes
        if str(getattr(route, "path", "")).startswith("/api/b66/template-sources")
    }
    assert ("/api/b66/template-sources", ("POST",)) in paths
    assert ("/api/b66/template-sources", ("GET", "HEAD")) in paths
    assert ("/api/b66/template-sources/{template_source_id}", ("GET", "HEAD")) in paths


class _FakeD1Statement:
    def bind(self, *values):
        return self

    async def run(self):
        return {}

    async def first(self):
        return None

    async def all(self):
        return {"results": []}


class _FakeD1:
    def prepare(self, sql):
        return _FakeD1Statement()


class _FakeR2:
    async def put(self, key, body, **kwargs):
        return {}

    async def get(self, key):
        return None

    async def delete(self, key):
        return {}


def test_composition_binds_store_when_both_bindings_present():
    app = create_app(
        settings=_settings(), d1_binding=_FakeD1(), r2_binding=_FakeR2()
    )
    assert app.state.b66_template_source_store is not None
    assert isinstance(app.state.b66_template_source_store, B66TemplateSourceStore)


def test_composition_fails_closed_without_r2_binding():
    app = create_app(settings=_settings(), d1_binding=_FakeD1(), r2_binding=None)
    assert app.state.b66_template_source_store is None
