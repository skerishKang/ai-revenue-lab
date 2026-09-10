from __future__ import annotations

import io
from io import BytesIO
import json
import zipfile
from base64 import b64encode

import httpx
import pytest
from pypdf import PdfWriter, PdfReader

from app.auth import SESSION_COOKIE, create_session_token
from app.binary_documents import parse_binary_document_item, BinaryDocumentValidationError
from app.config import Settings
from app.documents import DocumentValidationError
from app.history import ProjectProfile, UserProfile
from app.main import create_app
from app.project_files import (
    BINARY_PROJECT_FILE_MEDIA,
    D1ProjectFileStore,
    ProjectFileLimitError,
    ProjectFileRecord,
    _extracted_media_type,
)

SESSION_SECRET = "phase11-binary-project-session-secret-not-a-real-key-00000"

PDF_MEDIA = "application/pdf"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def settings(*, runtime="mock", web_provider="off"):
    values = {
        "runtime_mode": runtime,
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "phase11.apps.googleusercontent.com",
        "google_client_secret": "unit-test-secret",
        "session_secret": SESSION_SECRET,
        "session_max_age_seconds": 3600,
        "web_provider": web_provider,
    }
    if runtime == "b14":
        values["b14_base_url"] = "https://b14.example"
    return Settings.from_values(**values)


def user_profile(uid="usr_test", email="u@example.test"):
    return UserProfile(uid, email, "테스터", "")


def project_profile(uid, pid, name="자료실"):
    return ProjectProfile(pid, name, "쉽게 설명해줘", uid, uid)


class MemoryProjectStore:
    def __init__(self):
        self.users: dict[str, UserProfile] = {}
        self.projects: dict[str, dict] = {}

    async def upsert_google_user(self, subject, email, name, picture):
        uid = "usr_" + subject[:32].ljust(32, "0")
        profile = UserProfile(uid, email, name or email, picture)
        self.users[uid] = profile
        return profile

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def add_user(self, marker: str):
        return await self.upsert_google_user(marker, f"{marker}@example.test", marker, "")

    async def list_projects(self, user_id):
        rows = [row for row in self.projects.values() if row["user_id"] == user_id]
        rows.sort(key=lambda row: row["profile"].updated_at, reverse=True)
        return [row["profile"] for row in rows]

    async def get_project(self, user_id, project_id):
        row = self.projects.get(project_id)
        if row is None or row["user_id"] != user_id:
            return None
        return row["profile"]

    async def create_project(self, user_id, name, instructions):
        pid = "proj_" + "2" * 32
        self.projects[pid] = {"user_id": user_id, "profile": project_profile(user_id, pid, name)}
        return self.projects[pid]["profile"]

    async def update_project(self, user_id, project_id, name, instructions):
        row = self.projects[project_id]
        row["profile"] = ProjectProfile(project_id, name or row["profile"].name, instructions or "", "t1", "t1")
        return row["profile"]

    async def delete_project(self, user_id, project_id):
        row = self.projects.pop(project_id, None)
        return row is not None and row["user_id"] == user_id


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

    async def create_file(self, user_id, project_id, name, media_type, text, *, source_media_type=None):
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


def _make_docx_base64() -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>Hello from DOCX</w:t></w:p></w:body></w:document>',
        )
    return b64encode(buf.getvalue()).decode()


def _make_pdf_base64(*, text: str = "Positive PDF Text") -> str:
    # Minimal valid PDF-1.4 with extractable text via pypdf
    stream_content = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode("latin-1", errors="replace")
    objs = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >>>> >>"),
        (4, b"<< /Length " + str(len(stream_content)).encode() + b" >>\nstream\n" + stream_content + b"\nendstream"),
    ]
    pdf = BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = {}
    for num, data in objs:
        offsets[num] = pdf.tell()
        pdf.write(f"{num} 0 obj\n".encode())
        pdf.write(data)
        pdf.write(b"\nendobj\n")
    xref_offset = pdf.tell()
    pdf.write(b"xref\n0 5\n0000000000 65535 f \n")
    for i in range(1, 5):
        pdf.write(f"{offsets[i]:010d} 00000 n \n".encode())
    pdf.write(b"trailer\n<< /Size 5 /Root 1 0 R >>\n")
    pdf.write(b"startxref\n")
    pdf.write(f"{xref_offset}\n".encode())
    pdf.write(b"%%EOF\n")
    return b64encode(pdf.getvalue()).decode()


