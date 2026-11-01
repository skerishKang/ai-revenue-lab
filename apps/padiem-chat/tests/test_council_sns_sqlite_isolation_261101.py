"""Council photo persistence and account fences on the real local COM2 stack."""
import base64
import json
import sqlite3

import pytest
from starlette.testclient import TestClient

from test_local_cpython import local_client  # noqa: F401 - real SQLite, disk R2 and ASGI
from test_5728_image_project_files import PNG_1x1


def _ok(response, status):
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


def test_local_migration_chain_keeps_068_069_photo_constraints(local_client, tmp_path):
    db = sqlite3.connect(tmp_path / "chat.sqlite3")
    migrations = {r[0] for r in db.execute("select name from padiem_local_migration_ledger")}
    assert "068_project_files_extracted_media.sql" in migrations
    assert "069_project_files_image_media.sql" in migrations
    sql = db.execute("select sql from sqlite_master where name='project_files'").fetchone()[0]
    for media in ("image/png", "image/jpeg", "image/webp", "extracted/pdf", "extracted/docx"):
        assert media in sql
    indexes = {r[1] for r in db.execute("pragma index_list(project_files)")}
    assert {"idx_project_files_owner_project", "idx_project_files_project_updated"} <= indexes
    insert = ("insert into project_files (id, project_id, user_id, name, media_type, "
              "content_text, content_chars, created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)")
    for index, media in enumerate(("image/png", "image/jpeg", "image/webp")):
        db.execute(insert, (str(index), "project", "user", "photo", media, "", 0, "t", "t"))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(insert, ("empty", "project", "user", "document", "text/plain", "", 0, "t", "t"))
    db.rollback()
    db.close()


@pytest.mark.parametrize("country", ["kr", "us", "uk", "fr"])
def test_photo_roster_and_account_isolation(local_client, country):
    app = local_client.app
    headers = {"Origin": "http://127.0.0.1:8773"}
    with TestClient(app, headers=headers) as other, TestClient(app, headers=headers) as reopened:
        owner = local_client
        _ok(owner.post("/api/auth/password/register", json={
            "email": "owner@example.test", "password": "test-password-1234"}), 200)
        _ok(other.post("/api/auth/password/register", json={
            "email": "other@example.test", "password": "test-password-5678"}), 200)
        project = _ok(owner.post("/api/projects", json={"name": "private-council"}), 201)["project"]
        pid = project["id"]
        root = f"/api/projects/{pid}/files"
        raw = base64.b64decode(PNG_1x1)
        photo = _ok(owner.post(root, content=raw, headers={
            "Content-Type": "application/octet-stream", "X-Padiem-Filename": "private-photo.png",
            "X-Padiem-Media-Type": "image/png"}), 201)["file"]
        assert photo["content_chars"] == 0
        photo_id = photo["id"]
        roster = json.dumps({"version": 2, "photos": [
            {"fileId": photo_id, "name": "private-photo.png", "position": "0"}],
            "draft": {"text": "private-roster-marker", "platform": "blog"}})
        ids = [photo_id]
        for name, media, text in [
            ("SNS 사진 구성.json", "application/json", roster),
            ("private-document.txt", "text/plain", "private-document-marker"),
            ("활동집 - private-book.txt", "text/plain", "private-book-marker")]:
            body = {"name": name, "media_type": media, "text": text, "country": country}
            ids.append(_ok(owner.post(root, json=body), 201)["file"]["id"])
        roster_id, document_id, book_id = ids[1:]
        preview = owner.get(f"{root}/{photo_id}/original")
        assert preview.status_code == 200 and preview.content == raw

        # A second session authenticates as A and reads persisted content and bytes.
        _ok(reopened.post("/api/auth/password/login", json={
            "identifier": "owner@example.test", "password": "test-password-1234"}), 200)
        restored = _ok(reopened.get(f"{root}/{roster_id}"), 200)["file"]["content"]
        assert json.loads(restored)["photos"][0]["fileId"] == photo_id
        assert reopened.get(f"{root}/{photo_id}/original").content == raw
        assert _ok(reopened.get(f"{root}/{book_id}"), 200)["file"]["content"] == "private-book-marker"

        # B can list its own project; guessing A's project or any A file is denied.
        bpid = _ok(other.post("/api/projects", json={"name": "other-project"}), 201)["project"]["id"]
        projects = _ok(other.get("/api/projects"), 200)["projects"]
        assert pid not in [p["id"] for p in projects] and bpid in [p["id"] for p in projects]
        assert other.get(f"/api/projects/{pid}").status_code == 404
        assert other.get(root, params={"country": country}).status_code == 404
        assert _ok(other.get(f"/api/projects/{bpid}/files", params={"country": country}), 200)["files"] == []
        for fid in ids:
            assert other.get(f"{root}/{fid}").status_code == 404
            assert other.get(f"/api/projects/{bpid}/files/{fid}").status_code == 404
        assert other.get(f"{root}/{photo_id}/original").status_code == 404
        assert other.get(f"/api/projects/{bpid}/files/{photo_id}/original").status_code == 404
        # This route searches conversations, not project files. Seed a real A
        # conversation with the same markers to provide a positive control.
        markers = ("private-document-marker", "private-book-marker", "private-roster-marker")
        stream = owner.post("/api/chat/stream", json={"messages": [
            {"role": "user", "content": " ".join(markers)}], "project_id": pid})
        assert stream.status_code == 200, stream.text
        for marker in markers:
            own_search = _ok(owner.get("/api/conversations/search", params={"q": marker}), 200)
            assert own_search["conversations"], marker
            search = _ok(other.get("/api/conversations/search", params={"q": marker}), 200)
            assert search["conversations"] == []

        assert owner.delete(f"{root}/{photo_id}").status_code == 204
        assert owner.get(f"{root}/{photo_id}/original").status_code == 404
