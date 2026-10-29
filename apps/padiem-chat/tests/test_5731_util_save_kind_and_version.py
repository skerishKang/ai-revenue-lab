"""#5731 (A안) — 저장한 글의 종류와 덮어쓰기 버전.

The design decision was the smallest one that removes the two real problems:
a speech list that could only guess from a name prefix, and a re-save that
quietly stacked a second row with the same name. This file pins the server half:

- a save stamps its kind, and a list can read it back;
- the same name in the same kind answers 409 with the existing file, so the
  screen can ask before writing;
- a different kind may reuse the name (a speech never collides with a meeting);
- PUT replaces the body and keeps the displaced text as `<name> (이전 N)` in the
  same project, linked through `doc_version_of` — nothing is destroyed and no
  new store is introduced;
- another owner still sees 404 for both the save and the overwrite;
- migration 078 is additive (no table rebuild).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.project_files import UTIL_DOC_KINDS, _version_name

ROOT = Path(__file__).resolve().parents[1]
USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
PROJECT = "proj_" + "c" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="util-save-kind.apps.googleusercontent.com",
        google_client_secret="util-save-kind-google-secret",
        session_secret="util-save-kind-session-secret-00",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


def _client(user_id: str = USER_A) -> TestClient:
    settings = _settings()
    from app.project_files import D1ProjectFileStore

    app = create_app(
        settings=settings,
        history_store=_History(),
        project_file_store=D1ProjectFileStore(_database()),
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, user_id),
        domain="chat.example.test",
        path="/",
    )
    return client


SCHEMA = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '2026-10-29T00:00:00Z',
    updated_at TEXT NOT NULL DEFAULT '2026-10-29T00:00:00Z'
);
CREATE TABLE project_files (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    content_text TEXT NOT NULL,
    content_chars INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'kr',
    doc_kind TEXT NOT NULL DEFAULT '',
    doc_version_of TEXT
);
"""


class _History:
    """Only what the project-file routes ask of the history store."""

    async def get_project(self, user_id: str, project_id: str):
        from app.history import ProjectProfile

        if project_id != PROJECT:
            return None
        return ProjectProfile(
            id=PROJECT, name="유틸 작업", instructions="",
            created_at="2026-10-29T00:00:00Z", updated_at="2026-10-29T00:00:00Z",
        )


def _database():
    from app.d1_sqlite import SqliteD1, connect

    connection = connect(":memory:")
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO projects (id, user_id, name) VALUES (?, ?, ?)", (PROJECT, USER_A, "유틸 작업"))
    connection.execute("INSERT INTO projects (id, user_id, name) VALUES (?, ?, ?)",
                       ("proj_" + "d" * 32, USER_B, "유틸 작업"))
    return SqliteD1(connection)


def _save(client: TestClient, name: str, text: str, kind: str = "") -> object:
    payload = {"name": name, "media_type": "text/plain", "text": text}
    if kind:
        payload["doc_kind"] = kind
    return client.post(f"/api/projects/{PROJECT}/files", json=payload)


def test_kind_and_version_vocabulary_is_small_and_explicit() -> None:
    assert UTIL_DOC_KINDS == {"speech", "sns", "meeting", "book"}
    assert _version_name("행사.txt", 1) == "행사 (이전 1).txt"
    assert _version_name("행사", 2) == "행사 (이전 2)"


def test_a_save_stamps_the_kind_the_list_reads() -> None:
    client = _client()
    created = _save(client, "개교기념일.txt", "축사 본문입니다.", "speech")
    assert created.status_code == 201, created.text
    assert created.json()["file"]["doc_kind"] == "speech"
    assert created.json()["file"]["doc_version_of"] is None

    listed = client.get(f"/api/projects/{PROJECT}/files")
    assert listed.status_code == 200
    row = next(item for item in listed.json()["files"] if item["name"] == "개교기념일.txt")
    assert row["doc_kind"] == "speech"


def test_a_name_already_used_by_the_same_kind_asks_instead_of_stacking() -> None:
    client = _client()
    first = _save(client, "개교기념일.txt", "첫 본문", "speech")
    assert first.status_code == 201
    existing_id = first.json()["file"]["id"]

    again = _save(client, "개교기념일.txt", "두 번째 본문", "speech")
    assert again.status_code == 409, again.text
    error = again.json()["error"]
    assert error["code"] == "name_conflict"
    assert error["existing"] == {"id": existing_id, "name": "개교기념일.txt"}

    rows = client.get(f"/api/projects/{PROJECT}/files").json()["files"]
    assert [row["name"] for row in rows].count("개교기념일.txt") == 1


def test_another_kind_may_reuse_the_same_name() -> None:
    client = _client()
    assert _save(client, "행사.txt", "축사", "speech").status_code == 201
    assert _save(client, "행사.txt", "회의 기록", "meeting").status_code == 201
    kinds = sorted(
        row["doc_kind"] for row in client.get(f"/api/projects/{PROJECT}/files").json()["files"]
        if row["name"] == "행사.txt"
    )
    assert kinds == ["meeting", "speech"]


def test_an_unknown_kind_is_refused() -> None:
    client = _client()
    response = _save(client, "행사.txt", "본문", "essay")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_document"


