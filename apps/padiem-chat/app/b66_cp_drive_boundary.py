"""#4089: private B66-to-Control-Plane Drive compatibility boundary.

A reviewed CP google-drive authorization currently has *drive.readonly* scope.
B66's independent customer-selected storage destination needs its own reviewed
Google grant; the old source precursor used *drive.file* and the final B66 host
uses the separate full-Drive connector. No public route, OAuth execution,
writable credential, or owner-to-CP mapping exists here. Only the authorized
server host may supply both the private CP selection and the separately
verified B66 owner/CP actor-workspace link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .b66_drive_connection import (
    B66DriveConnectionStatus,
    B66_DRIVE_DURABLE_CREDENTIAL_BACKEND,
)

CP_REVIEWED_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
B66_REQUIRED_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_B66_USER_RE = re.compile(r"^usr_[a-f0-9]{32}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,255}$")
_COMMON_KEYS = frozenset({"status", "connector_id", "workspace_ref"})
_RESOLVED_REQUIRED = _COMMON_KEYS | frozenset({"binding_ref", "actor_ref"})
_RESOLVED_OPTIONAL = frozenset({"account_ref"})


def _valid_ref(value: Any, *, owner: bool = False) -> str:
    pattern = _B66_USER_RE if owner else _REF_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("invalid_server_reference")
    return value


@dataclass(frozen=True, slots=True)
class B66VerifiedCPDriveOwnerLink:
    """Host-only evidence that the same verified B66 session maps to CP context.

    Merely constructing this value in a unit test is NOT proof that an actual
    production session resolver can create it. Production host composition is
    deliberately separate and remains NOT_PROVEN until wired and audited.
    """
    owner_b66_user_id: str
    cp_workspace_ref: str
    cp_actor_ref: str
    cp_session_id: str | None = None

    def __post_init__(self) -> None:
        _valid_ref(self.owner_b66_user_id, owner=True)
        _valid_ref(self.cp_workspace_ref)
        _valid_ref(self.cp_actor_ref)
        if self.cp_session_id is not None:
            _valid_ref(self.cp_session_id)


class B66CPDriveBoundary:
    """Fail-closed, bounded adapter over CP's PRIVATE binding selection fields.

    CP's GoogleOAuthBindingSelection.to_private_dict() yields the keys accepted
    here; CP credentials and private data must never go to the browser.
    The host MUST authenticate both the selection and verified_link. This class
    cannot mint a link, assert a Google sub, or activate drive.file authorization.
    """

    @staticmethod
    def _status(owner: str, *, requires_file_consent: bool = False) -> dict[str, Any]:
        return {
            "status": (
                B66DriveConnectionStatus.RECONNECT_REQUIRED.value
                if requires_file_consent
                else B66DriveConnectionStatus.NOT_CONNECTED.value
            ),
            "verified_store_owner": owner,
            "destination_account": None,
            "destination_sub": None,
            "scope": B66_REQUIRED_DRIVE_SCOPE,
            "reconnect_reason": "cp_reviewed_scope_mismatch" if requires_file_consent else None,
            "connected_at": None,
            "durable_credential_backend": B66_DRIVE_DURABLE_CREDENTIAL_BACKEND,
        }

    def project_status(
        self,
        *,
        owner_b66_user_id: str,
        cp_private_selection: Mapping[str, Any] | None = None,
        verified_link: B66VerifiedCPDriveOwnerLink | None = None,
    ) -> dict[str, Any]:
        owner = _valid_ref(owner_b66_user_id, owner=True)
        # No canonical host mapping means CP identity cannot be adopted as a
        # B66 owner; do not expose even an ostensibly resolved Google account.
        if verified_link is None:
            return self._status(owner)
        if not isinstance(verified_link, B66VerifiedCPDriveOwnerLink):
            raise ValueError("untrusted_owner_cp_link")
        if verified_link.owner_b66_user_id != owner:
            raise ValueError("owner_cp_link_mismatch")
        if cp_private_selection is None:
            return self._status(owner)
        if not isinstance(cp_private_selection, Mapping):
            raise ValueError("invalid_private_cp_selection")
        keys = frozenset(cp_private_selection)
        if not keys.issubset(_RESOLVED_REQUIRED | _RESOLVED_OPTIONAL):
            raise ValueError("unreviewed_cp_selection_fields")
        if cp_private_selection.get("connector_id") != "google-drive":
            raise ValueError("wrong_cp_connector")
        if _valid_ref(cp_private_selection.get("workspace_ref")) != verified_link.cp_workspace_ref:
            raise ValueError("workspace_mismatch")
        status = cp_private_selection.get("status")
        if status == "not_connected":
            if keys != _COMMON_KEYS:
                raise ValueError("invalid_not_connected_keyset")
            return self._status(owner)
        if status != "resolved" or not _RESOLVED_REQUIRED.issubset(keys):
            raise ValueError("invalid_resolved_keyset")
        if (
            _valid_ref(cp_private_selection.get("actor_ref"))
            != verified_link.cp_actor_ref
        ):
            raise ValueError("actor_mismatch")
        _valid_ref(cp_private_selection.get("binding_ref"))
        if "account_ref" in cp_private_selection:
            _valid_ref(cp_private_selection["account_ref"])
        # Even a genuine CP binding cannot supply B66's write scope. An opaque
        # CP account_ref is NOT a verified Google sub; keep identity redacted.
        return self._status(owner, requires_file_consent=True)
