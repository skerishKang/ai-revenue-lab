"""#4089 STEP2B3: CP session and owner-link boundary, provider-free."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, IdentityLinkState, ProductIdentityLink, SubjectType
from app.b66_cp_drive_boundary import B66VerifiedCPDriveOwnerLink, B66_REQUIRED_DRIVE_SCOPE
from app.b66_cp_host_session import (
    UnconfiguredB66HostCPSessionPort, B66HostCPSessionFactory,
    validate_canonical_cp_drive_owner_link, B66_CP_HOST_SESSION_PROVEN,
    B66_CP_HOST_COMPOSITION_PROVEN, B66_CP_AUTH_SESSION_TO_CP,
)
A = "usr_" + "a"*32
B = "usr_" + "b"*32

def now():
    return datetime.now(timezone.utc)

def session(*, subject="canon-1", product="b62", state=AuthSessionState.ACTIVE, expired=False):
    t = now()
    return AuthSessionSnapshot(
        session_id="sess-1", product_id=product,
        subject=CanonicalSubjectRef(SubjectType.USER, subject),
        issued_at=t-timedelta(minutes=10),
        expires_at=t-timedelta(seconds=1) if expired else t+timedelta(minutes=10),
        state=state,
    )

def link(*, owner=A, subject="canon-1", product="b62", state=IdentityLinkState.ACTIVE):
    return ProductIdentityLink(
        product_id=product, product_user_id=owner, canonical_subject_id=subject, state=state,
    )

def context(*, subject="canon-1"):
    return SimpleNamespace(subject_id=subject, workspace_ref="ws-a", actor_ref="actor-a")

def valid(**changes):
    args=dict(owner_b66_user_id=A, cp_auth_session=session(), cp_product_link=link(),
              cp_connector_context=context(), now=now())
    args.update(changes)
    return validate_canonical_cp_drive_owner_link(**args)

def test_default_unconfigured_port_denies():
    port=UnconfiguredB66HostCPSessionPort()
    with pytest.raises(ValueError,match="not_composed"):
        port.resolve_verified_cp_drive_owner_link(A)
    assert B66_CP_HOST_SESSION_PROVEN is False
    assert B66_CP_HOST_COMPOSITION_PROVEN is False
    assert port.safe_dict()["production_host_composition_proven"] is False

def test_current_canonical_session_owner_and_context_bound():
    result=valid()
    assert isinstance(result,B66VerifiedCPDriveOwnerLink)
    assert (result.owner_b66_user_id,result.cp_workspace_ref,result.cp_actor_ref)==(A,"ws-a","actor-a")
    for changes in [
        dict(cp_auth_session=None),dict(cp_product_link=None),
        dict(cp_auth_session=SimpleNamespace(subject_id="canon-1")),
        dict(cp_auth_session=session(product="b54-padiem-claw")),
        dict(cp_auth_session=session(state=AuthSessionState.REVOKED)),
        dict(cp_auth_session=session(expired=True)),
        dict(cp_product_link=link(owner=B)),
        dict(cp_product_link=link(subject="different")),
        dict(cp_product_link=link(product="b54-padiem-claw")),
        dict(cp_product_link=link(state=IdentityLinkState.REVOKED)),
        dict(cp_connector_context=context(subject="different")),
        dict(cp_connector_context=SimpleNamespace(workspace_ref="ws-a",actor_ref="actor-a")),
        dict(owner_b66_user_id=B),dict(now=datetime(2026,10,16)),
    ]:
        with pytest.raises(ValueError):
            valid(**changes)

def test_valid_other_canonical_subject_when_link_and_context_match():
    assert isinstance(valid(cp_auth_session=session(subject="canon-2"),
                            cp_product_link=link(subject="canon-2"),
                            cp_connector_context=context(subject="canon-2")),
                      B66VerifiedCPDriveOwnerLink)

def test_injected_factory_cannot_claim_live_host_proof_or_accept_foreign_owner():
    assert B66_CP_AUTH_SESSION_TO_CP=="IDENTIFIED_UNWIRED"
    factory=B66HostCPSessionFactory()
    with pytest.raises(ValueError,match="not_composed"):
        factory.resolve_verified_cp_drive_owner_link(A)
    assert B66_REQUIRED_DRIVE_SCOPE.endswith("/drive.file")
    good=B66VerifiedCPDriveOwnerLink(A,"ws-a","actor-a")
    factory=B66HostCPSessionFactory(SimpleNamespace(resolve_verified_cp_drive_owner_link=lambda *a,**k: good))
    assert factory.resolve_verified_cp_drive_owner_link(A)==good
    assert factory.production_host_composition_proven is False
    assert factory.safe_dict()["server_verified_padiem_session_to_cp_link"] is False
    bad=B66VerifiedCPDriveOwnerLink(B,"ws-b","actor-b")
    factory=B66HostCPSessionFactory(SimpleNamespace(resolve_verified_cp_drive_owner_link=lambda *a,**k: bad))
    with pytest.raises(ValueError,match="cp_owner_link_mismatch"):
        factory.resolve_verified_cp_drive_owner_link(A)
    factory=B66HostCPSessionFactory(SimpleNamespace(resolve_verified_cp_drive_owner_link=lambda *a,**k: "bad"))
    with pytest.raises(ValueError,match="invalid_cp_owner_link"):
        factory.resolve_verified_cp_drive_owner_link(A)
