"""B67 A6 authenticated Project Drive browser canary (#3199).

Attaches only to an already-running local Chromium via loopback CDP. The user
owns the authenticated browser session; this runner never reads, exports, or
prints cookies, tokens, project IDs, folder IDs, folder names, or user identity.

The runner reuses one existing Project and two distinct existing Drive folders:
recent -> one search -> select A -> reload persistence -> replace with B ->
clear -> reload unconfigured. It creates no Project/folder and performs no
OAuth connect. Existing configured state fails closed instead of being cleared.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse

TARGET_URL = "https://chat.padiem.net/"
TARGET_HOST = "chat.padiem.net"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
ALLOWED_CDP_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

STATUS_LOADING = "불러오는 중…"
STATUS_UNCONFIGURED = "사건 폴더가 선택되지 않았습니다."
STATUS_CONNECTED = frozenset({"연결됨 · 내 드라이브", "연결됨 · 공유 드라이브"})
STATUS_DRIVE_NOT_CONNECTED = "Google Drive 연결을 확인해 주세요."

WAIT_SECONDS = 20.0


class CanaryFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FolderCandidate:
    folder_id: str
    name: str


def validate_cdp_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme != "http":
        raise CanaryFailure("cdp_url_not_loopback_http")
    if parsed.hostname not in ALLOWED_CDP_HOSTS:
        raise CanaryFailure("cdp_url_not_loopback_http")
    if parsed.port is None:
        raise CanaryFailure("cdp_url_missing_port")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CanaryFailure("cdp_url_contains_authority_data")
    if parsed.path not in ("", "/"):
        raise CanaryFailure("cdp_url_contains_path")
    return raw


def classify_status(text: str) -> str:
    value = (text or "").strip()
    if value == STATUS_LOADING:
        return "loading"
    if value == STATUS_UNCONFIGURED:
        return "unconfigured"
    if value in STATUS_CONNECTED:
        return "connected"
    if value == STATUS_DRIVE_NOT_CONNECTED:
        return "drive_not_connected"
    if value:
        return "error"
    return "empty"


def _wait_status(page, *, expected: set[str], timeout: float = WAIT_SECONDS) -> str:
    deadline = time.monotonic() + timeout
    locator = page.locator("#projectDriveStatus")
    while time.monotonic() < deadline:
        try:
            state = classify_status(locator.text_content() or "")
        except Exception:
            state = "empty"
        if state in expected:
            return state
        if state in {"drive_not_connected", "error"}:
            raise CanaryFailure(f"drive_status_{state}")
        time.sleep(0.1)
    raise CanaryFailure("drive_status_timeout")


def _wait_folder_buttons(page, *, minimum: int, timeout: float = WAIT_SECONDS):
    deadline = time.monotonic() + timeout
    buttons = page.locator("#projectDriveFolderList button[data-folder-select]")
    while time.monotonic() < deadline:
        try:
            if buttons.count() >= minimum:
                return buttons
        except Exception:
            pass
        time.sleep(0.1)
    raise CanaryFailure("drive_folder_candidates_insufficient")


def _candidate_at(buttons, index: int) -> FolderCandidate:
    button = buttons.nth(index)
    folder_id = (button.get_attribute("data-folder-select") or "").strip()
    row = button.locator("xpath=..")
    name = (row.locator(".project-drive-row-name").text_content() or "").strip()
    if not folder_id or not name:
        raise CanaryFailure("drive_folder_candidate_invalid")
    return FolderCandidate(folder_id=folder_id, name=name)


def _find_folder_button(page, folder_id: str):
    buttons = page.locator("#projectDriveFolderList button[data-folder-select]")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if (button.get_attribute("data-folder-select") or "") == folder_id:
            return button
    raise CanaryFailure("drive_folder_candidate_not_found")


def _wait_projects_ready(page, timeout_ms: int = 20000) -> None:
    try:
        page.locator("#projectsNavButton:not([disabled])").wait_for(
            state="attached", timeout=timeout_ms
        )
        page.locator(".project-manage").first.wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:
        raise CanaryFailure("authenticated_existing_project_unavailable") from exc


def _open_existing_project(page, project_id: str | None = None) -> str:
    _wait_projects_ready(page)
    rows = page.locator(".project-row")
    for index in range(rows.count()):
        row = rows.nth(index)
        project_button = row.locator(".project-item")
        candidate_id = (project_button.get_attribute("data-project-id") or "").strip()
        if not candidate_id:
            continue
        if project_id is not None and candidate_id != project_id:
            continue
        row.locator(".project-manage").click()
        try:
            page.locator("#projectDialog").wait_for(state="visible", timeout=10000)
            page.locator("#projectDrivePanel").wait_for(state="visible", timeout=10000)
        except Exception as exc:
            raise CanaryFailure("project_drive_panel_unavailable") from exc
        return candidate_id
    raise CanaryFailure("existing_project_not_found")


def _expect_api_response(page, method: str, path_fragment: str, action):
    try:
        with page.expect_response(
            lambda response: (
                response.request.method == method
                and path_fragment in urlparse(response.url).path
            ),
            timeout=20000,
        ) as response_info:
            action()
        response = response_info.value
    except Exception as exc:
        raise CanaryFailure(f"{method.lower()}_response_missing") from exc
    if response.status != 200:
        raise CanaryFailure(f"{method.lower()}_http_{response.status}")
    return response


def _open_picker_and_wait_recent(page):
    _expect_api_response(
        page,
        "GET",
        "/drive-folders",
        lambda: page.locator("#projectDrivePickButton").click(),
    )
    try:
        page.locator("#projectDrivePicker").wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise CanaryFailure("drive_picker_unavailable") from exc
    return _wait_folder_buttons(page, minimum=2)


def _search_for_folder_a(page, folder: FolderCandidate) -> None:
    query = folder.name[:200].strip()
    if not query:
        raise CanaryFailure("drive_search_query_unavailable")
    search = page.locator("#projectDriveSearchInput")
    search.fill(query)
    _expect_api_response(page, "GET", "/drive-folders", lambda: search.press("Enter"))
    _wait_folder_buttons(page, minimum=1)
    _find_folder_button(page, folder.folder_id)


def _select_folder(page, folder_id: str) -> None:
    button = _find_folder_button(page, folder_id)
    _expect_api_response(page, "PUT", "/drive-case-folder", button.click)
    _wait_status(page, expected={"connected"})


def _clear_folder(page) -> None:
    clear_button = page.locator("#projectDriveClearButton")
    try:
        clear_button.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise CanaryFailure("drive_clear_button_unavailable") from exc
    _expect_api_response(page, "DELETE", "/drive-case-folder", clear_button.click)
    _wait_status(page, expected={"unconfigured"})


def _choose_target_page(browser):
    if not browser.contexts:
        raise CanaryFailure("cdp_browser_context_unavailable")
    context = browser.contexts[0]
    for page in context.pages:
        try:
            if urlparse(page.url).hostname == TARGET_HOST:
                return page, False
        except Exception:
            continue
    return context.new_page(), True


def run_live(cdp_url: str) -> int:
    validate_cdp_url(cdp_url)
    direct_google_requests = 0
    put_count = 0
    delete_count = 0
    created_page = False

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        raise CanaryFailure("playwright_unavailable")

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            raise CanaryFailure("cdp_connect_failed") from exc

        page, created_page = _choose_target_page(browser)

        def observe_request(request) -> None:
            nonlocal direct_google_requests, put_count, delete_count
            parsed = urlparse(request.url)
            host = (parsed.hostname or "").lower()
            if host.endswith("googleapis.com") or host == "drive.google.com":
                direct_google_requests += 1
            if "/drive-case-folder" in parsed.path and request.method == "PUT":
                put_count += 1
            if "/drive-case-folder" in parsed.path and request.method == "DELETE":
                delete_count += 1

        page.on("request", observe_request)
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
            _wait_projects_ready(page)
            project_id = _open_existing_project(page)

            # A6 requires a clean unconfigured baseline. Never auto-clear an
            # existing user binding merely to make the test convenient.
            baseline = _wait_status(page, expected={"unconfigured", "connected"})
            if baseline != "unconfigured":
                raise CanaryFailure("baseline_already_configured")

            recent = _open_picker_and_wait_recent(page)
            folder_a = _candidate_at(recent, 0)
            folder_b = _candidate_at(recent, 1)
            if folder_a.folder_id == folder_b.folder_id:
                raise CanaryFailure("drive_folder_candidates_not_distinct")

            _search_for_folder_a(page, folder_a)
            _select_folder(page, folder_a.folder_id)

            page.reload(wait_until="domcontentloaded", timeout=30000)
            _open_existing_project(page, project_id)
            _wait_status(page, expected={"connected"})

            recent_after_reload = _open_picker_and_wait_recent(page)
            # Folder B was captured from the initial recent result. It must
            # remain selectable after reload; no ID/name is ever printed.
            _find_folder_button(page, folder_b.folder_id)
            _select_folder(page, folder_b.folder_id)

            _clear_folder(page)
            page.reload(wait_until="domcontentloaded", timeout=30000)
            _open_existing_project(page, project_id)
            _wait_status(page, expected={"unconfigured"})

            if put_count != 2 or delete_count != 1:
                raise CanaryFailure("browser_mutation_count_mismatch")
            if direct_google_requests != 0:
                raise CanaryFailure("browser_direct_google_call_observed")

            print("B67_A6_BROWSER_FLOW=PASS")
            print("A6_BROWSER_AUTHENTICATED=YES")
            print("A6_EXISTING_PROJECT_REUSED=YES")
            print("A6_BASELINE_UNCONFIGURED=PASS")
            print("A6_RECENT_FOLDER_CANDIDATES=PASS")
            print("A6_SEARCH_FOLDER_CANDIDATES=PASS")
            print("A6_DISTINCT_FOLDER_SELECTIONS=PASS")
            print("A6_SELECT_A=PASS")
            print("A6_RELOAD_PERSISTS=PASS")
            print("A6_REPLACE_B=PASS")
            print("A6_CLEAR=PASS")
            print("A6_CLEAR_RELOAD_PERSISTS=PASS")
            print("DRIVE_CASE_FOLDER_PUT_COUNT=2")
            print("DRIVE_CASE_FOLDER_DELETE_COUNT=1")
            print("BROWSER_DIRECT_GOOGLE_CALLS=0")
            print("PROJECT_CREATE=0")
            print("OAUTH_CONNECT=0")
            print("RAW_PROJECT_ID_OUTPUT=0")
            print("RAW_FOLDER_ID_OUTPUT=0")
            print("RAW_FOLDER_NAME_OUTPUT=0")
            print("RAW_USER_OUTPUT=0")
            print("COOKIE_OUTPUT=0")
            print("TOKEN_OUTPUT=0")
            print("D1_READBACK=NOT_PERFORMED_BY_BROWSER_RUNNER")
            return 0
        finally:
            if created_page:
                try:
                    page.close()
                except Exception:
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--authorized-live-run", action="store_true")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if not args.authorized_live_run:
        print("B67_A6_BROWSER_FLOW=FAIL_AUTHORIZATION_REQUIRED")
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 1

    try:
        return run_live(args.cdp_url)
    except CanaryFailure as exc:
        print("B67_A6_BROWSER_FLOW=FAIL")
        print(f"SAFE_ERROR_CODE={exc.code}")
        print("RAW_PROJECT_ID_OUTPUT=0")
        print("RAW_FOLDER_ID_OUTPUT=0")
        print("RAW_FOLDER_NAME_OUTPUT=0")
        print("RAW_USER_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        return 1
    except Exception:
        print("B67_A6_BROWSER_FLOW=FAIL")
        print("SAFE_ERROR_CODE=unexpected_error")
        print("RAW_PROJECT_ID_OUTPUT=0")
        print("RAW_FOLDER_ID_OUTPUT=0")
        print("RAW_FOLDER_NAME_OUTPUT=0")
        print("RAW_USER_OUTPUT=0")
        print("COOKIE_OUTPUT=0")
        print("TOKEN_OUTPUT=0")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
