from app.b66_drive_connection import (
    B66ControlPlaneDriveBindingAdapter,
    B66DriveConnectionStatus,
)


PROOF = {
    "status": "resolved",
    "connector_id": "google-drive",
    "workspace_ref": "ws-owner-a",
    "binding_ref": "binding-owner-a",
    "actor_ref": "actor-owner-a",
    "account_ref": "google-sub-a12345678",
}

NOT_CONNECTED_PROOF = {
    "status": "not_connected",
    "connector_id": "google-drive",
    "workspace_ref": "ws-owner-a",
}


def test_wrong_control_plane_connector_rejected():
    adapter = B66ControlPlaneDriveBindingAdapter()
    proof = dict(PROOF, connector_id="google-calendar")
    try:
        adapter.project_trusted_binding(owner_b66_user_id="b66-owner-a", binding_proof=proof)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong connector accepted")


def test_wrong_owner_link_denied():
    adapter = B66ControlPlaneDriveBindingAdapter()
    proof = dict(PROOF, owner_b66_user_id="b66-owner-b")
    try:
        adapter.project_trusted_binding(owner_b66_user_id="b66-owner-a", binding_proof=proof)
    except ValueError:
        pass
    else:
        raise AssertionError("control-plane owner cross-feed accepted")


def test_control_plane_verified_scope_is_read_only_and_requires_reconnect():
    adapter = B66ControlPlaneDriveBindingAdapter()
    record = adapter.project_trusted_binding(owner_b66_user_id="b66-owner-a", binding_proof=PROOF)
    assert record is not None
    assert record.status == B66DriveConnectionStatus.RECONNECT_REQUIRED
    assert record.reconnect_reason == "cp_reviewed_scope_mismatch"
    assert adapter.reviewed_cp_scope == "https://www.googleapis.com/auth/drive.readonly"
    assert record.scope == "https://www.googleapis.com/auth/drive.readonly"
    assert adapter.required_b66_scope == "https://www.googleapis.com/auth/drive.file"


def test_control_plane_scope_downgrade_from_file_scope_rejected():
    adapter = B66ControlPlaneDriveBindingAdapter()
    proof = dict(PROOF, scopes="https://www.googleapis.com/auth/drive.file")
    try:
        adapter.project_trusted_binding(owner_b66_user_id="b66-owner-a", binding_proof=proof)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid cp scope accepted")


def test_naked_account_string_is_not_authority():
    adapter = B66ControlPlaneDriveBindingAdapter()
    proof = {"google_sub": "google-sub-x12345678", "google_email": "x@example.test"}
    try:
        adapter.project_trusted_binding(owner_b66_user_id="b66-owner-a", binding_proof=proof)
    except ValueError:
        pass
    else:
        raise AssertionError("browser identity accepted")


def test_same_destination_account_does_not_cross_b66_authority():
    adapter = B66ControlPlaneDriveBindingAdapter()
    proof_a = dict(PROOF, account_ref="google-sub-shared12345")
    proof_b = dict(PROOF, account_ref="google-sub-shared12345", workspace_ref="ws-owner-b", binding_ref="binding-owner-b", actor_ref="actor-owner-b")
    status_a = adapter.status_from_proof("b66-owner-a", proof_a)
    status_b = adapter.status_from_proof("b66-owner-b", proof_b)
    assert status_a["verified_store_owner"] == "b66-owner-a"
    assert status_b["verified_store_owner"] == "b66-owner-b"
    assert status_a["destination_sub"] == status_b["destination_sub"]
    assert status_a["status"] == "reconnect_required"
    assert status_b["status"] == "reconnect_required"


def test_not_connected_proof_projects_not_connected():
    adapter = B66ControlPlaneDriveBindingAdapter()
    assert adapter.status_from_proof("b66-owner-a", NOT_CONNECTED_PROOF)["status"] == "not_connected"


def test_cp_proof_keyset_exactness():
    adapter = B66ControlPlaneDriveBindingAdapter()
    proof = dict(PROOF, extra=True)
    try:
        adapter.project_trusted_binding(owner_b66_user_id="b66-owner-a", binding_proof=proof)
    except ValueError:
        pass
    else:
        raise AssertionError("unexpected cp field accepted")


def test_no_public_scope_slot_in_binding_status():
    adapter = B66ControlPlaneDriveBindingAdapter()
    proof = dict(PROOF, account_ref="google-sub-a12345678")
    result = adapter.project_trusted_binding(owner_b66_user_id="b66-owner-a", binding_proof=proof).public_status()
    assert result["scope"] == "https://www.googleapis.com/auth/drive.readonly"
    assert "verified_store_owner" in result
    assert "destination_account" in result