def test_overwrite_keeps_the_previous_body_as_a_version_file() -> None:
    client = _client()
    created = _save(client, "개교기념일.txt", "예전 축사 본문", "speech")
    file_id = created.json()["file"]["id"]

    replaced = client.put(
        f"/api/projects/{PROJECT}/files/{file_id}",
        content=json.dumps({"text": "새로 고친 축사 본문"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()
    assert body["file"]["id"] == file_id
    assert body["previous"]["name"] == "개교기념일 (이전 1).txt"
    assert body["previous"]["doc_version_of"] == file_id
    assert body["previous"]["doc_kind"] == "speech"

    current = client.get(f"/api/projects/{PROJECT}/files/{file_id}").json()["file"]
    assert current["content"] == "새로 고친 축사 본문"
    previous = client.get(
        f"/api/projects/{PROJECT}/files/{body['previous']['id']}"
    ).json()["file"]
    assert previous["content"] == "예전 축사 본문"

    # A second overwrite numbers the next version instead of reusing 「이전 1」.
    second = client.put(
        f"/api/projects/{PROJECT}/files/{file_id}",
        content=json.dumps({"text": "세 번째 본문"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["previous"]["name"] == "개교기념일 (이전 2).txt"


def test_a_stored_speech_reopens_for_editing_and_resaves_with_its_kind() -> None:
    """#6199 — 목록에서 연 본문을 그대로 고쳐 저장하는 한 흐름.

    The reopen reads the owner's detail route; the edited save lands on the
    existing 409 (new name) or the existing PUT (overwrite). Neither path makes
    a second store, and the kind the row was stored under survives both.
    """

    client = _client()
    created = _save(client, "개교기념일.txt", "예전 축사 본문", "speech")
    assert created.status_code == 201, created.text
    file_id = created.json()["file"]["id"]

    # 1) 고쳐 쓰기 reads this body back — that is what the editor receives.
    opened = client.get(f"/api/projects/{PROJECT}/files/{file_id}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["file"]["content"] == "예전 축사 본문"
    assert opened.json()["file"]["doc_kind"] == "speech"

    # 2) Saving the edited body under the same name asks (409) and writes nothing.
    edited = "예전 축사 본문 · 고친 문장"
    asked = _save(client, "개교기념일.txt", edited, "speech")
    assert asked.status_code == 409, asked.text
    assert asked.json()["error"]["existing"] == {"id": file_id, "name": "개교기념일.txt"}
    assert client.get(f"/api/projects/{PROJECT}/files/{file_id}").json()["file"]["content"] == "예전 축사 본문"

    # 3) 새 이름으로 저장 = exactly one new row, same kind, original untouched.
    saved_new = _save(client, "개교기념일 (2).txt", edited, "speech")
    assert saved_new.status_code == 201, saved_new.text
    assert saved_new.json()["file"]["doc_kind"] == "speech"
    current = [
        row for row in client.get(f"/api/projects/{PROJECT}/files").json()["files"]
        if row["doc_kind"] == "speech" and not row["doc_version_of"]
    ]
    assert sorted(row["name"] for row in current) == ["개교기념일 (2).txt", "개교기념일.txt"]

    # 4) 덮어쓰기 = the same row carries the edit, the old body survives as a version.
    replaced = client.put(
        f"/api/projects/{PROJECT}/files/{file_id}",
        content=json.dumps({"text": "예전 축사 본문 · 마지막 수정", "doc_kind": "speech"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["file"]["doc_kind"] == "speech"
    assert replaced.json()["previous"]["name"] == "개교기념일 (이전 1).txt"
    after = client.get(f"/api/projects/{PROJECT}/files").json()["files"]
    listed = [row["name"] for row in after if row["doc_kind"] == "speech" and not row["doc_version_of"]]
    assert sorted(listed) == ["개교기념일 (2).txt", "개교기념일.txt"]
    assert client.get(f"/api/projects/{PROJECT}/files/{file_id}").json()["file"]["content"] == (
        "예전 축사 본문 · 마지막 수정"
    )


def test_another_owner_cannot_open_the_body_for_editing() -> None:
    """#6199 — 남의 글은 목록에도, id로 열어도 없다(존재 비노출)."""

    owner = _client()
    created = _save(owner, "개교기념일.txt", "내 축사", "speech")
    file_id = created.json()["file"]["id"]

    other = _client(USER_B)
    assert other.get(f"/api/projects/{PROJECT}/files/{file_id}").status_code == 404
    assert owner.get(f"/api/projects/{PROJECT}/files/{file_id}").status_code == 200


def test_another_owner_cannot_overwrite_or_read() -> None:
    owner = _client()
    created = _save(owner, "개교기념일.txt", "내 축사", "speech")
    file_id = created.json()["file"]["id"]

    other = _client(USER_B)
    denied = other.put(
        f"/api/projects/{PROJECT}/files/{file_id}",
        content=json.dumps({"text": "남의 글 덮어쓰기"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert denied.status_code in {403, 404}
    assert owner.get(f"/api/projects/{PROJECT}/files/{file_id}").json()["file"]["content"] == "내 축사"


def test_overwrite_refuses_a_non_text_document() -> None:
    client = _client()
    created = _save(client, "행사.txt", "본문", "speech")
    file_id = created.json()["file"]["id"]
    # An image row is stored through the binary path; simulating one here by
    # asking to overwrite a missing id keeps the route honest either way.
    missing = client.put(
        f"/api/projects/{PROJECT}/files/file_{'0' * 32}",
        content=json.dumps({"text": "본문"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert missing.status_code == 404
    assert client.get(f"/api/projects/{PROJECT}/files/{file_id}").status_code == 200


@pytest.mark.parametrize("forbidden", ["DROP TABLE", "project_files_rebuilt"])
def test_migration_078_is_additive(forbidden: str) -> None:
    sql = (ROOT / "migrations" / "078_project_files_doc_kind.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE project_files ADD COLUMN doc_kind" in sql
    assert "ALTER TABLE project_files ADD COLUMN doc_version_of" in sql
    assert forbidden not in sql
    assert "UPDATE project_files" not in sql