MAX_BINARY_PROJECT_FILE_BASE64_BYTES = 2 * 1024 * 1024


async def client_with_session(app, user: UserProfile):
    cfg = Settings.from_values(
        session_secret=SESSION_SECRET, auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="phase11.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
    )
    app.state.settings = cfg
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test")
    client.cookies.set(SESSION_COOKIE, create_session_token(cfg, user.id), domain="chat.example.test", path="/")
    return client


@pytest.mark.asyncio
async def test_text_project_file_create_unchanged():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-text")
    project = await history.create_project(owner.id, "텍스트 프로젝트", "")
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    try:
        response = await client.post(f"/api/projects/{project.id}/files", json={
            "name": "메모.txt", "media_type": "text/plain", "text": "안녕하세요"
        })
        assert response.status_code == 201
        data = response.json()["file"]
        assert data["media_type"] == "text/plain"
        assert data["name"] == "메모.txt"
    finally:
        await client.aclose()


def _make_empty_pdf_base64() -> str:
    # Minimal valid PDF with NO extractable text (empty content stream)
    stream_content = b""
    objs = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << >> >>"),
        (4, b"<< /Length 0 >>\nstream\n" + stream_content + b"\nendstream"),
    ]
    pdf = BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = {}
    for num, data in objs:
        offsets[num] = pdf.tell()
        pdf.write(f"{num} 0 obj\n".encode())
        pdf.write(data)
        pdf.write(b"\nendobj\n")
    xref_offset = pdf.tell()
    pdf.write(b"xref\n0 5\n0000000000 65535 f \n")
    for i in range(1, 5):
        pdf.write(f"{offsets[i]:010d} 00000 n \n".encode())
    pdf.write(b"trailer\n<< /Size 5 /Root 1 0 R >>\n")
    pdf.write(b"startxref\n")
    pdf.write(f"{xref_offset}\n".encode())
    pdf.write(b"%%EOF\n")
    return b64encode(pdf.getvalue()).decode()


