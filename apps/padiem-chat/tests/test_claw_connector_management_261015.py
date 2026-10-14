"""Connector management must separate reversible usage toggle from OAuth credential removal."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
MANAGER = (STATIC / "claw-connector-management.js").read_text(encoding="utf-8")
GUIDE = (STATIC / "claw-connection-guide.js").read_text(encoding="utf-8")
CHIP = (STATIC / "claw-connection-chips.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def test_existing_connectors_page_has_explicit_connect_and_remove_actions():
    for control in ("connectorGithubPrimary", "connectorGithubRemove",
                    "connectorGithubState", "connectorGithubPermissions",
                    "connectorDriveRemove", "connectorDriveFeedback"):
        assert f'id="{control}"' in HTML
    assert 'src="./claw-connector-management.js"' in HTML
    assert HTML.index('src="./app.js"') < HTML.index('src="./claw-connector-management.js"')
    assert 'data-google-connector-connect="google-drive"' in HTML
    assert '연결 삭제는 계정 인증을 제거하는 것' in HTML
    assert 'id="connectorComputerCard"' in HTML  # unchanged Windows area


def test_main_off_first_use_starts_real_provider_not_connector_workspace():
    assert 'padiem:drive-quick-connect' in GUIDE
    assert 'padiem:drive-quick-connect' in APP
    assert 'await loadConnectorStatus()' in APP
    assert 'offered.click()' in APP  # existing reviewed Drive ticket flow
    assert 'beginGoogleDriveConnect()' in APP
    assert '"/api/connectors/github/start"' in GUIDE
    assert 'window.location.assign("/api/connectors/github/start")' in GUIDE
    assert 'sessionStorage' not in APP
    assert 'openConnectorsDialog()' in APP
    assert 'claw-github=connected' in APP
    assert 'window.history.replaceState' in APP


def test_connection_management_never_forges_on_off_or_auto_deletes():
    assert '"/api/connectors/github/status"' in MANAGER
    assert '"/api/connectors/github/"+next' in MANAGER
    assert '"/api/connectors/github/disconnect"' in MANAGER
    assert '"/api/connectors/google/drive/disconnect"' in MANAGER
    assert 'padiem:refresh-connector-status' in MANAGER
    assert 'padiem:refresh-connector-status' in APP
    assert 'button.dataset.confirmRemove === "yes"' in MANAGER
    assert 'data-connection-state =' not in MANAGER
    assert 'localStorage' not in MANAGER
    assert 'data-claw-connection="pc"' not in MANAGER
    assert 'Google Drive 일시 중지는 아직 준비 중' in CHIP
    assert 'if(signedIn())void disconnectDrive();' not in CHIP


def test_permissions_link_stays_user_accessible_with_no_secret():
    assert 'href="/api/connectors/github/installations"' in HTML
    assert 'show(githubPermissions, known && linked)' in MANAGER
    assert 'PADIEM_GITHUB_APP_CLIENT_SECRET' not in HTML
    assert 'PADIEM_GITHUB_APP_CLIENT_SECRET' not in MANAGER
