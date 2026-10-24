"""#5728 — image project files: raw byte storage, retrieval, delete, isolation.

Images reuse the existing project-file binary channel end to end:

- PNG/JPEG/WebP upload stores the ORIGINAL bytes in R2 and a record with the
  exact original media_type and no parsed text (no document parser runs);
- the owner re-reads the byte-identical original through `/original`;
- delete removes both the record and the stored original;
- another owner/project gets 404 (existing `_identity` scoping);
- PDF/DOCX behavior is unchanged (covered by test_project_file_binary_upload).
"""
from __future__ import annotations

import base64 as b64
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.main import create_app
from test_project_file_binary_upload import (  # noqa: F401 — shared fixtures
    MemoryProjectFileStore,
    MemoryProjectStore,
    _MemoryR2,
    post_binary,
    settings,
)

from app.project_files import IMAGE_PROJECT_FILE_MEDIA, ProjectFileRecord
import uuid as _uuid


class _StoreWithValidIds(MemoryProjectFileStore):
    """The shared memory store mints 69-char ids; the routes validate 37.
    These tests read the record back through HTTP, so mint real ids."""

    async def create_file(self, user_id, project_id, name, media_type, text, *, source_media_type=None):
        rec = ProjectFileRecord(
            id="file_" + _uuid.uuid4().hex,
            project_id=project_id, name=name, media_type=media_type,
            content_text=text, content_chars=len(text),
            created_at="t1", updated_at="t1",
        )
        self.files.setdefault((user_id, project_id), []).append(rec)
        return rec


PNG_1x1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# Real JPEG and WebP headers: the image lane validates the declared media
# type against the actual bytes, so the fixtures must be honest images.
JPEG_1x1 = b64.b64encode(
    bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"JFIF" + bytes([0])
    + bytes([0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00])
    + bytes([0xFF, 0xD9])
).decode()

_webp_payload = b"WEBP" + b"VP8 " + (4).to_bytes(4, "little") + bytes([0, 0, 0, 0])
WEBP_MINIMAL = b64.b64encode(
    b"RIFF" + (len(_webp_payload)).to_bytes(4, "little") + _webp_payload
).decode()


class _R2WithGet(_MemoryR2):
    async def get(self, key, **kwargs):
        data = self.objects.get(key)
        return None if data is None else SimpleNamespace(body=data)


async def _owner_app_client(marker="img-owner", project_name="SNS 사진"):
    history = MemoryProjectStore()
    owner = await history.add_user(marker)
    project = await history.create_project(owner.id, project_name, "")
    store = _StoreWithValidIds()
    bucket = _R2WithGet()
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    app.state.settings = cfg
    app.state.workspace_document_store = SimpleNamespace(r2_bucket=bucket)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test")
    client.cookies.set(SESSION_COOKIE, create_session_token(cfg, owner.id), domain="chat.example.test", path="/")
    return app, store, bucket, owner, project, client


@pytest.mark.asyncio
async def test_image_media_set_is_the_attachment_family():
    assert IMAGE_PROJECT_FILE_MEDIA == {"image/png", "image/jpeg", "image/webp"}


