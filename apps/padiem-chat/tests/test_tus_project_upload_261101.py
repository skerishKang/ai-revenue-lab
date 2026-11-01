"""1GB 통일 1단계 — 프로젝트 파일 tus 조각 업로드 서버 계약.

docs/research/LARGE_UPLOAD_1GB_DESIGN_20261101.md A안 1단계. The tus verbs ride
on the same session auth and the same save flow as the direct octet-stream
route (app.project_file_routes.save_binary_project_file), so every refusal here
is the route's own Korean guidance and every success lands in the very same
store rows and original-bytes objects. The browser contract is proved in
tests/test_b62_2342_project_file_binary_ui.py; the front pass-through in
apps/padiem-chat-front/test/tus-upload.test.mjs.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import zipfile
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.binary_documents import guidance_for_reason_code
from app.config import Settings
from app.history import ProjectProfile, UserProfile
from app.main import create_app
from app.project_files import ProjectFileRecord
from app.tus_core import (
    _DATA_NAME,
    _META_NAME,
    sweep_expired_uploads,
    upload_root as _upload_root,
)

SESSION_SECRET = "tus-test-session-secret-0123456789abcdef0123456789abcdef"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
TUS = "1.0.0"


def settings(*, runtime="mock"):
    return Settings.from_values(
        runtime_mode=runtime,
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="phase11.apps.googleusercontent.com",
        google_client_secret="phase11-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        web_provider="off",
    )


def user_profile(uid="usr_test", email="u@example.test"):
    return UserProfile(uid, email, "테스터", "")


class MemoryProjectStore:
    def __init__(self):
        self.users: dict[str, UserProfile] = {}
        self.projects: dict[str, dict] = {}

    async def upsert_google_user(self, subject, email, name, picture):
        uid = "usr_" + subject[:32].ljust(32, "0")
        profile = UserProfile(uid, email, name or email, picture)
        self.users[uid] = profile
        return profile

    async def add_user(self, marker: str):
        return await self.upsert_google_user(marker, f"{marker}@example.test", marker, "")

    async def get_project(self, user_id, project_id):
        row = self.projects.get(project_id)
        if row is None or row["user_id"] != user_id:
            return None
        return row["profile"]

    async def create_project(self, user_id, name, instructions):
        pid = "proj_" + str(len(self.projects) + 1).rjust(32, "2")
        self.projects[pid] = {"user_id": user_id, "profile": ProjectProfile(pid, name, instructions, "t1", "t1")}
        return self.projects[pid]["profile"]


class MemoryProjectFileStore:
    def __init__(self):
        self.files = {}

    async def list_files(self, user_id, project_id):
        return list(self.files.get((user_id, project_id), []))

    async def get_file(self, user_id, project_id, file_id):
        for f in self.files.get((user_id, project_id), []):
            if f.id == file_id:
                return f
        return None

    async def create_file(self, user_id, project_id, name, media_type, text, *, source_media_type=None, country="kr"):
        rec = ProjectFileRecord(
            id="file_" + len(self.files).to_bytes(32, "big").hex(),
            project_id=project_id,
            name=name,
            media_type=media_type,
            content_text=text,
            content_chars=len(text),
            created_at="t1",
            updated_at="t1",
        )
        self.files.setdefault((user_id, project_id), []).append(rec)
        return rec

    async def delete_file(self, user_id, project_id, file_id):
        key = (user_id, project_id)
        self.files[key] = [f for f in self.files.get(key, []) if f.id != file_id]
        return True


class _CountingR2:
    """Original-bytes bucket double: records only the digest, never the bytes."""

    def __init__(self):
        self.objects = {}

    async def put(self, key, body, **kwargs):
        self.objects[key] = hashlib.sha256(bytes(body)).hexdigest()

    async def delete(self, key):
        self.objects.pop(key, None)


def tus_metadata(name: str, media_type: str) -> str:
    return (
        "filename " + base64.b64encode(name.encode("utf-8")).decode("ascii")
        + ",filetype " + base64.b64encode(media_type.encode("ascii")).decode("ascii")
    )


def make_app(monkeypatch, tmp_path, *, chunk_bytes=None, max_bytes=None, cleanup_seconds=None):
    monkeypatch.setenv("PADIEM_TUS_UPLOAD_DIR", str(tmp_path / "tus-uploads"))
    if chunk_bytes is not None:
        monkeypatch.setenv("PADIEM_TUS_CHUNK_MAX_BYTES", str(chunk_bytes))
    if max_bytes is not None:
        monkeypatch.setenv("PADIEM_TUS_MAX_UPLOAD_BYTES", str(max_bytes))
    if cleanup_seconds is not None:
        monkeypatch.setenv("PADIEM_TUS_CLEANUP_SECONDS", str(cleanup_seconds))
    history = MemoryProjectStore()
    store = MemoryProjectFileStore()
    app = create_app(settings(), history_store=history, project_file_store=store)
    app.state.workspace_document_store = SimpleNamespace(r2_bucket=_CountingR2())
    return app, history, store


async def client_with_session(app, user: UserProfile):
    cfg = Settings.from_values(
        session_secret=SESSION_SECRET, auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="phase11.apps.googleusercontent.com",
        google_client_secret="phase11-secret",
    )
    app.state.settings = cfg
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test")
    client.cookies.set(SESSION_COOKIE, create_session_token(cfg, user.id), domain="chat.example.test", path="/")
    return client


async def create_upload(client, project_id, *, name, media_type, length):
    return await client.post(
        f"/api/projects/{project_id}/files/tus",
        headers={
            "Upload-Length": str(length),
            "Upload-Metadata": tus_metadata(name, media_type),
            "Tus-Resumable": TUS,
        },
    )


async def patch_chunk(client, project_id, upload_id, offset, chunk, *, content_type="application/offset+octet-stream"):
    return await client.patch(
        f"/api/projects/{project_id}/files/tus/{upload_id}",
        content=chunk,
        headers={"Upload-Offset": str(offset), "Content-Type": content_type, "Tus-Resumable": TUS},
    )


@pytest.mark.asyncio
async def test_tus_options_reports_discovery_limits(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path, chunk_bytes=94371840, max_bytes=1073741824)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test")
    try:
        response = await client.options("/api/projects/proj_x/files/tus", headers={"Tus-Resumable": TUS})
        assert response.status_code == 204
        assert response.headers["tus-resumable"] == TUS
        assert response.headers["tus-version"] == TUS
        assert response.headers["tus-max-size"] == "1073741824"
        assert response.headers["tus-extension"] == "creation"
        assert response.headers["x-padiem-tus-chunk-max"] == "94371840"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_creation_requires_session(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path)
    owner = await history.add_user("tus-anon")
    project = await history.create_project(owner.id, "프로젝트", "")
    app.state.settings = settings()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test")
    try:
        response = await create_upload(client, project.id, name="보고서.pdf", media_type="application/pdf", length=1024)
        assert response.status_code in (401, 403, 503)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_creation_returns_unguessable_location_and_limits(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path, chunk_bytes=4096, max_bytes=100000)
    owner = await history.add_user("tus-create")
    project = await history.create_project(owner.id, "프로젝트", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        response = await create_upload(client, project.id, name="보고서.pdf", media_type="application/pdf", length=2048)
        assert response.status_code == 201
        assert response.headers["tus-resumable"] == TUS
        body = response.json()
        upload_id = body["upload_id"]
        assert len(upload_id) >= 24 and "/" not in upload_id  # secrets.token_urlsafe
        assert response.headers["location"] == f"/api/projects/{project.id}/files/tus/{upload_id}"
        assert body["offset_bytes"] == 0
        assert body["chunk_max_bytes"] == 4096
        assert body["max_upload_bytes"] == 100000
        # The chunk file exists on disk before the first PATCH.
        assert os.path.exists(os.path.join(_upload_root(), upload_id, _DATA_NAME))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_creation_refuses_bad_metadata_and_size(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path, max_bytes=1000)
    owner = await history.add_user("tus-bad")
    project = await history.create_project(owner.id, "프로젝트", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        base = f"/api/projects/{project.id}/files/tus"
        missing = await client.post(base, headers={"Upload-Length": "10", "Tus-Resumable": TUS})
        assert missing.status_code == 422
        unsupported = await client.post(base, headers={
            "Upload-Length": "10",
            "Upload-Metadata": tus_metadata("메모.txt", "text/plain"),
            "Tus-Resumable": TUS,
        })
        assert unsupported.status_code == 422
        oversize = await client.post(base, headers={
            "Upload-Length": "1001",
            "Upload-Metadata": tus_metadata("큰파일.pdf", "application/pdf"),
            "Tus-Resumable": TUS,
        })
        assert oversize.status_code == 413
        assert "최대" in oversize.json()["error"]["message"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_head_patch_and_offset_mismatch(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await history.add_user("tus-patch")
    project = await history.create_project(owner.id, "프로젝트", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        created = await create_upload(client, project.id, name="보고서.pdf", media_type="application/pdf", length=10000)
        upload_id = created.json()["upload_id"]
        head = await client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert head.status_code == 200
        assert head.headers["upload-offset"] == "0"
        assert head.headers["upload-length"] == "10000"

        first = await patch_chunk(client, project.id, upload_id, 0, b"a" * 4096)
        assert first.status_code == 204
        assert first.headers["upload-offset"] == "4096"

        head = await client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert head.headers["upload-offset"] == "4096"

        wrong = await patch_chunk(client, project.id, upload_id, 0, b"b" * 16)
        assert wrong.status_code == 409
        assert wrong.json()["error"]["code"] == "offset_mismatch"
        head = await client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert head.headers["upload-offset"] == "4096"  # nothing was appended

        wrong_type = await client.patch(
            f"/api/projects/{project.id}/files/tus/{upload_id}",
            content=b"b" * 16,
            headers={"Upload-Offset": "4096", "Content-Type": "application/octet-stream", "Tus-Resumable": TUS},
        )
        assert wrong_type.status_code == 415
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_other_user_gets_a_plain_404(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await history.add_user("tus-owner")
    other = await history.add_user("tus-other")
    project = await history.create_project(owner.id, "비공개", "")
    owner_client = await client_with_session(app, user_profile(owner.id))
    other_client = await client_with_session(app, user_profile(other.id))
    try:
        created = await create_upload(owner_client, project.id, name="보고서.pdf", media_type="application/pdf", length=64)
        upload_id = created.json()["upload_id"]
        url = f"/api/projects/{project.id}/files/tus/{upload_id}"
        head = await other_client.head(url)
        assert head.status_code == 404
        patch = await patch_chunk(other_client, project.id, upload_id, 0, b"x" * 8)
        assert patch.status_code == 404
        pickup = await other_client.get(url)
        assert pickup.status_code == 404
    finally:
        await owner_client.aclose()
        await other_client.aclose()


@pytest.mark.asyncio
async def test_tus_chunk_over_cap_refused_before_appending(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path, chunk_bytes=1024)
    owner = await history.add_user("tus-cap")
    project = await history.create_project(owner.id, "프로젝트", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        created = await create_upload(client, project.id, name="보고서.pdf", media_type="application/pdf", length=4096)
        upload_id = created.json()["upload_id"]
        too_big = await patch_chunk(client, project.id, upload_id, 0, b"x" * 2048)
        assert too_big.status_code == 413
        assert too_big.json()["error"]["code"] == "chunk_too_large"
        head = await client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert head.headers["upload-offset"] == "0"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_disconnect_resume_completes_into_the_save_flow(monkeypatch, tmp_path):
    """끊었다 이어 올리기: 새 접속이 HEAD로 위치를 확인하고 남은 조각부터 다시 보낸다."""
    app, history, store = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await history.add_user("tus-resume")
    project = await history.create_project(owner.id, "이어올리기", "")
    payload = PNG_MAGIC + bytes(range(256)) * 44  # 11264 + 8 bytes of image-ish data
    first_client = await client_with_session(app, user_profile(owner.id))
    created = await create_upload(first_client, project.id, name="스캔.png", media_type="image/png", length=len(payload))
    upload_id = created.json()["upload_id"]
    first = await patch_chunk(first_client, project.id, upload_id, 0, payload[:4096])
    assert first.status_code == 204
    await first_client.aclose()  # 접속 끊김

    second_client = await client_with_session(app, user_profile(owner.id))
    try:
        head = await second_client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
        offset = int(head.headers["upload-offset"])
        assert offset == 4096
        while offset < len(payload):
            take = min(4096, len(payload) - offset)
            second = await patch_chunk(second_client, project.id, upload_id, offset, payload[offset:offset + take])
            assert second.status_code == 204
            offset = int(second.headers["upload-offset"])
        assert offset == len(payload)

        done = await second_client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert done.headers["x-padiem-upload-complete"] == "1"

        # PATCH after completion is refused; the result is picked up exactly once.
        late = await patch_chunk(second_client, project.id, upload_id, len(payload), b"")
        assert late.status_code == 409
        assert late.json()["error"]["code"] == "upload_completed"
        pickup = await second_client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert pickup.status_code == 201, pickup.json()
        file_row = pickup.json()["file"]
        assert file_row["name"] == "스캔.png"
        assert file_row["media_type"] == "image/png"
        rows = await store.list_files(owner.id, project.id)
        assert len(rows) == 1 and rows[0].id == file_row["id"]
        bucket = app.state.workspace_document_store.r2_bucket
        key = f"projects/{owner.id}/{project.id}/originals/{file_row['id']}"
        assert bucket.objects[key] == hashlib.sha256(payload).hexdigest()
        # One-time pickup: the temp chunks are gone and the URL reads as missing.
        assert not os.path.exists(os.path.join(_upload_root(), upload_id))
        again = await second_client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert again.status_code == 404
    finally:
        await second_client.aclose()


@pytest.mark.asyncio
async def test_tus_finalize_validation_failure_surfaces_on_pickup(monkeypatch, tmp_path):
    """합치기 후 저장 흐름이 거절하면(형식 불일치) GET 결과가 그 안내를 그대로 전한다."""
    app, history, store = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await history.add_user("tus-invalid")
    project = await history.create_project(owner.id, "형식불일치", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        junk = b"this-is-not-a-png-file" * 4
        created = await create_upload(client, project.id, name="가짜.png", media_type="image/png", length=len(junk))
        upload_id = created.json()["upload_id"]
        done = await patch_chunk(client, project.id, upload_id, 0, junk)
        assert done.status_code == 204  # tus append itself succeeded; the save flow refused the bytes
        late = await patch_chunk(client, project.id, upload_id, len(junk), b"")
        assert late.status_code == 409
        pickup = await client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert pickup.status_code == 422
        body = pickup.json()["error"]
        assert body["code"] == "invalid_document"
        assert "이미지 형식" in body["message"]
        assert await store.list_files(owner.id, project.id) == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_incomplete_upload_expires_and_is_swept(monkeypatch, tmp_path):
    app, history, _ = make_app(monkeypatch, tmp_path, cleanup_seconds=3600)
    owner = await history.add_user("tus-expire")
    project = await history.create_project(owner.id, "만료", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        created = await create_upload(client, project.id, name="오래된.pdf", media_type="application/pdf", length=64)
        upload_id = created.json()["upload_id"]
        directory = os.path.join(_upload_root(), upload_id)
        stale = time.time() - 7200
        os.utime(os.path.join(directory, _META_NAME), (stale, stale))
        removed = sweep_expired_uploads()
        assert removed >= 1
        assert not os.path.exists(directory)
        head = await client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert head.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.skipif(
    not os.environ.get("PADIEM_TUS_LOCAL_250MB"),
    reason="로컬 250MB 이어 올리기 실증 — PADIEM_TUS_LOCAL_250MB=1 로 실행(1회 실증용)",
)
@pytest.mark.asyncio
async def test_250mb_dummy_disconnect_resume(monkeypatch, tmp_path):
    """250MB 더미 파일 끊었다 이어 올리기 1회 — 90MB 기본 조각 3번(90+90+70)."""
    total = 250 * 1024 * 1024
    app, history, store = make_app(monkeypatch, tmp_path)
    owner = await history.add_user("tus-250mb")
    project = await history.create_project(owner.id, "대용량", "")

    payload = bytearray(total)
    block = os.urandom(1024 * 1024)
    for i in range(0, total, len(block)):
        payload[i:i + len(block)] = block[:min(len(block), total - i)]
    payload[0:8] = PNG_MAGIC
    digest = hashlib.sha256(bytes(payload[:len(payload)])).hexdigest()

    client = await client_with_session(app, user_profile(owner.id))
    try:
        created = await create_upload(client, project.id, name="더미.png", media_type="image/png", length=total)
        assert created.status_code == 201
        upload_id = created.json()["upload_id"]
        chunk_max = created.json()["chunk_max_bytes"]
        assert chunk_max == 90 * 1024 * 1024

        offset = 0
        requests = 0
        while offset < total:
            take = min(chunk_max, total - offset)
            response = await patch_chunk(client, project.id, upload_id, offset, bytes(payload[offset:offset + take]))
            assert response.status_code == 204
            offset = int(response.headers["upload-offset"])
            requests += 1
            if requests == 1:
                # 접속이 끊긴 것처럼 새 클라이언트로 갈아탄다.
                await client.aclose()
                client = await client_with_session(app, user_profile(owner.id))
                head = await client.head(f"/api/projects/{project.id}/files/tus/{upload_id}")
                assert int(head.headers["upload-offset"]) == offset
        assert requests >= 3

        pickup = await client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert pickup.status_code == 201, pickup.json()
        file_row = pickup.json()["file"]
        bucket = app.state.workspace_document_store.r2_bucket
        key = f"projects/{owner.id}/{project.id}/originals/{file_row['id']}"
        assert bucket.objects[key] == digest
        rows = await store.list_files(owner.id, project.id)
        assert len(rows) == 1 and rows[0].id == file_row["id"]
    finally:
        await client.aclose()


OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _hwpx_zip(*paragraphs: str) -> bytes:
    body = "".join(
        f"<hp:p><hp:runs><hp:t>{text}</hp:t></hp:runs></hp:p>" for text in paragraphs
    )
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        f"{body}</hs:sec>"
    ).encode("utf-8")
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("Contents/section1.xml", section)
    return output.getvalue()


@pytest.mark.asyncio
async def test_tus_completion_refuses_ole_legacy_hwp_with_one_guidance(monkeypatch, tmp_path):
    """#6126 tus 완료 지점: OLE2 .hwp는 합치기 직후 한 문장 안내로 거절된다."""
    app, history, store = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await history.add_user("tus-legacy-hwp")
    project = await history.create_project(owner.id, "구형한글", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        payload = OLE_MAGIC + b"\x00" * 64
        created = await create_upload(client, project.id, name="작년 축사.hwp",
                                      media_type="application/hwp+zip", length=len(payload))
        upload_id = created.json()["upload_id"]
        done = await patch_chunk(client, project.id, upload_id, 0, payload)
        assert done.status_code == 204
        pickup = await client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert pickup.status_code == 422, pickup.json()
        body = pickup.json()["error"]
        assert body["code"] == "invalid_document"
        assert body["message"] == guidance_for_reason_code(
            "legacy_hwp_unsupported", "application/hwp+zip")
        assert await store.list_files(owner.id, project.id) == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_tus_completion_reads_a_mislabeled_real_hwpx_as_hwpx(monkeypatch, tmp_path):
    """#6126 tus 완료 지점: ZIP 바이트의 .hwp는 HWPX로 읽히고 원래 이름을 유지한다."""
    app, history, store = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await history.add_user("tus-hwp-as-hwpx")
    project = await history.create_project(owner.id, "위장HWPX", "")
    client = await client_with_session(app, user_profile(owner.id))
    try:
        payload = _hwpx_zip("HWPX로 저장한 첫 문단", "둘째 문단")
        created = await create_upload(client, project.id, name="보고서.hwp",
                                      media_type="application/hwp+zip", length=len(payload))
        upload_id = created.json()["upload_id"]
        done = await patch_chunk(client, project.id, upload_id, 0, payload)
        assert done.status_code == 204
        pickup = await client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert pickup.status_code == 201, pickup.json()
        file_row = pickup.json()["file"]
        assert file_row["name"] == "보고서.hwp"
        assert file_row["media_type"] == "extracted/hwpx"
        rows = await store.list_files(owner.id, project.id)
        assert len(rows) == 1
        assert "HWPX로 저장한 첫 문단" in rows[0].content_text
        assert "둘째 문단" in rows[0].content_text
    finally:
        await client.aclose()
