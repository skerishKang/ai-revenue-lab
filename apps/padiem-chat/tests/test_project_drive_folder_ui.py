"""Project Drive case-folder UI contract tests (#3190).

Source-level QA for the static UI: the markup the Project dialog must expose,
the JS behaviours that are security-relevant (text-safe rendering, stale-response
guards, state separation), and the accessibility/mobile rules.

A full interactive browser run is intentionally out of scope here; these
assertions pin the same contract a browser QA pass would exercise.
"""

from __future__ import annotations

import pathlib

STATIC = pathlib.Path(__file__).resolve().parents[1] / "static"

INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC / "project-drive-folder.js").read_text(encoding="utf-8")
CSS = (STATIC / "projects.css").read_text(encoding="utf-8")


# --- 1. section markup -----------------------------------------------------


def test_project_drive_section_is_present_and_labelled() -> None:
    assert 'id="projectDrivePanel"' in INDEX
    assert "Google Drive 사건 폴더" in INDEX
    assert 'id="projectDriveTitle"' in INDEX
    assert 'id="projectDrivePickButton"' in INDEX
    assert 'id="projectDriveClearButton"' in INDEX
    assert 'id="projectDriveStatus"' in INDEX


def test_status_region_is_aria_live() -> None:
    assert 'id="projectDriveStatusLive"' in INDEX
    assert 'aria-live="polite"' in INDEX
    assert 'aria-busy="false"' in INDEX


def test_picker_is_a_dialog_with_label_and_search_label() -> None:
    assert 'id="projectDrivePicker"' in INDEX
    assert "<dialog" in INDEX
    assert 'aria-labelledby="projectDrivePickerTitle"' in INDEX
    assert 'for="projectDriveSearchInput"' in INDEX
    assert 'id="projectDriveSearchInput"' in INDEX


def test_script_is_loaded_and_no_new_framework() -> None:
    assert 'src="./project-drive-folder.js"' in INDEX
    for framework in ("react", "vue", "svelte", "htmx"):
        assert framework not in SCRIPT.lower()


# --- 2. states -------------------------------------------------------------


def test_all_five_status_texts_are_defined() -> None:
    for text in (
        "사건 폴더가 선택되지 않았습니다.",
        "연결됨 · 내 드라이브",
        "연결됨 · 공유 드라이브",
        "Google Drive 연결을 확인해 주세요.",
        "사건 폴더 상태를 불러오지 못했습니다.",
    ):
        assert text in SCRIPT, text


def test_picker_states_are_distinct() -> None:
    for text in (
        "폴더를 불러오는 중…",
        "최근 폴더가 없습니다.",
        "검색 결과가 없습니다.",
        "Google Drive 연결을 확인해 주세요.",
        "폴더 목록을 불러오지 못했습니다.",
    ):
        assert text in SCRIPT, text
    # only a bounded error.code === drive_not_connected maps to the connection
    # state; any other 409 is a generic error (status and list alike)
    assert 'body.error.code === "drive_not_connected"' in SCRIPT
    assert "response.status !== 409" in SCRIPT


# --- 3. stale-response guards ---------------------------------------------


def test_stale_status_and_search_responses_are_ignored() -> None:
    assert "statusToken" in SCRIPT
    assert "searchToken" in SCRIPT
    assert SCRIPT.count("!== state.statusToken") >= 1
    assert SCRIPT.count("!== state.searchToken") >= 1


# --- 4. XSS safety ---------------------------------------------------------


def test_folder_names_are_rendered_with_textcontent_only() -> None:
    # property/function usage only; bare mentions in comments are documentation
    for sink in (".innerHTML", "insertAdjacentHTML(", "document.write(", "outerHTML"):
        assert sink not in SCRIPT, sink
    assert "label.textContent = String(folder.name)" in SCRIPT


# --- 5. routes contract ----------------------------------------------------


def test_client_calls_only_the_owner_gated_routes() -> None:
    assert "/drive-case-folder" in SCRIPT
    assert "/drive-folders" in SCRIPT
    assert 'method: "PUT"' in SCRIPT
    assert 'method: "DELETE"' in SCRIPT
    assert "folder_id: folderId" in SCRIPT


def test_raw_ids_are_not_rendered() -> None:
    # the folder id only ever travels through data attributes / request bodies
    assert "data-folder-select" in SCRIPT
    assert "folder.folder_id" in SCRIPT


# --- 6. accessibility + mobile --------------------------------------------


def test_accessibility_rules_are_present() -> None:
    assert "Escape" in SCRIPT
    assert "opener.focus()" in SCRIPT
    assert "state.opener = document.activeElement" in SCRIPT
    assert "search.focus()" in SCRIPT
    assert "setSelectButtonsDisabled(true)" in SCRIPT


def test_css_has_44px_targets_and_mobile_rule() -> None:
    assert "min-height: 44px" in CSS
    assert "min-width: 44px" in CSS
    assert "@media (max-width: 420px)" in CSS
    assert "overflow-wrap: anywhere" in CSS


# --- 7. dialog lifecycle ---------------------------------------------------


def test_dialog_lifecycle_is_wired_in_app_js() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "window.padiemProjectDriveFolder.reset()" in app
    assert "window.padiemProjectDriveFolder.loadStatus(project.id)" in app
    assert 'document.getElementById("projectDrivePanel")' in app
    assert "drivePanel.hidden = true" in app


def test_reset_invalidates_tokens_and_clears_the_picker() -> None:
    assert "function reset()" in SCRIPT
    assert "state.statusToken += 1;" in SCRIPT
    assert "state.searchToken += 1;" in SCRIPT
    assert "closePicker({ restoreFocus: false })" in SCRIPT
    assert "reset: reset," in SCRIPT
