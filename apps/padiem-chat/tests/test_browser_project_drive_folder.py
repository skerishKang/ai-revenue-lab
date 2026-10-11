"""Dedicated Project Drive case-folder browser QA (#3190).

Follows the repository's browser-QA convention: the real static module source is
executed under Node with a deterministic DOM shim and a fake fetch, and the
observed behaviour is asserted. No live network and no Google call is involved.

Covered: status states (unconfigured / my drive / shared drive /
drive-not-connected-by-code / other 409 / 502), recent + search results and
empty states, picker drive-not-connected vs generic error, select / replace /
clear flows, stale-response guards (project switch during a delayed body read,
dialog close invalidation), XSS-safe rendering of hostile folder names, and the
Escape/focus lifecycle.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "static" / "project-drive-folder.js"

ELEMENT_IDS = (
    "projectDrivePanel",
    "projectDriveStatus",
    "projectDriveStatusLive",
    "projectDrivePickButton",
    "projectDriveClearButton",
    "projectDrivePicker",
    "projectDrivePickerClose",
    "projectDriveSearchInput",
    "projectDriveFolderList",
    "projectDrivePickerState",
)


def _run(scenario: str) -> dict:
    module = MODULE_PATH.read_text(encoding="utf-8")
    driver = (Path(__file__).resolve().parent / "drive_folder_browser_driver.js").read_text(encoding="utf-8")
    result = subprocess.run(
        ["node", "-e", driver, module, scenario],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"driver failed: {result.stderr}")
    return json.loads(result.stdout.strip())


# --- 1. status states ------------------------------------------------------


def test_status_states() -> None:
    observed = _run("status")
    assert observed["unconfigured"] == "사건 폴더가 선택되지 않았습니다."
    assert observed["my_drive"] == "연결됨 · 내 드라이브"
    assert observed["shared_drive"] == "연결됨 · 공유 드라이브"
    assert observed["not_connected"] == "Google Drive 연결을 확인해 주세요."
    assert observed["other_409"] == "사건 폴더 상태를 불러오지 못했습니다."
    assert observed["http_502"] == "사건 폴더 상태를 불러오지 못했습니다."


def test_loading_state_is_announced_with_aria_busy() -> None:
    observed = _run("loading")
    assert observed["busy"] == "true"
    assert observed["text"] == "불러오는 중…"


def test_clear_button_visibility_follows_configured() -> None:
    observed = _run("configured_buttons")
    assert observed["unconfigured_clear_hidden"] is True
    assert observed["unconfigured_pick_label"] == "폴더 선택"
    assert observed["configured_clear_hidden"] is False
    assert observed["configured_pick_label"] == "폴더 변경"


# --- 2. picker states ------------------------------------------------------


def test_picker_recent_search_and_empty_states() -> None:
    observed = _run("picker")
    assert observed["recent_rows"] == 2
    assert observed["recent_first_name"] == "사건자료"
    assert observed["recent_first_space"] == "내 드라이브"
    assert observed["recent_second_space"] == "공유 드라이브"
    assert observed["recent_empty"] == "최근 폴더가 없습니다."
    assert observed["search_empty"] == "검색 결과가 없습니다."
    assert observed["search_query_in_url"] is True


def test_picker_error_states_are_distinct() -> None:
    observed = _run("picker_errors")
    assert observed["not_connected"] == "Google Drive 연결을 확인해 주세요."
    assert observed["other_409"] == "폴더 목록을 불러오지 못했습니다."
    assert observed["http_502"] == "폴더 목록을 불러오지 못했습니다."


# --- 3. select / replace / clear ------------------------------------------


def test_select_replace_and_clear_flows() -> None:
    observed = _run("mutations")
    assert observed["select_method"] == "PUT"
    assert observed["select_body"] == {"folder_id": "folder_a"}
    assert observed["select_status_refreshed"] is True
    assert observed["replace_body"] == {"folder_id": "folder_b"}
    assert observed["clear_method"] == "DELETE"
    assert observed["after_clear"] == "사건 폴더가 선택되지 않았습니다."


def test_select_buttons_disable_while_put_is_in_flight() -> None:
    observed = _run("double_submit")
    assert observed["disabled_during_put"] is True


# --- 4. stale / race -------------------------------------------------------


def test_project_switch_during_status_body_read_is_ignored() -> None:
    observed = _run("stale_project_switch")
    assert observed["status_after_switch"] == "연결됨 · 내 드라이브"
    assert observed["stale_status_applied"] is False


def test_dialog_close_during_status_read_is_ignored() -> None:
    observed = _run("stale_dialog_close")
    assert observed["status_after_reset"] == "사건 폴더가 선택되지 않았습니다."
    assert observed["stale_status_applied"] is False


def test_stale_search_response_is_ignored() -> None:
    observed = _run("stale_search")
    assert observed["final_first_name"] == "두번째"
    assert observed["stale_search_applied"] is False


# --- 5. XSS ---------------------------------------------------------------


def test_hostile_folder_names_are_literal_text_only() -> None:
    observed = _run("xss")
    assert observed["visible_names"] == [
        "<img src=x onerror=alert(1)>",
        "<script>alert(1)</script>",
    ]
    assert observed["img_nodes"] == 0
    assert observed["script_nodes"] == 0
    assert observed["raw_folder_id_visible"] is False


# --- 6. keyboard / focus ---------------------------------------------------


def test_escape_closes_picker_and_restores_focus() -> None:
    observed = _run("keyboard")
    assert observed["focused_on_open"] == "projectDriveSearchInput"
    assert observed["closed_on_escape"] is True
    assert observed["focus_returned_to_opener"] is True
