"""B66 #4089: distinct drive.file consent *plan*, NOT an active OAuth connector.

Current CP google-drive review is drive.readonly. The reviewed CP ingress/store
does not recognize b66-google-drive-file or its writable scope. The separate
B66 sign-in owner and independent Google storage destination remain independent.
This private, source-only policy cannot start an OAuth flow, authorize an
account, issue a token, grant write access, or claim Production host wiring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .b66_cp_drive_boundary import (
    B66CPDriveBoundary,
    B66VerifiedCPDriveOwnerLink,
    B66_REQUIRED_DRIVE_SCOPE,
    CP_REVIEWED_DRIVE_SCOPE,
)

B66_DRIVE_FILE_CONSENT_CONNECTOR_ID = "b66-google-drive-file"
B66_DRIVE_FILE_CONSENT_DEFAULT_GATE = "DEFAULT_DENY"
B66_DRIVE_FILE_SCOPE_ACTIVATED = False
B66_DRIVE_FILE_HOST_MAPPING_PROVEN = False


@dataclass(frozen=True, slots=True)
class B66DriveFileConsentPlan:
    """Non-executable host-only plan, carrying no Google account identity."""

    status: str
    owner_b66_user_id: str
    reviewed_connector_id: str
    requested_scope: str
    cp_shared_scope: str
    public_consent_gate: str = B66_DRIVE_FILE_CONSENT_DEFAULT_GATE
    production_consent_activated: bool = B66_DRIVE_FILE_SCOPE_ACTIVATED
    cp_host_owner_runtime_proven: bool = B66_DRIVE_FILE_HOST_MAPPING_PROVEN

    def safe_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "verified_store_owner": self.owner_b66_user_id,
            "reviewed_connector_id": self.reviewed_connector_id,
            "reviewed_scope": self.requested_scope,
            "cp_google_drive_scope": self.cp_shared_scope,
            "public_consent_gate": self.public_consent_gate,
            "production_consent_activated": self.production_consent_activated,
            "cp_host_owner_runtime_proven": self.cp_host_owner_runtime_proven,
            "destination_sub": None,
            "destination_account": None,
        }


class B66DriveFileConsentPolicy:
    """Private source-only scope gate over the existing CP link contract.

    The caller is required to be the already-authorized server host: this
    policy provides NO way to construct an independently trusted CP owner link
    from browser fields. The host wiring is NOT implemented by this class.
    """

    public_consent_gate = B66_DRIVE_FILE_CONSENT_DEFAULT_GATE

    def project_host_review(
        self,
        *,
        authenticated_b66_user_id: str,
        verified_link: B66VerifiedCPDriveOwnerLink | None,
        cp_private_selection: Mapping[str, Any] | None,
        requested_scope: str,
    ) -> B66DriveFileConsentPlan:
        if not isinstance(requested_scope, str) or requested_scope != B66_REQUIRED_DRIVE_SCOPE:
            raise ValueError("unreviewed_b66_drive_file_scope")
        if not isinstance(verified_link, B66VerifiedCPDriveOwnerLink):
            raise ValueError("verified_host_owner_cp_link_required")
        if verified_link.owner_b66_user_id != authenticated_b66_user_id:
            raise ValueError("b66_host_owner_mismatch")
        if cp_private_selection is None:
            raise ValueError("cp_private_selection_required")
        # This validates CP's reviewed connector/actor/workspace, exact private
        # keysets and owner mapping; no Drive write grant is inferred from it.
        cp_status = B66CPDriveBoundary().project_status(
            owner_b66_user_id=authenticated_b66_user_id,
            verified_link=verified_link,
            cp_private_selection=cp_private_selection,
        )
        if cp_status["status"] not in ("not_connected", "reconnect_required"):
            raise ValueError("unexpected_cp_drive_status")
        return B66DriveFileConsentPlan(
            status="host_only_review_plan",
            owner_b66_user_id=authenticated_b66_user_id,
            reviewed_connector_id=B66_DRIVE_FILE_CONSENT_CONNECTOR_ID,
            requested_scope=B66_REQUIRED_DRIVE_SCOPE,
            cp_shared_scope=CP_REVIEWED_DRIVE_SCOPE,
        )
