from app.b66_drive_connection import (
    B66ReviewedDriveFileConsentPort,
    B66_REVIEWED_GOOGLE_DRIVE_FILE_CONNECTOR_ID,
    B66_REVIEWED_GOOGLE_DRIVE_FILE_SCOPE,
    CP_GOOGLE_DRIVE_REVIEWED_CONNECTOR_ID,
)


def test_public_consent_gate_is_default_denied():
    port = B66ReviewedDriveFileConsentPort()
    assert port.public_consent_gate == "DEFAULT_DENY"
    port.host_trusted("cgi-owner-a")
    try:
        port.enable_public_consent_gate(host_verified=False)
    except ValueError:
        pass
    else:
        raise AssertionError("unhosted public gate enabled")
    assert port.public_consent_gate == "DEFAULT_DENY"


def test_hosted_reviewed_consent_requires_exact_scope_and_connector():
    port = B66ReviewedDriveFileConsentPort()
    port.host_trusted("cgi-owner-a")
    for connector in ("google-drive", "b66-json", "foo"):
        try:
            port.project_requested_consent(owner_b66_user_id="cgi-owner-a", connector_id=connector, requested_scope=B66_REVIEWED_GOOGLE_DRIVE_FILE_SCOPE, trusted_host=True)
        except ValueError:
            pass
        else:
            raise AssertionError(f"wrong connector accepted: {connector}")
    for scope in ("https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive", B66_REVIEWED_GOOGLE_DRIVE_FILE_SCOPE + " "):
        try:
            port.project_requested_consent(owner_b66_user_id="cgi-owner-a", connector_id=B66_REVIEWED_GOOGLE_DRIVE_FILE_CONNECTOR_ID, requested_scope=scope, trusted_host=True)
        except ValueError:
            pass
        else:
            raise AssertionError(f"wrong scope accepted: {scope}")


def test_hosted_reviewed_consent_requires_trusted_host_and_keeps_gate_default():
    port = B66ReviewedDriveFileConsentPort()
    port.host_trusted("cgi-owner-a")
    result = port.project_requested_consent(owner_b66_user_id="cgi-owner-a", connector_id=B66_REVIEWED_GOOGLE_DRIVE_FILE_CONNECTOR_ID, requested_scope=B66_REVIEWED_GOOGLE_DRIVE_FILE_SCOPE, trusted_host=True)
    assert result["cp_google_drive_scope"] == "https://www.googleapis.com/auth/drive.readonly"
    assert result["uses_cp_shared_connector"] is False
    assert result["production_consent_activated"] is False
    assert port.public_consent_gate == "DEFAULT_DENY"
    assert result["reviewed_scope"] == B66_REVIEWED_GOOGLE_DRIVE_FILE_SCOPE
    assert result["verified_store_owner"] == "cgi-owner-a"


def test_owner_must_be_trusted_for_hosted_consent():
    port = B66ReviewedDriveFileConsentPort()
    try:
        port.project_requested_consent(owner_b66_user_id="", connector_id=B66_REVIEWED_GOOGLE_DRIVE_FILE_CONNECTOR_ID, requested_scope=B66_REVIEWED_GOOGLE_DRIVE_FILE_SCOPE, trusted_host=True)
    except ValueError:
        pass
    else:
        raise AssertionError("untrusted owner accepted")
    port.host_trusted("cgi-owner-a")
    try:
        port.project_requested_consent(owner_b66_user_id="cgi-owner-b", connector_id=B66_REVIEWED_GOOGLE_DRIVE_FILE_CONNECTOR_ID, requested_scope=B66_REVIEWED_GOOGLE_DRIVE_FILE_SCOPE, trusted_host=True)
    except ValueError:
        pass
    else:
        raise AssertionError("cross-owner hosted consent accepted")


def test_readonly_cp_connector_remains_distinct():
    port = B66ReviewedDriveFileConsentPort()
    assert port.cp_google_drive_connector_id() == "google-drive"
    assert port.cp_google_drive_connector_id() != port.reviewed_connector_id()
    assert port.reviewed_connector_id() == "b66-google-drive-file"