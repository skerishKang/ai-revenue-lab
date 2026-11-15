"""#7782 — a Library row opens its stored content read-only; the project action
lists the project's files.

Pinned here:
- the viewer reads only the shipped owner-scoped routes (detail for content,
  original for downloads); no second store, no new route, app.js gains nothing;
- the Library row click hands the row to the viewer seam, and the settings
  dialog seam (PadiemChatProjectOpener) is left exactly as it was;
- the viewer is read-only: it has no write call at all;
- the server already refuses a foreign file with 404 and an unsigned call with
  401 — the tests run the REAL D1 store against SQLite to keep that proof.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import project_file_routes
from app.project_file_routes import owner_files_collection, project_file_detail, project_file_original
from app.project_files import D1ProjectFileStore

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
LIBRARY_JS = (STATIC / "library.js").read_text(encoding="utf-8")
VIEWER_JS = (STATIC / "library-file-viewer.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
HARNESS = (Path(__file__).resolve().parent / "_util_library_open_harness.js").read_text(encoding="utf-8")

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
OWNER = "usr_" + "a" * 32
FOREIGN = "usr_" + "b" * 32
PROJECT = "proj_" + "1" * 32
FOREIGN_PROJECT = "proj_" + "9" * 32
STORED_TEXT = "존경하는 회원 여러분, 안녕하십니까.\n30주년 축사 초안입니다."


# ── wiring: the screen reuses the shipped seam, app.js gains nothing ────────


def test_the_row_hands_the_file_to_the_viewer_seam() -> None:
    assert "window.PadiemChatLibraryFiles" in LIBRARY_JS
    assert "onOpen: () => openStoredFile(file, label)" in LIBRARY_JS
    assert "action: { label: TEXT.open(), run: () => openProjectFiles(file) }" in LIBRARY_JS
    # The settings seam is retired from this surface, not rewired.
    assert "PadiemChatProjectOpener" not in LIBRARY_JS


def test_the_viewer_reads_only_the_shipped_owner_scoped_routes() -> None:
    for path in ("/api/saved-outputs", "/api/library", "/api/documents", "/api/files"):
        assert path not in VIEWER_JS, path
    assert "/files/" in VIEWER_JS and "/original" in VIEWER_JS
    # Read-only: no mutating verb exists in the viewer.
    for verb in ('method: "POST"', 'method: "PUT"', 'method: "DELETE"', 'method: "PATCH"'):
        assert verb not in VIEWER_JS, verb


def test_the_viewer_is_the_only_new_module_and_app_js_gains_nothing() -> None:
    assert '<script src="./library-file-viewer.js" defer></script>' in INDEX_HTML
    # app.js keeps the settings seam exactly as it was; the viewer lives elsewhere.
    assert "window.PadiemChatProjectOpener" in APP_JS
    assert "PadiemChatLibraryFiles" not in APP_JS


def test_the_viewer_styles_use_chat_tokens_and_stay_out_of_the_module() -> None:
    library_css = (STATIC / "library.css").read_text(encoding="utf-8")
    assert ".library-file-dialog" in library_css and ".library-files-dialog" in library_css
    assert "var(--radius-md)" in library_css and "var(--accent-strong)" in library_css
    # The module itself paints nothing: no inline colour, no hex, no radius.
    for token in ("style.color", "style.background", "#fff", "#000", "borderRadius"):
        assert token not in VIEWER_JS, token


# ── behaviour: the real library.js + viewer in a Node DOM shim ──────────────


def _run_harness(scenario: dict) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the library open harness"
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "library_open_harness.js"
        harness.write_text(HARNESS, encoding="utf-8")
        env = dict(os.environ)
        env["SCENARIO"] = json.dumps(scenario)
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "library.js"), str(STATIC / "library-file-viewer.js")],
            capture_output=True, text=True, encoding="utf-8", env=env, check=False,
        )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _assert_checks(result: dict, names) -> None:
    assert result["ok"] is True, {k: v for k, v in result["checks"].items() if not v}
    for name in names:
        assert result["checks"].get(name) is True, name


def test_behaviour_the_row_click_opens_the_stored_content() -> None:
    result = _run_harness({})
    _assert_checks(result, (
        "viewer_seam_published", "library_open", "library_listed_one_row",
        "row_present", "row_is_openable", "row_keeps_project_action",
        "row_click_reads_file_detail", "detail_read_is_same_origin",
        "viewer_dialog_open", "viewer_shows_stored_text",
        "viewer_has_copy_button", "settings_seam_untouched_after_row_click",
    ))


def test_behaviour_copy_and_download_carry_the_exact_stored_text() -> None:
    result = _run_harness({})
    _assert_checks(result, (
        "copy_button_label", "copy_hands_stored_text", "download_button_present",
        "download_built_one_blob", "download_blob_is_text_kind",
        "download_blob_holds_the_content",
    ))


def test_behaviour_a_failed_copy_is_reported_without_a_status_token() -> None:
    result = _run_harness({"copyResult": False})
    _assert_checks(result, ("copy_failure_is_reported",))


def test_behaviour_the_project_action_lists_the_projects_files() -> None:
    result = _run_harness({})
    _assert_checks(result, (
        "project_action_reads_file_list", "list_dialog_open",
        "list_shows_the_file", "settings_seam_never_called",
    ))


def test_behaviour_a_foreign_file_gets_an_honest_refusal() -> None:
    result = _run_harness({"detailStatus": 404})
    _assert_checks(result, (
        "foreign_file_reads_the_route", "foreign_file_shows_no_content",
        "foreign_file_is_honest",
    ))
    assert "존경하는 회원 여러분" not in result["text"]


def test_behaviour_a_failed_list_read_is_honest() -> None:
    result = _run_harness({"projectListStatus": 503})
    _assert_checks(result, ("list_failure_is_honest", "list_failure_shows_no_rows"))


# ── server side: the shipped routes already keep the owner scope ────────────


class D1Statement:
    def __init__(self, connection, sql, values=()):
        self.conn, self.sql, self.values = connection, sql, values

    def bind(self, *values):
        return D1Statement(self.conn, self.sql, values)

    async def first(self):
        row = self.conn.execute(self.sql, self.values).fetchone()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.values)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class D1Sqlite:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return D1Statement(self.connection, sql)


class _HistoryStub:
    """get_project is the route's project-ownership gate; the store keeps files."""

    def __init__(self, owned):
        self.owned = owned

    async def get_project(self, user_id: str, project_id: str):
        return {"id": project_id} if (user_id, project_id) in self.owned else None


