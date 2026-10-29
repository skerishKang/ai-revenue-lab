"""#5783 G5 — 세 탭(축사·SNS·회의정리)의 작성→저장→다시 열기→고쳐 쓰기→내보내기.

The tracker's G5 asks for one integrated pass over the three util tools, not a
new product surface. This module reuses the existing machinery:

- ``tests/_5785_util_harness.js`` runs the shipped ``static/util-menu.js``
  against the recording fake of the existing endpoints (``/api/chat``,
  ``/api/projects``, ``/api/projects/{id}/files``) and a fake DOM.
- a fake D1 (``SqliteD1``) backs the real project-file routes for the
  account-isolation half.

What is pinned here, per tool:

1. 작성 — the generated draft reaches the editable output through ``/api/chat``;
2. 저장 — the row is stored under the tool's own name and ``doc_kind``;
3. 다시 열기 — the stored body comes back into that same editor;
4. 고쳐 쓰기 — the same-name save answers 409 and the screen asks; both choices
   keep the kind, and the overwrite keeps the displaced body as a version;
5. 내보내기 — the download hands the browser a real file name, a UTF-8 text
   type and the exact current draft.

The account half uses two sessions over one fake D1: the other account sees 404
for the owner's file id and cannot overwrite it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from _5785_util_runner import run
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.d1_sqlite import SqliteD1, connect
from app.project_files import D1ProjectFileStore

ANSWER = "생성된 초안 본문입니다.\n\n두 번째 문단입니다."
SPEECH_NAME = "가을 문화제 축사.txt"
SNS_TITLE = "블로그 게시글"
SNS_NAME = "블로그 게시글.txt"
MEETING_NAME = "가을 주민 간담회.txt"
TEXT_TYPE = "text/plain;charset=utf-8"


@pytest.fixture(scope="module")
def g5() -> dict:
    return run("g5")


# ── 축사 ─────────────────────────────────────────────────────────────────────


def test_speech_writes_saves_reopens_rewrites_and_exports(g5: dict) -> None:
    speech = g5["speech"]
    assert speech["generated"] == ANSWER
    assert speech["firstSavedName"] == SPEECH_NAME
    assert speech["firstSavedKind"] == "speech"

    assert speech["reopened"] == ANSWER + "\n[편집: 저장 전]"
    assert SPEECH_NAME in speech["editState"]
    assert "덮어쓰기" in speech["editState"] and "버전" in speech["editState"]

    assert speech["askText"] == "같은 이름의 글이 이미 있습니다: " + SPEECH_NAME
    assert speech["askLabels"][0].startswith("새 이름으로 저장")
    assert speech["askLabels"][1].startswith("덮어쓰기")

    assert speech["overwrittenBody"] == speech["reopened"] + "\n[편집: 고쳐 쓰기]"
    assert speech["overwrittenKind"] == "speech"
    assert len(speech["versions"]) == 1
    version = speech["versions"][0]
    assert version["name"] == "가을 문화제 축사 (이전 1).txt"
    assert version["doc_kind"] == "speech"
    assert version["content"] == speech["reopened"]

    assert speech["export"] == {
        "filename": "speech.txt",
        "type": TEXT_TYPE,
        "content": speech["overwrittenBody"],
    }


# ── SNS ──────────────────────────────────────────────────────────────────────


def test_sns_writes_saves_reopens_rewrites_and_exports(g5: dict) -> None:
    sns = g5["sns"]
    assert sns["generated"] == ANSWER
    assert sns["title"] == SNS_TITLE
    assert sns["firstSavedName"] == SNS_NAME
    assert sns["firstSavedKind"] == "sns"

    assert sns["reopened"] == ANSWER + "\n#가을축제"
    assert SNS_NAME in sns["editState"]

    assert sns["askText"] == "같은 이름의 글이 이미 있습니다: " + SNS_NAME
    assert sns["askLabels"][0].startswith("새 이름으로 저장")
    assert sns["askLabels"][1].startswith("덮어쓰기")

    # 새 이름으로 저장: one new row in the same kind, the original untouched.
    assert sns["storedNames"] == [SNS_NAME, "블로그 게시글 (2).txt"]
    assert sns["originalBody"] == sns["reopened"]

    assert sns["export"] == {
        "filename": "sns-blog.txt",
        "type": TEXT_TYPE,
        "content": sns["reopened"] + "\n#고쳐쓰기",
    }


# ── 회의정리 ────────────────────────────────────────────────────────────────


def test_meeting_writes_saves_reopens_rewrites_and_exports(g5: dict) -> None:
    meeting = g5["meeting"]
    assert meeting["generated"] == ANSWER
    assert meeting["firstSavedName"] == MEETING_NAME
    assert meeting["firstSavedKind"] == "meeting"

    assert meeting["reopened"] == ANSWER + "\n[편집: 저장 전]"

    assert meeting["askText"] == "같은 이름의 글이 이미 있습니다: " + MEETING_NAME
    assert meeting["askLabels"][0].startswith("새 이름으로 저장")
    assert meeting["askLabels"][1].startswith("덮어쓰기")

    assert meeting["overwrittenBody"] == meeting["reopened"] + "\n[편집: 고쳐 쓰기]"
    assert meeting["overwrittenKind"] == "meeting"
    assert len(meeting["versions"]) == 1
    version = meeting["versions"][0]
    assert version["name"] == "가을 주민 간담회 (이전 1).txt"
    assert version["doc_kind"] == "meeting"
    assert version["content"] == meeting["reopened"]

    assert meeting["export"] == {
        "filename": "meeting.txt",
        "type": TEXT_TYPE,
        "content": meeting["overwrittenBody"],
    }


# ── three tabs together ─────────────────────────────────────────────────────


def test_all_three_tabs_use_the_existing_chat_route(g5: dict) -> None:
    assert g5["chatModes"] == ["auto", "auto", "auto"]


def test_each_tab_keeps_its_own_kind_and_its_own_rows(g5: dict) -> None:
    kinds = {}
    for row in g5["storedKinds"]:
        kinds.setdefault(row["doc_kind"], set()).add(row["name"])
    # The tool lists are separated by kind: exactly the rows each tool wrote.
    assert kinds["speech"] == {SPEECH_NAME}
    assert kinds["sns"] == {SNS_NAME, "블로그 게시글 (2).txt"}
    assert kinds["meeting"] == {MEETING_NAME}
    # Version rows exist but are history, not list items.
    assert g5["versionCount"] == 2
    # The SNS photo roster rides the same project-file store under its own row.
    assert any(row["name"] == "SNS 사진 구성.json" for row in g5["storedKinds"])


def test_the_chain_uses_only_the_existing_project_file_routes(g5: dict) -> None:
    allowed = {
        "GET /api/pc/pairings",
        "GET /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
        "POST /api/chat",
    }
    for endpoint in g5["endpoints"]:
        if endpoint in allowed:
            continue
        # Reopen/overwrite/roster cleanup are the existing single-file routes.
        assert endpoint.startswith(("GET /api/projects/p1/files/", "PUT /api/projects/p1/files/",
                                    "DELETE /api/projects/p1/files/")), endpoint
    assert g5["alerts"] == []
    assert g5["pageErrors"] == []


# ── account isolation on the real project-file routes + fake D1 ────────────

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
PROJECT_A = "proj_" + "c" * 32
PROJECT_B = "proj_" + "d" * 32

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

    def __init__(self, ownership: dict[str, str]) -> None:
        self._ownership = ownership

    async def get_project(self, user_id: str, project_id: str):
        from app.history import ProjectProfile

        if self._ownership.get(project_id) != user_id:
            return None
        return ProjectProfile(
            id=project_id, name="유틸 작업", instructions="",
            created_at="2026-10-29T00:00:00Z", updated_at="2026-10-29T00:00:00Z",
        )


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="util-g5.apps.googleusercontent.com",
        google_client_secret="util-g5-google-secret",
        session_secret="util-g5-session-secret-0000000000",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


def _shared_clients() -> dict[str, TestClient]:
    settings = _settings()
    connection = connect(":memory:")
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO projects (id, user_id, name) VALUES (?, ?, ?)",
                       (PROJECT_A, USER_A, "유틸 작업"))
    connection.execute("INSERT INTO projects (id, user_id, name) VALUES (?, ?, ?)",
                       (PROJECT_B, USER_B, "유틸 작업"))
    app = create_app(
        settings=settings,
        history_store=_History({PROJECT_A: USER_A, PROJECT_B: USER_B}),
        project_file_store=D1ProjectFileStore(SqliteD1(connection)),
    )
    clients = {}
    for user_id in (USER_A, USER_B):
        client = TestClient(app, base_url="https://chat.example.test")
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id),
            domain="chat.example.test",
            path="/",
        )
        clients[user_id] = client
    return clients


def _save(client: TestClient, project_id: str, name: str, text: str, kind: str):
    return client.post(
        f"/api/projects/{project_id}/files",
        json={"name": name, "media_type": "text/plain", "text": text, "doc_kind": kind},
    )


def test_another_account_cannot_open_the_stored_piece() -> None:
    clients = _shared_clients()
    created = _save(clients[USER_A], PROJECT_A, SPEECH_NAME, "내 축사 본문", "speech")
    assert created.status_code == 201, created.text
    file_id = created.json()["file"]["id"]

    # The other account's own project list never carries this row.
    other_list = clients[USER_B].get(f"/api/projects/{PROJECT_B}/files")
    assert other_list.status_code == 200
    assert all(row["name"] != SPEECH_NAME for row in other_list.json()["files"])

    # Opening the id directly is a 404, not an existence oracle.
    assert clients[USER_B].get(f"/api/projects/{PROJECT_A}/files/{file_id}").status_code == 404
    assert clients[USER_B].get(f"/api/projects/{PROJECT_B}/files/{file_id}").status_code == 404
    assert clients[USER_A].get(f"/api/projects/{PROJECT_A}/files/{file_id}").status_code == 200


def test_another_account_cannot_overwrite_or_delete_the_stored_piece() -> None:
    clients = _shared_clients()
    created = _save(clients[USER_A], PROJECT_A, SPEECH_NAME, "내 축사 본문", "speech")
    assert created.status_code == 201, created.text
    file_id = created.json()["file"]["id"]

    denied = clients[USER_B].put(
        f"/api/projects/{PROJECT_A}/files/{file_id}",
        content=json.dumps({"text": "남의 글 덮어쓰기", "doc_kind": "speech"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    assert denied.status_code in {403, 404}, denied.text
    assert clients[USER_B].delete(f"/api/projects/{PROJECT_A}/files/{file_id}").status_code in {403, 404}

    owner_body = clients[USER_A].get(f"/api/projects/{PROJECT_A}/files/{file_id}")
    assert owner_body.status_code == 200
    assert owner_body.json()["file"]["content"] == "내 축사 본문"
    assert owner_body.json()["file"]["doc_kind"] == "speech"