@pytest.mark.asyncio
@pytest.mark.parametrize("media", ["image/png", "image/jpeg", "image/webp"])
async def test_all_three_image_types_store_original_bytes_without_parsing(media):
    app, store, bucket, owner, project, client = await _owner_app_client()
    try:
        raw = {
            "image/png": b64.b64decode(PNG_1x1),
            "image/jpeg": b64.b64decode(JPEG_1x1),
            "image/webp": b64.b64decode(WEBP_MINIMAL),
        }[media]
        response = await post_binary(
            client, f"/api/projects/{project.id}/files",
            name="harbor.png", media_type=media, base64=b64.b64encode(raw).decode(),
        )
        assert response.status_code == 201, response.text
        body = response.json()["file"]
        assert body["media_type"] == media
        assert body["content_chars"] == 0
        record = await store.get_file(owner.id, project.id, body["id"])
        assert record is not None and record.content_text == ""
        stored = [v for k, v in bucket.objects.items() if body["id"] in k]
        assert stored == [raw], "the stored original must be byte-identical"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_owner_reads_the_byte_identical_original_with_exact_media():
    app, store, bucket, owner, project, client = await _owner_app_client()
    try:
        created = (
            await post_binary(client, f"/api/projects/{project.id}/files",
                              name="harbor.png", media_type="image/png", base64=PNG_1x1)
        ).json()["file"]
        original = await client.get(f"/api/projects/{project.id}/files/{created['id']}/original")
        assert original.status_code == 200
        assert original.headers["content-type"].startswith("image/png")
        assert b64.b64decode(PNG_1x1) == original.content
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_delete_removes_record_and_stored_original():
    app, store, bucket, owner, project, client = await _owner_app_client()
    try:
        created = (
            await post_binary(client, f"/api/projects/{project.id}/files",
                              name="harbor.png", media_type="image/png", base64=PNG_1x1)
        ).json()["file"]
        assert any(created["id"] in k for k in bucket.objects)
        deleted = await client.delete(f"/api/projects/{project.id}/files/{created['id']}")
        assert deleted.status_code == 204
        assert await store.get_file(owner.id, project.id, created["id"]) is None
        assert not any(created["id"] in k for k in bucket.objects)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_another_owner_is_denied_and_the_copy_survives():
    history = MemoryProjectStore()
    owner = await history.add_user("img-owner-a")
    stranger = await history.add_user("img-stranger-b")
    project = await history.create_project(owner.id, "SNS 사진", "")
    store = _StoreWithValidIds()
    bucket = _R2WithGet()
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    app.state.settings = cfg
    app.state.workspace_document_store = SimpleNamespace(r2_bucket=bucket)

    async def session_for(user):
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test")
        c.cookies.set(SESSION_COOKIE, create_session_token(cfg, user.id), domain="chat.example.test", path="/")
        return c

    owner_client = await session_for(owner)
    try:
        created = (
            await post_binary(owner_client, f"/api/projects/{project.id}/files",
                              name="harbor.png", media_type="image/png", base64=PNG_1x1)
        ).json()["file"]
    finally:
        await owner_client.aclose()

    stranger_client = await session_for(stranger)
    try:
        foreign_original = await stranger_client.get(f"/api/projects/{project.id}/files/{created['id']}/original")
        assert foreign_original.status_code == 404
        foreign_delete = await stranger_client.delete(f"/api/projects/{project.id}/files/{created['id']}")
        assert foreign_delete.status_code == 404
        assert await store.get_file(owner.id, project.id, created["id"]) is not None
        assert any(created["id"] in k for k in bucket.objects)
    finally:
        await stranger_client.aclose()


@pytest.mark.asyncio
async def test_mislabeled_bytes_are_rejected_and_store_nothing():
    """The parser-free image lane still refuses a body that does not match
    its declared media type — the same honesty the document path gets from
    its parser's format checks (a text payload renamed .png is not a PNG)."""
    app, store, bucket, owner, project, client = await _owner_app_client()
    try:
        response = await post_binary(
            client, f"/api/projects/{project.id}/files",
            name="가짜.png", media_type="image/png",
            base64=__import__("base64", fromlist=["b64encode"]).b64encode(b"this is definitely not an image").decode(),
        )
        assert response.status_code == 422
        assert not bucket.objects
        assert not store.files
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unsupported_image_type_is_rejected_and_stores_nothing():
    app, store, bucket, owner, project, client = await _owner_app_client()
    try:
        response = await post_binary(
            client, f"/api/projects/{project.id}/files",
            name="x.gif", media_type="image/gif", base64=PNG_1x1,
        )
        assert response.status_code == 422
        assert not bucket.objects
        assert not store.files
    finally:
        await client.aclose()

@pytest.mark.asyncio
async def test_d1_store_create_accepts_images_without_document_validation(monkeypatch):
    """The production D1 path (not the memory store) must accept image media.

    Regression for the first deploy: validate_document_fields rejected
    image/png and every upload answered 422.
    """
    from app.project_files import D1ProjectFileStore

    store = D1ProjectFileStore(object())
    captured = {}

    async def fake_run(sql, *values):
        captured["sql"] = sql
        captured["values"] = values
        return {"results": [{"id": "file_" + "0" * 32}]}

    monkeypatch.setattr(store, "_run", fake_run)
    record = await store.create_file("u1", "p1", "harbor.png", "image/png", "")
    assert record.media_type == "image/png"
    assert record.content_text == ""
    assert record.content_chars == 0
    assert "image/png" in captured["values"]
