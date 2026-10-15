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

# STEP 2-B4: CP read-through host composition focused tests.
import asyncio
from app import b66_cp_host_session as b66_host
from app.b66_cp_host_session import (
    B66PadiemCPHostComposer,
    resolve_b66_cp_drive_owner_from_padiem_session,
)


class _Shadow:
    def __init__(self, subject="canon-1"):
        self.auth_session_id = "sess-1"
        self.canonical_subject_id = subject
        self.session_revision = 1

    async def load_projection(self, user_id):
        return self


class _Authority:
    def __init__(self, sess):
        self.sess = sess
        self.reverse = A
        self.calls = []

    async def resolve_auth_session(self, *, session_id):
        assert session_id == "sess-1"
        return self.sess

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        self.calls.append((product_id, canonical_subject_id))
        return self.reverse


class _ContextStore:
    def __init__(self, subject="canon-1", product="b62"):
        self.subject = subject
        self.product = product
        self.reads = 0

    def resolve_existing(self, *, auth_session, now):
        self.reads += 1
        return SimpleNamespace(
            product_id=self.product,
            subject_id=self.subject,
            workspace_ref="workspace-a",
            actor_ref="actor-a",
        )


def _host_env(monkeypatch, *, owner=A, cp_subject="canon-1"):
    monkeypatch.setattr(b66_host, "auth_ready", lambda request: True, raising=False)
    from app import auth_routes
    monkeypatch.setattr(auth_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda request: owner)
    auth = _Authority(session(subject=cp_subject))
    context_store = _ContextStore(subject=cp_subject)
    return auth, context_store


def test_b66_step2b4_signed_host_link_proves_cp_reverse_and_context(monkeypatch):
    authority, contexts = _host_env(monkeypatch)
    composer = B66PadiemCPHostComposer(
        identity_shadow_store=_Shadow(),
        current_canonical_session_authority=authority,
        connector_context_store=contexts,
    )
    result = asyncio.run(composer.compose_owner_link(request=object()))
    assert result == B66VerifiedCPDriveOwnerLink(A, "workspace-a", "actor-a", "sess-1")
    assert authority.calls == [("b62", "canon-1")]
    assert contexts.reads == 1
    assert composer.production_host_composition_proven is False
    assert composer.safe_dict()["production_runtime_wired"] is False


@pytest.mark.parametrize("case", [
    "foreign-owner", "shadow-mismatch", "expired", "revoked",
    "foreign-context-subject", "foreign-context-product", "missing-reverse",
    "missing-context", "missing-shadow", "missing-authority",
])
def test_b66_step2b4_denies_missing_or_cross_owner_authority(monkeypatch, case):
    authority, contexts = _host_env(monkeypatch)
    shadow = _Shadow()
    if case == "foreign-owner":
        authority.reverse = B
    elif case == "shadow-mismatch":
        shadow = _Shadow("other-canonical-subject")
    elif case == "expired":
        authority.sess = session(expired=True)
    elif case == "revoked":
        authority.sess = session(state=AuthSessionState.REVOKED)
    elif case == "foreign-context-subject":
        contexts.subject = "other-canonical-subject"
    elif case == "foreign-context-product":
        contexts.product = "b54-padiem-claw"
    elif case == "missing-reverse":
        authority.resolve_product_user_for_subject = None
    elif case == "missing-context":
        contexts.resolve_existing = None
    elif case == "missing-shadow":
        shadow = None
    elif case == "missing-authority":
        authority = None
    with pytest.raises(ValueError):
        asyncio.run(resolve_b66_cp_drive_owner_from_padiem_session(
            request=object(), identity_shadow_store=shadow,
            current_canonical_session_authority=authority,
            connector_context_store=contexts,
        ))


def test_b66_step2b4_unsigned_owner_is_rejected(monkeypatch):
    authority, contexts = _host_env(monkeypatch, owner=None)
    with pytest.raises(ValueError, match="signed_padiem_session_required"):
        asyncio.run(resolve_b66_cp_drive_owner_from_padiem_session(
            request=object(), identity_shadow_store=_Shadow(),
            current_canonical_session_authority=authority,
            connector_context_store=contexts,
        ))
    assert contexts.reads == 0


def test_b66_step2b4_absent_host_composition_does_not_claim_live(monkeypatch):
    _host_env(monkeypatch)
    composer = B66PadiemCPHostComposer()
    with pytest.raises(ValueError, match="cp_host_authority_required"):
        asyncio.run(composer.compose_owner_link(request=object()))
    assert composer.safe_dict()["production_host_composition_proven"] is False
