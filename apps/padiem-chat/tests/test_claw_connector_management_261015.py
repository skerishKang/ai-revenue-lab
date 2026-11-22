"""Connector management must separate reversible usage toggle from OAuth credential removal."""
from _android_handoff_storage_guard import assert_session_storage_is_handoff_only

# #8060: 원문 read는 파일 전용 _support가 담당하고 시험은 파싱된 HTML 값·시트
# 토큰으로 단언한다. 공용 claw_static은 건드리지 않는다.
from _support.connector_management_source import (
    html_has_attr,
    html_ids,
    script_srcs,
    sheet_has,
    sheet_text,
)

_MANAGER = "claw-connector-management.js"
_GUIDE = "claw-connection-guide.js"
_CHIP = "claw-connection-chips.js"
_APP = "app.js"
_CONNECTORS = "chat-connectors-module.js"


def test_existing_connectors_page_has_explicit_connect_and_remove_actions():
    ids = html_ids()
    for control in ("connectorGithubPrimary", "connectorGithubRemove",
                    "connectorGithubState", "connectorGithubPermissions",
                    "connectorDriveRemove", "connectorDriveFeedback"):
        assert control in ids
    srcs = script_srcs()
    assert "./claw-connector-management.js" in srcs
    assert srcs.index("./app.js") < srcs.index("./claw-connector-management.js")
    assert html_has_attr("data-google-connector-connect", "google-drive")
    # #5555 owner decision 2026-10-23: the header disclosure (and the long
    # disconnect explanation) is removed from the screen entirely.
    assert not sheet_has("index.html", "연결 삭제는 계정 인증을 제거하는 것")
    assert "connectorComputerCard" in ids  # unchanged Windows area


def test_main_off_first_use_starts_real_provider_not_connector_workspace():
    assert sheet_has(_GUIDE, "padiem:drive-quick-connect")
    # #7216 A9: the quick-connect listener and the reviewed ticket flow moved
    # into the connectors module; app.js keeps the wire call + OAuth return.
    assert sheet_has(_CONNECTORS, "padiem:drive-quick-connect")
    assert sheet_has(_CONNECTORS, "await loadConnectorStatus()")
    assert sheet_has(_CONNECTORS, "offered.click()")  # existing reviewed Drive ticket flow
    assert sheet_has(_CONNECTORS, "beginGoogleDriveConnect()")
    assert sheet_has(_APP, "connectorsModule().wireConnectorsListeners();")
    assert sheet_has(_GUIDE, "/api/connectors/github/start")
    assert sheet_has(_GUIDE, 'window.location.assign("/api/connectors/github/start")')
    assert_session_storage_is_handoff_only(sheet_text(_APP))
    assert sheet_has(_APP, "openConnectorsDialog()")
    assert sheet_has(_APP, "claw-github=connected")
    assert sheet_has(_APP, "window.history.replaceState")


def test_connection_management_never_forges_on_off_or_auto_deletes():
    assert sheet_has(_MANAGER, "/api/connectors/github/status")
    assert sheet_has(_MANAGER, '"/api/connectors/github/"+next')
    assert sheet_has(_MANAGER, "/api/connectors/github/disconnect")
    assert sheet_has(_MANAGER, "/api/connectors/google/drive/disconnect")
    assert sheet_has(_MANAGER, "padiem:refresh-connector-status")
    # #7216 A9: the refresh listener lives in the connectors module now.
    assert sheet_has(_CONNECTORS, "padiem:refresh-connector-status")
    assert sheet_has(_MANAGER, 'button.dataset.confirmRemove === "yes"')
    assert not sheet_has(_MANAGER, "data-connection-state =")
    assert not sheet_has(_MANAGER, "localStorage")
    assert not sheet_has(_MANAGER, 'data-claw-connection="pc"')
    assert sheet_has(_CHIP, "Google 권한은 잠시 멈출 수 없어요")
    assert sheet_has(_CHIP, "https://myaccount.google.com/connections")
    assert sheet_has(_CHIP, 'rel="noopener noreferrer"')
    assert not sheet_has(_CHIP, "if(signedIn())void disconnectDrive();")


def test_permissions_link_stays_user_accessible_with_no_secret():
    assert html_has_attr("href", "/api/connectors/github/installations")
    assert sheet_has(_MANAGER, "show(githubPermissions, known && linked)")
    assert not sheet_has("index.html", "PADIEM_GITHUB_APP_CLIENT_SECRET")
    assert not sheet_has(_MANAGER, "PADIEM_GITHUB_APP_CLIENT_SECRET")


def test_connector_surface_refresh_is_generation_guarded():
    assert sheet_has(_MANAGER, 'document.getElementById("connectorsView")')
    assert sheet_has(_MANAGER, "const drive = document.querySelector(")
    assert not sheet_has(_MANAGER, "const drive = dialog?.querySelector(")
    assert sheet_has(_MANAGER, "if (!connectorSurfaceOpen()) return;")
    assert sheet_has(_MANAGER, "generation !== readGeneration || !connectorSurfaceOpen()")
    assert sheet_has(_MANAGER, 'attributeFilter:["data-state"]')
