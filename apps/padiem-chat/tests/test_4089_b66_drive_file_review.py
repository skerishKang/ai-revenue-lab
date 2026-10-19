"""Provider-free #4089 Step 2B2. An OAuth consent plan is NOT activation."""
import pytest

from app.b66_cp_drive_boundary import B66VerifiedCPDriveOwnerLink
from app.b66_drive_file_consent import (
    B66DriveFileConsentPolicy,
    B66_DRIVE_FILE_CONSENT_CONNECTOR_ID,
    B66_DRIVE_FILE_CONSENT_DEFAULT_GATE,
    B66_DRIVE_FILE_SCOPE_ACTIVATED,
    B66_DRIVE_FILE_HOST_MAPPING_PROVEN,
)

A = "usr_" + "a" * 32
B = "usr_" + "b" * 32
FILE = "https://www.googleapis.com/auth/drive.file"
READ = "https://www.googleapis.com/auth/drive.readonly"


def link(owner=A, workspace="workspace-a", actor="actor-a"):
    return B66VerifiedCPDriveOwnerLink(
        owner_b66_user_id=owner, cp_workspace_ref=workspace,
        cp_actor_ref=actor,
    )


def selection(workspace="workspace-a", actor="actor-a", account="cp-ref-opaque"):
    return {
        "status": "resolved", "connector_id": "google-drive",
        "workspace_ref": workspace, "actor_ref": actor,
        "binding_ref": "binding-opaque", "account_ref": account,
    }


def plan(*, owner=A, verified=None, private=None, scope=FILE):
    return B66DriveFileConsentPolicy().project_host_review(
        authenticated_b66_user_id=owner,
        verified_link=link() if verified is None else verified,
        cp_private_selection=selection() if private is None else private,
        requested_scope=scope,
    )


def test_default_gate_keeps_oauth_disabled_and_no_host_runtime_claim():
    policy = B66DriveFileConsentPolicy()
    assert policy.public_consent_gate == "DEFAULT_DENY"
    assert B66_DRIVE_FILE_CONSENT_DEFAULT_GATE == "DEFAULT_DENY"
    assert B66_DRIVE_FILE_SCOPE_ACTIVATED is False
    assert B66_DRIVE_FILE_HOST_MAPPING_PROVEN is False


def test_scope_review_plan_is_non_executable_and_preserves_cp_readonly():
    projected = plan().safe_dict()
    assert projected["status"] == "host_only_review_plan"
    assert projected["reviewed_connector_id"] == B66_DRIVE_FILE_CONSENT_CONNECTOR_ID
    assert projected["reviewed_connector_id"] != "google-drive"
    assert projected["reviewed_scope"] == FILE
    assert projected["cp_google_drive_scope"] == READ
    assert projected["public_consent_gate"] == "DEFAULT_DENY"
    assert projected["production_consent_activated"] is False
    assert projected["cp_host_owner_runtime_proven"] is False


@pytest.mark.parametrize("scope", [READ, "https://www.googleapis.com/auth/drive",
    "", " ", FILE+" ", ["https://www.googleapis.com/auth/drive.file"], None])
def test_only_exact_b66_write_scope_is_reviewed(scope):
    with pytest.raises(ValueError, match="unreviewed"):
        plan(scope=scope)


def test_missing_owner_mapping_denied_even_if_cp_binding_exists():
    with pytest.raises(ValueError, match="verified_host"):
        B66DriveFileConsentPolicy().project_host_review(
            authenticated_b66_user_id=A, verified_link=None,
            cp_private_selection=selection(), requested_scope=FILE,
        )


def test_wrong_owner_mapping_denied():
    with pytest.raises(ValueError, match="owner_mismatch"):
        plan(owner=B)


@pytest.mark.parametrize("wrong", [
    {"status":"resolved","connector_id":"google-calendar","workspace_ref":"workspace-a",
     "binding_ref":"binding-opaque","actor_ref":"actor-a"},
    {**selection(), "workspace_ref":"workspace-b"},
    {**selection(), "actor_ref":"actor-b"},
    {**selection(), "refresh_token":"secret"},
    {**selection(), "scope":FILE},
    {**selection(), "google_sub":"browser-claimed"},
    {**selection(), "binding_ref":""},
    {"status":"resolved","connector_id":"google-drive","workspace_ref":"workspace-a"},
])
def test_cp_private_proof_validation_is_reused(wrong):
    with pytest.raises(ValueError):
        plan(private=wrong)


def test_no_cp_selection_requires_host_integration():
    with pytest.raises(ValueError, match="cp_private_selection_required"):
        B66DriveFileConsentPolicy().project_host_review(
            authenticated_b66_user_id=A, verified_link=link(),
            cp_private_selection=None, requested_scope=FILE,
        )


def test_not_connected_cp_does_not_create_write_consent():
    projected = plan(private={
        "status":"not_connected","connector_id":"google-drive",
        "workspace_ref":"workspace-a",
    }).safe_dict()
    assert projected["status"] == "host_only_review_plan"
    assert projected["production_consent_activated"] is False


def test_independent_owners_can_choose_same_cp_account_without_shared_grants():
    account="same-opaque-account-ref"
    first=plan(private=selection(account=account)).safe_dict()
    second=B66DriveFileConsentPolicy().project_host_review(
        authenticated_b66_user_id=B,
        verified_link=link(B,"workspace-b","actor-b"),
        cp_private_selection=selection("workspace-b","actor-b",account),
        requested_scope=FILE,
    ).safe_dict()
    assert first["verified_store_owner"] == A
    assert second["verified_store_owner"] == B
    assert first["destination_sub"] is second["destination_sub"] is None
    assert account not in str(first) and account not in str(second)
    assert "binding-opaque" not in str(first) and "binding-opaque" not in str(second)