@pytest.mark.asyncio
async def test_pdf_upload_rejected_when_no_extractable_text():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-pdf")
    project = await history.create_project(owner.id, "PDF 프로젝트", "")
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    try:
        response = await client.post(f"/api/projects/{project.id}/files", json={
            "name": "빈보고서.pdf", "media_type": PDF_MEDIA, "base64": _make_empty_pdf_base64()
        })
        assert response.status_code == 422
        assert "PDF" in response.json()["error"]["message"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_positive_pdf_upload_signed_in_owner_201():
    """CENTRAL FIX A: positive PDF with actual extractable text, signed-in owner, HTTP 201."""
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-pdf-positive")
    project = await history.create_project(owner.id, "PDF 양성 프로젝트", "")
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    try:
        response = await client.post(f"/api/projects/{project.id}/files", json={
            "name": "보고서.pdf", "media_type": PDF_MEDIA, "base64": _make_pdf_base64()
        })
        assert response.status_code == 201, response.json()
        data = response.json()["file"]
        assert data["media_type"] == "extracted/pdf"
        assert data["name"] == "보고서.pdf"
        files = await store.list_files(owner.id, project.id)
        assert len(files) == 1
        assert "Positive PDF Text" in files[0].content_text
        # Public-safe projection: no base64, no object keys
        payload = json.dumps(data, ensure_ascii=False)
        assert "base64" not in payload
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_docx_upload_extracts_text_persisted_as_extracted_docx():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-docx")
    project = await history.create_project(owner.id, "DOCX 프로젝트", "")
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    try:
        response = await client.post(f"/api/projects/{project.id}/files", json={
            "name": "문서.docx", "media_type": DOCX_MEDIA, "base64": _make_docx_base64()
        })
        assert response.status_code == 201, response.json()
        data = response.json()["file"]
        assert data["media_type"] == "extracted/docx"
        assert data["name"] == "문서.docx"
        files = await store.list_files(owner.id, project.id)
        assert len(files) == 1
        assert files[0].media_type == "extracted/docx"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unauthenticated_upload_denied():
    app = create_app(settings())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test")
    try:
        response = await client.post("/api/projects/proj_test/files", json={
            "name": "보고서.pdf", "media_type": PDF_MEDIA, "base64": _make_pdf_base64()
        })
        assert response.status_code in (401, 403, 503)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cross_owner_project_non_disclosing_404():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-cross")
    other = await history.add_user("other-cross")
    project = await history.create_project(owner.id, "비공개 프로젝트", "")
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    other_client = await client_with_session(app, user_profile(other.id))
    try:
        response = await other_client.post(f"/api/projects/{project.id}/files", json={
            "name": "보고서.pdf", "media_type": PDF_MEDIA, "base64": _make_pdf_base64()
        })
        assert response.status_code == 404
    finally:
        await other_client.aclose()


def test_malformed_base64_rejected():
    with pytest.raises((DocumentValidationError, ValueError)):
        parse_binary_document_item({"type": "document", "name": "x.pdf", "media_type": PDF_MEDIA, "base64": "NOT-VALID-BASE64!!!"})


def test_unsupported_media_rejected():
    with pytest.raises(BinaryDocumentValidationError):
        parse_binary_document_item({"type": "document", "name": "x.exe", "media_type": "application/x-msdownload", "base64": _make_pdf_base64()})


def test_extension_magic_mismatch_rejected():
    with pytest.raises(BinaryDocumentValidationError):
        parse_binary_document_item({"type": "document", "name": "x.pdf", "media_type": DOCX_MEDIA, "base64": _make_pdf_base64()})


def test_oversized_base64_rejected_413():
    oversized = b64encode(b"x" * (2 * 1024 * 1024 + 100)).decode()
    item = {"name": "big.pdf", "media_type": PDF_MEDIA, "base64": oversized}
    from app.project_file_routes import _parse_project_file_item
    with pytest.raises(ValueError):
        _parse_project_file_item(item)


@pytest.mark.asyncio
async def test_projection_contains_no_base64_secrets():
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-proj")
    project = await history.create_project(owner.id, "프로젝트", "")
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    try:
        response = await client.post(f"/api/projects/{project.id}/files", json={
            "name": "문서.docx", "media_type": DOCX_MEDIA, "base64": _make_docx_base64()
        })
        assert response.status_code == 201
        payload = json.dumps(response.json(), ensure_ascii=False)
        assert "base64" not in payload
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_oversized_route_level_413():
    """CENTRAL FIX B: route-level actual HTTP request, verified 413."""
    store = MemoryProjectFileStore()
    history = MemoryProjectStore()
    owner = await history.add_user("owner-oversize")
    project = await history.create_project(owner.id, "프로젝트", "")
    cfg = settings()
    app = create_app(cfg, history_store=history, project_file_store=store)
    client = await client_with_session(app, user_profile(owner.id))
    try:
        oversized = b64encode(b"x" * (MAX_BINARY_PROJECT_FILE_BASE64_BYTES + 1)).decode()
        response = await client.post(f"/api/projects/{project.id}/files", json={
            "name": "big.pdf", "media_type": PDF_MEDIA, "base64": oversized
        })
        assert response.status_code == 413, f"expected 413 got {response.status_code}: {response.json()}"
    finally:
        await client.aclose()


def test_extracted_media_type_helper():
    assert _extracted_media_type("application/pdf") == "extracted/pdf"
    assert _extracted_media_type(DOCX_MEDIA) == "extracted/docx"


def test_binary_project_file_media_contains_pdf_docx():
    assert PDF_MEDIA in BINARY_PROJECT_FILE_MEDIA
    assert DOCX_MEDIA in BINARY_PROJECT_FILE_MEDIA