"""#7501 — 축사·SNS·회의정리 결과를 라이브러리에 저장한다.

Pinned here:
- the save reuses the SHIPPED owner-scoped store: POST /api/projects/{pid}/files
  (the row the Library already lists through GET /api/project-files). No second
  store, no second route, no new server module;
- the button sits in the Util result panel (util-tools.js), disabled while the
  result is empty, and app.js gains nothing;
- the save lands in the Chat util's own pinned project "유틸" — the council app
  is a different site with its own project (#7501 후속), so a Chat util result
  never surfaces as that project in a Chat user's project list;
- the stored body is the result as it is shown, the stored title is
  "도구 이름 + 날짜", and the tool that made it is kept as doc_kind
  (speech / sns / meeting);
- one save failure sentence for any status, read from the Chat locale table in
  KR and EN instead of printing a status token.

The Node harness runs the REAL util-tools.js against a DOM shim and a fake
same-origin transport, so the disabled/enabled rule, the project read, the
request method/path/body, the success sentence, the failure sentence and the
409 retry are executed rather than grepped.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOOLS_JS = (STATIC / "util-tools.js").read_text(encoding="utf-8")
LOCALE_JS = (STATIC / "locale.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
LIBRARY_JS = (STATIC / "library.js").read_text(encoding="utf-8")
HARNESS = (Path(__file__).resolve().parent / "_util_library_save_harness.js").read_text(encoding="utf-8")

TOOL_IDS = ("speech", "sns", "meeting")
SAVE_COPY_KEYS = (
    "util-library-save",
    "util-library-saving",
    "util-library-saved",
    "util-library-save-failed",
)
# The shipped owner-scoped routes this feature must reuse, named once here.
PROJECT_ROUTE = '"/api/projects"'
FILES_ROUTE = '"/api/projects/" + encodeURIComponent(pid) + "/files"'


# ── the existing store is reused, not re-created ───────────────────────────


def test_the_save_reuses_the_existing_project_file_routes() -> None:
    assert PROJECT_ROUTE in TOOLS_JS
    assert FILES_ROUTE in TOOLS_JS
    assert '"text/plain"' in TOOLS_JS and "doc_kind: docKind" in TOOLS_JS
    # No second sink was invented: the only endpoints any Util tool file names
    # are the shipped projects collection, its files collection, and the stream.
    for path in ("/api/saved-outputs", "/api/library", "/api/documents", "/api/files"):
        assert path not in TOOLS_JS, path


def test_the_library_the_owner_reopens_is_the_same_owner_scoped_list() -> None:
    # The Library reads one bounded owner-scoped page; the save writes into a
    # project of that same owner, so the saved row is listable and openable.
    assert 'const OWNER_FILES_ENDPOINT = "/api/project-files";' in LIBRARY_JS
    assert "action: { label: TEXT.open(), run: () => openProject(file.project_id) }" in LIBRARY_JS
    assert "window.PadiemChatProjectOpener" in LIBRARY_JS


def test_app_js_gains_no_save_logic() -> None:
    for token in ("util-library-save", "data-util-save-library", "유틸"):
        assert token not in APP_JS, token


def test_the_pinned_project_is_not_the_council_project() -> None:
    # #7501 후속: 의원 3종은 Chat 유틸과 다른 사이트다. Chat 유틸 결과가 Chat
    # 사용자의 프로젝트 목록에 '의원3종' 프로젝트로 생기지 않는다.
    assert '"의원3종"' not in TOOLS_JS
    assert 'const LIBRARY_PROJECT_NAME = "유틸";' in TOOLS_JS


# ── copy: locale keys in KR and EN, no status token ────────────────────────


def test_the_copy_comes_from_the_locale_table_in_both_languages() -> None:
    for key in SAVE_COPY_KEYS:
        assert LOCALE_JS.count('"%s":' % key) == 2, key
    # The failure sentence is the existing Korean one, not a new wording and not
    # a status code.
    assert '"util-library-save-failed": "문서를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."' in LOCALE_JS
    assert '"util-library-save": "라이브러리에 저장"' in LOCALE_JS
    assert '"util-library-saved": "라이브러리에 저장했습니다."' in LOCALE_JS


def test_the_tool_name_and_date_make_the_title_and_the_tool_is_kept() -> None:
    assert "function libraryTitle(toolId)" in TOOLS_JS
    assert 'base + ".txt"' in TOOLS_JS
    assert 'doc_kind: docKind' in TOOLS_JS
    for tool in TOOL_IDS:
        # The doc_kind sent is the manifest tool id, which the server accepts.
        assert 'saveToLibrary(toolId, text)' in TOOLS_JS


# ── behaviour: the real util-tools.js in a Node DOM shim ───────────────────


def _run_harness(scenario: dict) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util library-save harness"
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "util_library_save_harness.js"
        harness.write_text(HARNESS, encoding="utf-8")
        env = dict(os.environ)
        env["SCENARIO"] = json.dumps(scenario)
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "util-tools.js"), str(STATIC / "util-tools-contract.js"),
             str(STATIC / "util-tools-markdown.js"), str(STATIC / "util-manifest.js")],
            capture_output=True, text=True, encoding="utf-8", env=env, check=False,
        )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _assert_checks(result: dict, names) -> None:
    assert result["ok"] is True, {k: v for k, v in result["checks"].items() if not v}
    for name in names:
        assert result["checks"].get(name) is True, name


@pytest.mark.parametrize("tool", TOOL_IDS)
def test_behaviour_the_button_is_inert_until_there_is_a_result(tool: str) -> None:
    result = _run_harness({"tool": tool, "projects": [{"id": "proj_pinned", "name": "유틸"}]})
    _assert_checks(result, (
        "save_button_present", "save_label_is_locale_copy",
        "save_disabled_before_result", "save_before_result_makes_no_request",
        "save_enabled_after_result",
    ))


@pytest.mark.parametrize("tool", TOOL_IDS)
def test_behaviour_the_save_posts_the_result_to_the_existing_store(tool: str) -> None:
    result = _run_harness({"tool": tool, "projects": [{"id": "proj_pinned", "name": "유틸"}]})
    _assert_checks(result, (
        "library_project_read", "library_project_read_credentials", "reuses_the_pinned_project",
        "save_posts_with_credentials", "save_inline_is_json", "save_body_media_type",
        "save_body_is_the_result", "save_body_names_the_tool", "save_name_is_a_txt_file",
        "save_name_has_the_date", "saved_notice",
    ))
    saved = [r for r in result["requests"] if r["url"].endswith("/files")][0]
    assert saved["body"]["doc_kind"] == tool
    assert saved["body"]["text"] == "초안 본문"
    assert saved["body"]["media_type"] == "text/plain"


def test_behaviour_a_first_save_creates_the_pinned_project_once() -> None:
    result = _run_harness({"tool": "speech", "projects": []})
    _assert_checks(result, ("creates_the_pinned_project", "saves_into_the_created_project", "saved_notice"))
    creates = [r for r in result["requests"] if r["url"] == "/api/projects" and r["method"] == "POST"]
    assert len(creates) == 1 and creates[0]["body"] == {"name": "유틸"}


def test_behaviour_a_failed_project_read_saves_nothing() -> None:
    result = _run_harness({"tool": "speech", "projectsUnavailable": True})
    _assert_checks(result, ("no_save_without_a_project", "project_failure_is_reported"))


def test_behaviour_a_store_failure_uses_the_existing_korean_sentence() -> None:
    result = _run_harness({
        "tool": "meeting",
        "projects": [{"id": "proj_pinned", "name": "유틸"}],
        "saveResponses": [{"status": 503, "body": {"error": {"code": "unavailable"}}}],
        "expectFailure": True,
    })
    _assert_checks(result, (
        "failure_uses_the_existing_sentence", "failure_is_not_a_status_token",
        "failure_shows_no_success_copy", "save_retry_stays_available",
    ))


def test_behaviour_english_copy_when_the_ui_is_english() -> None:
    result = _run_harness({
        "tool": "speech", "lang": "en",
        "projects": [{"id": "proj_pinned", "name": "유틸"}],
    })
    _assert_checks(result, ("save_label_is_locale_copy", "saved_notice"))


def test_behaviour_the_same_day_name_conflict_never_overwrites() -> None:
    result = _run_harness({
        "tool": "sns",
        "projects": [{"id": "proj_pinned", "name": "유틸"}],
        "saveResponses": [
            {"status": 409, "body": {"error": {"code": "name_conflict"}}},
            {"status": 201},
        ],
        "expectConflictRetry": True,
    })
    _assert_checks(result, ("conflict_retries_with_a_new_name", "conflict_never_overwrites", "saved_notice"))


def test_behaviour_signed_out_has_no_save_path_at_all() -> None:
    result = _run_harness({"tool": "speech", "signedOut": True})
    _assert_checks(result, (
        "signed_out_gate", "signed_out_has_no_save_button", "signed_out_makes_no_request",
    ))


# ── the server side accepts exactly what the screen sends ──────────────────


class _MemoryFile:
    def __init__(self, file_id: str, project_id: str, name: str, media_type: str, kind: str):
        self.id, self.project_id, self.name = file_id, project_id, name
        self.media_type, self.doc_kind = media_type, kind

    def public_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "name": self.name,
                "media_type": self.media_type, "doc_kind": self.doc_kind}


class _MemoryStore:
    """The two store calls the shipped routes make, and nothing else."""

    def __init__(self) -> None:
        self.created: list[_MemoryFile] = []

    async def find_current_by_name(self, uid, pid, name, kind):
        for item in self.created:
            if item.project_id == pid and item.name == name and item.doc_kind == kind:
                return item
        return None

    async def create_file(self, uid, pid, name, media_type, text, **extra):
        file = _MemoryFile("file_%d" % (len(self.created) + 1), pid, name, media_type,
                           extra.get("doc_kind", ""))
        self.created.append(file)
        return file

    async def list_owner_files(self, uid, after=None, limit=50):
        from app.project_files import OwnerFileProjection
        return [
            OwnerFileProjection(
                id=item.id, project_id=item.project_id, project_name="유틸", name=item.name,
                media_type=item.media_type, content_chars=4,
                created_at="2026-11-11T00:00:00.000Z", updated_at="2026-11-11T00:00:00.000Z",
            )
            for item in self.created
        ][:limit]


def _post_request(store, body: dict, project_id: str) -> tuple[Request, bytes]:
    payload = json.dumps(body).encode("utf-8")
    request = Request({
        "type": "http", "method": "POST",
        "path": "/api/projects/%s/files" % project_id,
        "path_params": {"project_id": project_id},
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode())],
        "query_string": b"",
        "app": SimpleNamespace(state=SimpleNamespace(project_file_store=store,
                                                     history_store=None)),
    })
    return request, payload


def test_server_side_the_saved_row_is_the_one_the_library_lists() -> None:
    from app import project_file_routes as routes

    store = _MemoryStore()
    project_id = "proj_" + "1" * 32
    request, payload = _post_request(store, {
        "name": "축사·인사말 2026-11-11.txt",
        "media_type": "text/plain",
        "text": "축사 본문",
        "doc_kind": "speech",
    }, project_id)

    class _History:
        async def get_project(self, uid, pid):
            return SimpleNamespace(id=pid, name="유틸")

    request.app.state.history_store = _History()

    async def run() -> tuple[int, dict]:
        with patch.object(routes, "auth_ready", return_value=True), \
             patch.object(routes, "current_user_id", return_value="usr_" + "a" * 32), \
             patch.object(routes, "read_bounded_request_body",
                          side_effect=lambda req, max_bytes: payload):
            response = await routes.project_files_collection(request)
            created = json.loads(response.body.decode())
            listed = await routes.owner_files_collection(_owner_request(store))
        return response.status_code, {"created": created, "listed": json.loads(listed.body.decode())}

    code, body = asyncio.run(run())
    assert code == 201, body
    assert body["created"]["file"]["name"] == "축사·인사말 2026-11-11.txt"
    assert body["created"]["file"]["doc_kind"] == "speech"
    names = [item["name"] for item in body["listed"]["files"]]
    assert names == ["축사·인사말 2026-11-11.txt"]


def _owner_request(store) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/api/project-files",
        "headers": [], "query_string": b"",
        "app": SimpleNamespace(state=SimpleNamespace(project_file_store=store,
                                                     history_store=None)),
    })
