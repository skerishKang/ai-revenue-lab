"""#5728 — SNS composition photos persist through the project file store.

The photos are opaque originals: the exact uploaded bytes land in R2 under the
same owner-scoped key the document path uses, the record keeps the declared
image media type, and the document text pipeline (parser + normalization) is
never entered. The original route serves them back with that same media type
so the SNS composition can restore itself byte-identically.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import UserProfile
from app.main import create_app
from app.project_files import D1ProjectFileStore  # noqa: F401  (import-surface contract)
from tests.test_project_file_binary_upload import (
    MemoryProjectFileStore,
    MemoryProjectStore,
    _MemoryR2,
    client_with_session,
    post_binary,
    settings,
    user_profile,
)


def _png_bytes() -> bytes:
    # Minimal structurally honest PNG: signature + IHDR header chunk.
    ihdr = (13).to_bytes(4, "big") + b"IHDR" + (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + ihdr + (0).to_bytes(4, "big")


def _jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xd9"


def _webp_bytes() -> bytes:
    payload = b"WEBP" + b"VP8 " + (4).to_bytes(4, "little") + b"\x00\x00\x00\x00"
    return b"RIFF" + (len(payload)).to_bytes(4, "little") + payload


def _text_bytes() -> bytes:
    return b"this is definitely not an image"


@pytest.mark.asyncio
async def test_png_upload_stores_opaque_original_without_the_document_parser():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-photo")
    project = await history.create_project(owner.id, "SNS 사진", "")
    app = create_app(settings(), history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    bucket = app.state.workspace_document_store.r2_bucket
    try:
        with mock.patch("app.project_file_routes.parse_binary_document_via_authority") as parser:
            response = await post_binary(
                client, f"/api/projects/{project.id}/files",
                name="행사 사진.png", media_type="image/png",
                base64=__import__("base64", fromlist=["b64encode"]).b64encode(_png_bytes()).decode(),
            )
        parser.assert_not_called()
        assert response.status_code == 201, response.json()
        data = response.json()["file"]
        assert data["media_type"] == "image/png"
        assert data["content_chars"] == 0
        files = await store.list_files(owner.id, project.id)
        assert len(files) == 1
        assert files[0].media_type == "image/png"
        assert files[0].content_text == ""
        # The exact uploaded bytes are the stored original, typed as uploaded.
        stored = bucket.objects.get(f"projects/{owner.id}/{project.id}/originals/{data['id']}")
        assert stored == _png_bytes()
        assert bucket._http_metadata.get(f"projects/{owner.id}/{project.id}/originals/{data['id']}") == "image/png"
        payload = json.dumps(data, ensure_ascii=False)
        assert "base64" not in payload
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_jpeg_and_webp_uploads_keep_their_declared_media_type():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-photo-kinds")
    project = await history.create_project(owner.id, "SNS 사진", "")
    app = create_app(settings(), history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    b64 = __import__("base64", fromlist=["b64encode"])
    try:
        for name, media, raw in (
            ("카드.jpg", "image/jpeg", _jpeg_bytes()),
            ("배경.webp", "image/webp", _webp_bytes()),
        ):
            response = await post_binary(
                client, f"/api/projects/{project.id}/files",
                name=name, media_type=media, base64=b64.b64encode(raw).decode(),
            )
            assert response.status_code == 201, response.json()
            assert response.json()["file"]["media_type"] == media
        kinds = sorted(f.media_type for f in await store.list_files(owner.id, project.id))
        assert kinds == ["image/jpeg", "image/webp"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_declared_media_type_must_match_the_uploaded_bytes():
    """The image lane refuses mislabeled bytes instead of storing them."""
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-photo-magic")
    project = await history.create_project(owner.id, "SNS 사진", "")
    app = create_app(settings(), history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    b64 = __import__("base64", fromlist=["b64encode"])
    try:
        response = await post_binary(
            client, f"/api/projects/{project.id}/files",
            name="가짜.png", media_type="image/png", base64=b64.b64encode(_text_bytes()).decode(),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_document"
        assert await store.list_files(owner.id, project.id) == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_image_original_route_serves_the_stored_media_type():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-photo-original")
    project = await history.create_project(owner.id, "SNS 사진", "")
    app = create_app(settings(), history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    b64 = __import__("base64", fromlist=["b64encode"])
    try:
        created = await post_binary(
            client, f"/api/projects/{project.id}/files",
            name="행사 사진.png", media_type="image/png", base64=b64.b64encode(_png_bytes()).decode(),
        )
        fid = created.json()["file"]["id"]
        served = await client.get(f"/api/projects/{project.id}/files/{fid}/original")
        assert served.status_code == 200
        assert served.headers["content-type"].startswith("image/png")
        assert served.headers.get("cache-control") == "private, no-store"
        assert served.content == _png_bytes()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_image_upload_stays_inside_the_owner_scoped_project_guard():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-photo-guard")
    other = await history.add_user("other-photo-guard")
    project = await history.create_project(owner.id, "내 프로젝트", "")
    app = create_app(settings(), history_store=history, project_file_store=store)
    owner_client = await client_with_session(app, owner)
    other_client = await client_with_session(app, other)
    b64 = __import__("base64", fromlist=["b64encode"])
    try:
        denied = await post_binary(
            other_client, f"/api/projects/{project.id}/files",
            name="침입.png", media_type="image/png", base64=b64.b64encode(_png_bytes()).decode(),
        )
        assert denied.status_code == 404
        assert await store.list_files(other.id, project.id) == []
        anonymous = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test",
        )
        try:
            rejected = await post_binary(
                anonymous, f"/api/projects/{project.id}/files",
                name="익명.png", media_type="image/png", base64=b64.b64encode(_png_bytes()).decode(),
            )
            assert rejected.status_code == 401
        finally:
            await anonymous.aclose()
    finally:
        await owner_client.aclose()
        await other_client.aclose()
