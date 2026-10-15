"""Provider-free #4089 Step 2-B1 — CP read-only evidence never grants B66 write."""

import pytest

from app.b66_cp_drive_boundary import (
    B66CPDriveBoundary,
    B66VerifiedCPDriveOwnerLink,
    B66_REQUIRED_DRIVE_SCOPE,
    CP_REVIEWED_DRIVE_SCOPE,
)

A = "usr_" + "a" * 32
B = "usr_" + "b" * 32


def link(owner=A, workspace="ws-a", actor="actor-a"):
    return B66VerifiedCPDriveOwnerLink(
        owner_b66_user_id=owner,
        cp_workspace_ref=workspace,
        cp_actor_ref=actor,
    )


def cp(workspace="ws-a", actor="actor-a", account="unverified-cp-account-ref"):
    return {
        "status": "resolved",
        "connector_id": "google-drive",
        "workspace_ref": workspace,
        "binding_ref": "binding-a",
        "actor_ref": actor,
        "account_ref": account,
    }


def test_not_yet_composed_host_mapping_defaults_to_unconnected():
    boundary = B66CPDriveBoundary()
    assert boundary.project_status(owner_b66_user_id=A, cp_private_selection=cp())["status"] == "not_connected"
    assert boundary.project_status(owner_b66_user_id=A)["status"] == "not_connected"


def test_cp_readonly_binding_never_activates_b66_drive_file():
    result = B66CPDriveBoundary().project_status(
        owner_b66_user_id=A, cp_private_selection=cp(), verified_link=link()
    )
    assert CP_REVIEWED_DRIVE_SCOPE.endswith("/drive.readonly")
    assert B66_REQUIRED_DRIVE_SCOPE.endswith("/drive.file")
    assert result["status"] == "reconnect_required"
    assert result["reconnect_reason"] == "cp_reviewed_scope_mismatch"
    assert result["scope"] == B66_REQUIRED_DRIVE_SCOPE
    assert result["durable_credential_backend"] == "ABSENT_NOT_PROVEN"


def test_cp_account_ref_is_not_misrepresented_as_google_sub():
    result = B66CPDriveBoundary().project_status(
        owner_b66_user_id=A, cp_private_selection=cp(account="private-cp-account-ref"),
        verified_link=link(),
    )
    assert result["destination_sub"] is None
    assert result["destination_account"] is None
    assert "private-cp-account-ref" not in str(result)


@pytest.mark.parametrize("unverified", [
    {"status": "resolved", "connector_id": "google-calendar", "workspace_ref": "ws-a", "binding_ref": "b", "actor_ref": "actor-a"},
    {**cp(), "refresh_token": "secret"},
    {**cp(), "scopes": ["https://www.googleapis.com/auth/drive.file"]},
    {**cp(), "google_sub": "claimed"},
    {**cp(), "workspace_ref": "ws-other"},
    {**cp(), "actor_ref": "actor-other"},
    {**cp(), "binding_ref": ""},
    {"status": "resolved", "connector_id": "google-drive", "workspace_ref": "ws-a"},
    {"status": "not_connected", "connector_id": "google-drive", "workspace_ref": "ws-a", "actor_ref": "actor-a"},
])
def test_invalid_or_client_influenced_private_cp_projection_rejected(unverified):
    with pytest.raises(ValueError):
        B66CPDriveBoundary().project_status(
            owner_b66_user_id=A, cp_private_selection=unverified, verified_link=link()
        )


def test_not_connected_exact_private_keyset():
    result = B66CPDriveBoundary().project_status(
        owner_b66_user_id=A,
        cp_private_selection={"status": "not_connected", "connector_id": "google-drive", "workspace_ref": "ws-a"},
        verified_link=link(),
    )
    assert result["status"] == "not_connected"
    assert result["destination_sub"] is None


def test_wrong_owner_or_untyped_link_denied():
    boundary = B66CPDriveBoundary()
    with pytest.raises(ValueError):
        boundary.project_status(owner_b66_user_id=B, cp_private_selection=cp(), verified_link=link())
    with pytest.raises(ValueError):
        boundary.project_status(owner_b66_user_id=A, cp_private_selection=cp(), verified_link={"owner_b66_user_id": A})
    with pytest.raises(ValueError):
        boundary.project_status(owner_b66_user_id="forged-owner", cp_private_selection=cp())


def test_independent_b66_owners_can_choose_same_cp_account_without_grant_sharing():
    boundary = B66CPDriveBoundary()
    account = "cp-account-ref-same"
    sa = boundary.project_status(owner_b66_user_id=A, cp_private_selection=cp(account=account), verified_link=link())
    sb = boundary.project_status(owner_b66_user_id=B,
        cp_private_selection=cp(workspace="ws-b", actor="actor-b", account=account),
        verified_link=link(B,"ws-b","actor-b"))
    assert sa["verified_store_owner"] == A
    assert sb["verified_store_owner"] == B
    assert sa["destination_sub"] is sb["destination_sub"] is None
    assert sa["status"] == sb["status"] == "reconnect_required"
    assert "binding-a" not in str(sa)
    assert "binding-a" not in str(sb)


def test_revocation_and_unconfigured_mapping_are_not_connected():
    boundary = B66CPDriveBoundary()
    assert boundary.project_status(owner_b66_user_id=A, cp_private_selection=None, verified_link=link())["status"] == "not_connected"
    assert boundary.project_status(owner_b66_user_id=A, cp_private_selection=cp(), verified_link=None)["status"] == "not_connected"
