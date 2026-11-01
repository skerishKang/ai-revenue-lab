"""2026-11-01 대표 요청: 사이드바에서 "빠른 실행"과 "최근 프로젝트 파일" 묶음을 제거한다.

이 파일은 제거된 화면을 기준으로 고쳤다. 예전에는 이 두 묶음이 실제로 동작하는지
(단축 버튼 이동·최근 파일 5행·파일 더 보기)를 검증했다. 이제 검증하는 것은:

1. **사라진 것** — 마크업·카피 키·전용 CSS가 없고, 남은 메뉴가 그 자리를 대신한다.
2. **살아남은 경로** — 유틸은 사이드바 유틸 서브메뉴, 파일은 라이브러리 진입.
3. **첫 화면 요청 감소** — 라이브러리를 열지 않은 상태에서는 `/api/project-files`
   호출이 0건이고, 연 뒤 정확히 1건이 나간다. (사이드바 목록이 부르던 선조회 제거)
4. **사이드바 순서** — 메뉴 → 프로젝트 → 최근 대화.
5. **선택 강조** — 프로젝트 열기가 넣는 `.quick-selected-file`는 살아 있고, 그
   규칙은 `documents.css`로 이사했다.
"""

from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path
from urllib import parse as uparse

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
LIBRARY_JS = (STATIC / "library.js").read_text(encoding="utf-8")
DOCUMENTS_CSS = (STATIC / "documents.css").read_text(encoding="utf-8")
PID = "proj_" + "1" * 32
FID = "file_" + "2" * 32


@pytest.fixture(scope="module")
def site():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(STATIC), **kw)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def open_chat(browser, site, width):
    """A signed-in session whose Library has NOT been opened, with the read count."""
    page = browser.new_page(viewport={"width": width, "height": 900})
    reads = {"project_files": 0}

    def api(route):
        url = route.request.url
        path = uparse.urlsplit(url).path
        if not path.startswith("/api/"):
            if uparse.urlsplit(url).netloc != uparse.urlsplit(site).netloc:
                route.abort()
            else:
                route.continue_()
            return
        if path == "/api/auth/status":
            data = {"ready": True, "authenticated": True, "session_state": "signed_in",
                    "user": {"name": "Test"}, "history_ready": True, "project_files_ready": True}
        elif path == "/api/projects":
            data = {"projects": [{"id": PID, "name": "Test project", "instructions": ""}]}
        elif path == "/api/project-files":
            reads["project_files"] += 1
            data = {"files": [{"id": FID, "name": "recent.txt", "project_id": PID,
                               "project_name": "Test project"}], "has_more": False}
        elif path.startswith(f"/api/projects/{PID}"):
            data = {"files": [{"id": FID, "name": "recent.txt", "media_type": "text/plain",
                               "content_chars": 7}], "project": {"id": PID, "name": "Test project",
                                                                 "instructions": ""}}
        elif path == "/api/conversations":
            data = {"conversations": []}
        else:
            data = {"ok": True}
        route.fulfill(json=data)

    page.route("**/*", api)
    page.goto(site)
    page.wait_for_timeout(900)
    if width < 700:
        page.locator("#mobileMenu").click()
        page.wait_for_timeout(400)
    return page, reads


# ── 1. what is gone ──────────────────────────────────────────────────────────
def test_the_sidebar_carries_no_quick_launch_block():
    for token in ('id="quickLaunchTitle"', 'id="quickRecentFiles"', 'id="quickAllFiles"',
                  "data-quick-util", 'class="recent-section quick-launch"'):
        assert token not in INDEX, token
    assert not (STATIC / "quick-launch.css").exists()
    assert "./quick-launch.css" not in INDEX