def setup_database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    for name in (
        "001_auth_history.sql", "002_projects.sql", "003_project_files.sql",
        "068_project_files_extracted_media.sql", "069_project_files_image_media.sql",
        "075_project_files_country.sql", "077_project_files_text_byte_bound.sql",
        "078_project_files_doc_kind.sql", "083_project_files_hwpx.sql",
    ):
        db.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    for owner, subject in ((OWNER, "subject-owner-7782"), (FOREIGN, "subject-foreign-7782")):
        db.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (owner, "google", subject, f"{subject}@example.invalid", "2026-10-01", "2026-10-01"),
        )
    for project, owner, name in (
        (PROJECT, OWNER, "유틸"),
        (FOREIGN_PROJECT, FOREIGN, "남의 프로젝트"),
    ):
        db.execute(
            "INSERT INTO projects(id,user_id,name,instructions,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (project, owner, name, "", "2026-10-01", "2026-10-01"),
        )
    db.commit()
    return db


def build_request(store, history, *, path: str, method: str = "GET") -> Request:
    # /api/projects/{pid}/files/{fid} → parts: ['', 'api', 'projects', pid, 'files', fid]
    parts = path.split("/")
    params = {"project_id": parts[3] if len(parts) > 3 else ""}
    if len(parts) > 5:
        params["file_id"] = parts[5]
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "path_params": params,
        "query_string": b"",
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(
            project_file_store=store,
            history_store=history,
            settings=SimpleNamespace(auth_mode="google"),
        )),
    })


async def _detail(store, history, uid, path):
    with patch.object(project_file_routes, "current_user_id", return_value=uid), \
         patch.object(project_file_routes, "auth_ready", return_value=True):
        return await project_file_detail(build_request(store, history, path=path))


async def _original(store, history, uid, path):
    with patch.object(project_file_routes, "current_user_id", return_value=uid), \
         patch.object(project_file_routes, "auth_ready", return_value=True):
        return await project_file_original(build_request(store, history, path=path))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_the_owner_reads_back_the_exact_stored_content() -> None:
    async def scenario():
        db = setup_database()
        store = D1ProjectFileStore(D1Sqlite(db))
        created = await store.create_file(OWNER, PROJECT, "축사 초안 2026-11-14.txt", "text/plain", STORED_TEXT)
        history = _HistoryStub({(OWNER, PROJECT)})
        response = await _detail(store, history, OWNER, f"/api/projects/{PROJECT}/files/{created.id}")
        assert response.status_code == 200
        body = json.loads(bytes(response.body))
        assert body["file"]["content"] == STORED_TEXT
        assert body["file"]["name"] == "축사 초안 2026-11-14.txt"
        assert "content" in body["file"]
    _run(scenario())


