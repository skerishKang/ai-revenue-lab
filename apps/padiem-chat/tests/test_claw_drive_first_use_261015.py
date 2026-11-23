"""First-use Drive OAuth directly; removal only in the existing Connectors settings."""
from _android_handoff_storage_guard import assert_session_storage_is_handoff_only

# #8060: shipped reads live in _support; the contracts below stay unchanged.
from _support import claw_drive_first_use_source as sheets

HTML = sheets.index_html()
APP = sheets.app()
GUIDE = sheets.guide()
CHIPS = sheets.chips()
MANAGER = sheets.manager()
CONNECTORS = sheets.connectors()


def test_first_off_starts_existing_trusted_google_oauth():
    # #7216 A9: the quick-connect flow moved into the connectors module; app.js
    # keeps the wire call and the OAuth-return handling (session guard below).
    assert 'padiem:drive-quick-connect' in GUIDE and 'padiem:drive-quick-connect' in CONNECTORS
    assert 'await loadConnectorStatus()' in CONNECTORS
    assert 'offered.click()' in CONNECTORS
    assert 'beginGoogleDriveConnect()' in CONNECTORS
    assert 'connectorsModule().wireConnectorsListeners();' in APP
    assert_session_storage_is_handoff_only(APP)


def test_drive_off_not_revocation_and_explicit_manage_delete():
    assert 'intent === "disconnect-drive"' not in GUIDE
    assert 'id="connectorDriveRemove"' in HTML
    assert 'claw-drive-account-management.js' in HTML
    assert 'if(signedIn())void disconnectDrive();' not in CHIPS
    assert 'Google 권한은 잠시 멈출 수 없어요' in CHIPS
    assert 'Google permissions cannot be paused' in CHIPS
    assert 'https://myaccount.google.com/connections' in CHIPS
    assert 'rel="noopener noreferrer"' in CHIPS
    assert '"/api/connectors/google/drive/disconnect"' in MANAGER
    assert 'if(!confirmed)' in MANAGER
    assert 'padiem:refresh-connector-status' in MANAGER
    assert 'const card = document.querySelector(' in MANAGER
    assert 'dialog?.querySelector' not in MANAGER
    assert 'localStorage' not in MANAGER


def test_no_windows_or_github_changes_in_management():
    assert 'data-claw-connection="pc"' not in MANAGER
    assert 'github' not in MANAGER.lower()
