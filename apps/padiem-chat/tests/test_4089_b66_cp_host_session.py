import pytest
from datetime import datetime, timezone

from app.b66_cp_drive_boundary import (
    B66VerifiedCPDriveOwnerLink,
    B66_REQUIRED_DRIVE_SCOPE,
)
from app.b66_cp_host_session import (
    UnconfiguredB66HostCPSessionPort,
    B66HostCPSessionFactory,
    validate_canonical_cp_drive_owner_link,
    B66_CP_HOST_SESSION_PROVEN,
    B66_CP_HOST_COMPOSITION_PROVEN,
    B66_CP_AUTH_SESSION_TO_CP,
)


class Session:
    def __init__(self, subject_id="canon-1", active=True):
        self.subject_id = subject_id
        self.active = active

    def is_active(self, *, now):
        return self.active


class InactiveSession(Session):
    def __init__(self):
        super().__init__(active=False)


class Context:
    def __init__(self, subject_id="canon-1", workspace="ws-a", actor="actor-a"):
        self.subject_id = subject_id
        self.workspace_ref = workspace
        self.actor_ref = actor


A = "usr_" + "a" * 32


def now():
    return datetime.now(timezone.utc)


def test_host_session_defaults_are_fail_closed():
    port = UnconfiguredB66HostCPSessionPort()
    with pytest.raises(ValueError):
        port.resolve_verified_cp_drive_owner_link(A, now=now())
    assert B66_CP_HOST_SESSION_PROVEN is False
    assert B66_CP_HOST_COMPOSITION_PROVEN is False
    assert port.safe_dict()["production_host_composition_proven"] is False


def test_canonical_cp_validation_requires_server_authority():
    with pytest.raises(ValueError):
        validate_canonical_cp_drive_owner_link(owner_b66_user_id=A)
    with pytest.raises(ValueError):
        validate_canonical_cp_drive_owner_link(owner_b66_user_id=A, cp_auth_session=None, cp_connector_context=Context())
    with pytest.raises(ValueError):
        validate_canonical_cp_drive_owner_link(owner_b66_user_id=A, cp_auth_session=Session(), cp_connector_context=None)
    derived = validate_canonical_cp_drive_owner_link(owner_b66_user_id=A, cp_auth_session=Session(), cp_connector_context=Context(), now=now())
    assert isinstance(derived, B66VerifiedCPDriveOwnerLink)
    assert derived.owner_b66_user_id == A
    assert derived.cp_workspace_ref == "ws-a"


def test_inactive_subject_or_mismatch_is_denied():
    with pytest.raises(ValueError):
        validate_canonical_cp_drive_owner_link(owner_b66_user_id=A, cp_auth_session=InactiveSession(), cp_connector_context=Context(), now=now())
    with pytest.raises(ValueError):
        validate_canonical_cp_drive_owner_link(owner_b66_user_id=A, cp_auth_session=Session("canon-1"), cp_connector_context=Context("canon-2"), now=now())
    with pytest.raises(ValueError):
        validate_canonical_cp_drive_owner_link(owner_b66_user_id="forged-owner", cp_auth_session=Session(), cp_connector_context=Context())


def test_factory_does_not_claim_production_wiring():
    assert B66_CP_AUTH_SESSION_TO_CP == "IDENTIFIED_UNWIRED"
    factory = B66HostCPSessionFactory(None)
    assert factory.production_host_composition_proven is False
    with pytest.raises(ValueError):
        factory.resolve_verified_cp_drive_owner_link(A, now=now())
    assert B66_REQUIRED_DRIVE_SCOPE.endswith("/drive.file")