def test_a_foreign_account_never_opens_another_owners_file() -> None:
    async def scenario():
        db = setup_database()
        store = D1ProjectFileStore(D1Sqlite(db))
        created = await store.create_file(OWNER, PROJECT, "축사 초안.txt", "text/plain", STORED_TEXT)
        history = _HistoryStub({(FOREIGN, FOREIGN_PROJECT), (OWNER, PROJECT)})
        # Same file id, foreign session: the project gate and the file gate both refuse.
        response = await _detail(store, history, FOREIGN, f"/api/projects/{PROJECT}/files/{created.id}")
        assert response.status_code == 404
        body = json.loads(bytes(response.body))
        assert body["error"]["code"] == "project_file_not_found"
        # A foreign project id on the owner's session is refused the same way.
        foreign_created = await store.create_file(FOREIGN, FOREIGN_PROJECT, "남의 파일.txt", "text/plain", "남의 내용")
        response2 = await _detail(store, history, OWNER, f"/api/projects/{FOREIGN_PROJECT}/files/{foreign_created.id}")
        assert response2.status_code == 404
    _run(scenario())


def test_an_unsigned_call_is_refused() -> None:
    async def scenario():
        db = setup_database()
        store = D1ProjectFileStore(D1Sqlite(db))
        created = await store.create_file(OWNER, PROJECT, "축사 초안.txt", "text/plain", STORED_TEXT)
        history = _HistoryStub({(OWNER, PROJECT)})
        with patch.object(project_file_routes, "current_user_id", return_value=None), \
             patch.object(project_file_routes, "auth_ready", return_value=True):
            response = await project_file_detail(build_request(store, history, path=f"/api/projects/{PROJECT}/files/{created.id}"))
        assert response.status_code == 401
    _run(scenario())


def test_the_original_route_stays_owner_scoped() -> None:
    async def scenario():
        db = setup_database()
        store = D1ProjectFileStore(D1Sqlite(db))
        created = await store.create_file(FOREIGN, FOREIGN_PROJECT, "남의 원본.txt", "text/plain", "남의 내용")
        history = _HistoryStub({(OWNER, PROJECT), (FOREIGN, FOREIGN_PROJECT)})
        response = await _original(store, history, OWNER, f"/api/projects/{FOREIGN_PROJECT}/files/{created.id}")
        assert response.status_code == 404
    _run(scenario())


def test_the_owner_list_excludes_other_accounts_rows() -> None:
    async def scenario():
        db = setup_database()
        store = D1ProjectFileStore(D1Sqlite(db))
        await store.create_file(OWNER, PROJECT, "내 파일.txt", "text/plain", STORED_TEXT)
        await store.create_file(FOREIGN, FOREIGN_PROJECT, "남의 파일.txt", "text/plain", "남의 내용")
        history = _HistoryStub({(OWNER, PROJECT), (FOREIGN, FOREIGN_PROJECT)})
        with patch.object(project_file_routes, "current_user_id", return_value=OWNER), \
             patch.object(project_file_routes, "auth_ready", return_value=True):
            response = await owner_files_collection(build_request(store, history, path="/api/project-files"))
        assert response.status_code == 200
        body = json.loads(bytes(response.body))
        names = [item["name"] for item in body["files"]]
        assert names == ["내 파일.txt"]
        # The list stays content-free; the viewer reads content per file.
        assert all("content" not in item and "text" not in item for item in body["files"])
    _run(scenario())


def test_the_file_list_separates_the_name_and_the_meta_line() -> None:
    """#7788 후속: 파일 이름과 설명("텍스트 · 695자")이 한 줄에 붙어 나오지 않는다.

    The row renders the name and the meta as two spans; the file-list sheet
    stacks them (block display in library.css), so the name and the meta read
    as two lines at 1440 and 390 widths alike.
    """
    library_css = (STATIC / "library.css").read_text(encoding="utf-8")
    assert ".library-file-list .library-item-title," in library_css
    assert ".library-file-list .library-item-meta" in library_css
    assert "display: block" in library_css

    result = _run_harness({})
    _assert_checks(result, ("list_dialog_open", "list_shows_the_file",
                            "list_row_title_meta_separated"))
    checks = result["checks"]
    assert checks.get("list_row_title_meta_separated") is True, checks
