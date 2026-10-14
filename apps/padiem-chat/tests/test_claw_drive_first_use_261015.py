"""First-use Drive OAuth directly; removal only in the existing Connectors settings."""
from pathlib import Path

STATIC=Path(__file__).resolve().parents[1] / "static"
HTML=(STATIC/"index.html").read_text(encoding="utf-8")
APP=(STATIC/"app.js").read_text(encoding="utf-8")
GUIDE=(STATIC/"claw-connection-guide.js").read_text(encoding="utf-8")
CHIPS=(STATIC/"claw-connection-chips.js").read_text(encoding="utf-8")
MANAGER=(STATIC/"claw-drive-account-management.js").read_text(encoding="utf-8")


def test_first_off_starts_existing_trusted_google_oauth():
    assert 'padiem:drive-quick-connect' in GUIDE and 'padiem:drive-quick-connect' in APP
    assert 'await loadConnectorStatus()' in APP
    assert 'offered.click()' in APP
    assert 'beginGoogleDriveConnect()' in APP
    assert 'sessionStorage' not in APP


def test_drive_off_not_revocation_and_explicit_manage_delete():
    assert 'intent === "disconnect-drive"' not in GUIDE
    assert 'id="connectorDriveRemove"' in HTML
    assert 'claw-drive-account-management.js' in HTML
    assert 'if(signedIn())void disconnectDrive();' not in CHIPS
    assert 'Google Drive 일시 중지는 아직 준비 중' in CHIPS
    assert '"/api/connectors/google/drive/disconnect"' in MANAGER
    assert 'if(!confirmed)' in MANAGER
    assert 'padiem:refresh-connector-status' in MANAGER
    assert 'localStorage' not in MANAGER


def test_no_windows_or_github_changes_in_management():
    assert 'data-claw-connection="pc"' not in MANAGER
    assert 'github' not in MANAGER.lower()