def test_the_removed_copy_keys_are_gone_from_both_languages():
    assert not re.search(r'"quick-(launch-title|speech|sns|meeting|quote|pdfmd|recent-files|all-files|files-)', LOCALE)
    ko = LOCALE[LOCALE.index("ko: {"):LOCALE.index("\n    en: {")]
    en = LOCALE[LOCALE.index("\n    en: {"):LOCALE.index("\n  };", LOCALE.index("\n    en: {"))]
    key = re.compile(r'"([a-z0-9][a-z0-9-]{1,60})":')
    assert len(key.findall(ko)) == len(key.findall(en)), "ko/en 표 대칭이 무너짐"


def test_library_js_no_longer_holds_the_sidebar_list_or_its_prefetch():
    for token in ("quickRecentFiles", "quickAllFiles", "renderQuickFiles"):
        assert token not in LIBRARY_JS, token
    # The closed-state prefetch is the request that went away.
    assert "!isOpen() && (changed || projectionChanged)) loadFiles();" not in LIBRARY_JS
    # Opening the page still reads.
    assert 'if (activeTab === "files" && outcome !== "ready" && !loading) loadFiles();' in LIBRARY_JS


# ── 2. the surviving routes ──────────────────────────────────────────────────
def tap_sidebar(page, width):
    """390 keeps the nav off-canvas, and every destination closes it again."""
    if width < 700:
        menu = page.locator("#mobileMenu")
        if page.evaluate("() => !document.querySelector('.app-shell')"
                         ".classList.contains('sidebar-open')"):
            menu.click()
            page.wait_for_timeout(400)


@pytest.mark.parametrize("width", [1440, 390])
def test_util_and_library_are_still_reachable_from_their_own_menus(browser, site, width):
    page, _ = open_chat(browser, site, width)
    page.locator("#utilNavButton").click()
    page.wait_for_timeout(300)
    page.locator('.util-submenu-item[data-util="pdfmd"]').click()
    page.wait_for_timeout(600)
    assert page.locator("#utilPdfmdPanel").is_visible()
    assert page.locator(".app-shell").get_attribute("data-state") == "util"

    tap_sidebar(page, width)
    page.locator("#filesNavButton").click()
    page.wait_for_timeout(600)
    assert page.locator(".app-shell").get_attribute("data-state") == "library"
    page.close()


# ── 3. the first-screen request reduction ────────────────────────────────────
def test_an_open_session_reads_project_files_only_when_the_library_opens(browser, site):
    page, reads = open_chat(browser, site, 1440)
    assert reads["project_files"] == 0, "라이브러리를 열지 않았는데 첫 화면이 파일을 읽는다"
    page.locator("#filesNavButton").click()
    page.wait_for_timeout(800)
    assert reads["project_files"] == 1, "열었을 때 정확히 한 번 읽어야 한다"
    page.close()


# ── 4. the sidebar order the owner asked for ─────────────────────────────────
def test_the_sidebar_order_is_menu_then_projects_then_recent_conversations():
    nav = INDEX.index('<nav class="side-nav" aria-label="도구 및 연결">')
    projects = INDEX.index('id="projectsSection"')
    history = INDEX.index('id="historySection"')
    assert nav < projects < history


# ── 5. the selection highlight still exists, in its new home ─────────────────
def test_the_project_row_selection_rule_moved_to_documents_css():
    assert ".project-file-row.quick-selected-file" in DOCUMENTS_CSS
    assert 'row.classList.add("quick-selected-file");' in (STATIC / "app.js").read_text(encoding="utf-8")


def test_the_two_argument_opener_lost_its_only_caller():
    """`PadiemChatProjectOpener.openFile(projectId, fileId)` existed for the
    sidebar's recent-file rows. Nothing in the shipped code calls it now, so the
    highlight it drove can no longer appear. The handle and its rule stay (the
    seam is asserted by test_b62_3232_web_files_sidebar), and this pins the fact
    so the next pass can decide to retire them rather than lose it in a diff.
    """
    assert "opener.openFile(" not in LIBRARY_JS
    assert "openFile: async (projectId, fileId)" in (STATIC / "app.js").read_text(encoding="utf-8")
