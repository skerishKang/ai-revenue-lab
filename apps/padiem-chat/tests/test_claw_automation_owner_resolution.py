"""#2833 S-2 owner-resolution authority boundary tests.

Proves the boundary turns an opaque ``owner_ref`` into a bounded trusted owner context
only through injected authority plus a freshly validated canonical session, and that it
fails closed on every shortcut. No writes of any kind are exercised: the module has no
run-history / task / alert write path, no P01 call and no dispatch surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

from app.claw_automation_owner_resolution import (
    ClawAutomationOwnerResolver,
    ResolvedAutomationOwner,
    TrustedAutomationOwnerProjection,
)
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_shadow import IdentityShadowRecord

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace_a"
FOREIGN_WORKSPACE = "workspace_b"
OWNER = "owner:opaque:0001"
MEMBER = "member_0001"
PRODUCT_USER = "usr_0123456789abcdef0123456789abcdef"
SUBJECT = "subject:padiem:user:123"
SESSION = "authsession:b62:123"
AUTH_REF = "authority:owner:registry"


def canonical_session(*, state=AuthSessionState.ACTIVE, revision=1, subject=SUBJECT):
    return AuthSessionSnapshot(
        session_id=SESSION,
        product_id="b62",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=2),
        state=state,
        revision=revision,
    )


def shadow_record(*, revision=1, subject=SUBJECT) -> IdentityShadowRecord:
    return IdentityShadowRecord(
        product_user_id=PRODUCT_USER,
        canonical_subject_id=subject,
        auth_session_id=SESSION,
        session_revision=revision,
        session_state="active",
        session_expires_at=NOW + timedelta(hours=2),
        observed_at=NOW - timedelta(minutes=5),
    )


def owner_projection(**overrides) -> TrustedAutomationOwnerProjection:
    values = {
        "owner_ref": OWNER,
        "workspace_id": WORKSPACE,
        "product_user_id": PRODUCT_USER,
        "member_id": MEMBER,
        "canonical_subject_id": SUBJECT,
        "authority_ref": AUTH_REF,
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return TrustedAutomationOwnerProjection(**values)


class MemoryShadowStore:
    def __init__(self, record=None):
        self.record = record

    async def save_projection(self, value):  # pragma: no cover - unused here
        raise AssertionError("owner resolution must never write to the shadow store")

    async def load_projection(self, product_user_id):
        if self.record is not None and self.record.product_user_id == product_user_id:
            return self.record
        return None


class SessionAuthority:
    def __init__(self, session=None, *, raises=None):
        self.session = session
        self.raises = raises
        self.calls: list[str] = []

    def resolve_auth_session(self, *, session_id):
        self.calls.append(session_id)
        if self.raises is not None:
            raise self.raises
        return self.session


class OwnerAuthority:
    def __init__(self, projection=None, *, returns=None):
        self.projection = projection
        self.returns = returns
        self.calls: list[tuple[str, str]] = []

    def resolve_automation_owner(self, *, owner_ref, workspace_id, now):
        self.calls.append((owner_ref, workspace_id))
        if self.returns is not None:
            return self.returns
        return self.projection


class EchoingOwnerAuthority(OwnerAuthority):
    """Adversarial authority that echoes the opaque owner token as an identity."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def resolve_automation_owner(self, *, owner_ref, workspace_id, now):
        self.calls.append((owner_ref, workspace_id))
        return owner_projection(owner_ref=owner_ref, product_user_id=self._token)


def resolver(*, owner_authority=None, session=None, record=..., raises=None):
    return ClawAutomationOwnerResolver(
        owner_authority=owner_authority,
        session_authority=SessionAuthority(session or canonical_session(), raises=raises),
        shadow_store=MemoryShadowStore(shadow_record() if record is ... else record),
    )


# --- trusted resolution -----------------------------------------------------


async def test_trusted_owner_resolution_passes_and_preserves_identifiers() -> None:
    authority = OwnerAuthority(owner_projection())
    resolution = resolver(owner_authority=authority)

    resolved = await resolution.resolve_owner(owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW)

    assert isinstance(resolved, ResolvedAutomationOwner)
    assert resolved.workspace_id == WORKSPACE
    assert resolved.owner_ref == OWNER
    assert resolved.product_user_id == PRODUCT_USER
    assert resolved.member_id == MEMBER
    assert resolved.canonical_subject_id == SUBJECT
    assert authority.calls == [(OWNER, WORKSPACE)]


async def test_resolution_mints_no_authority_and_stays_bounded() -> None:
    resolution = resolver(owner_authority=OwnerAuthority(owner_projection()))

    resolved = await resolution.resolve_owner(owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW)
    payload = resolved.safe_dict()

    assert payload["authority_minted"] is False
    for counter in (
        "credentials",
        "raw_auth_session",
        "provider_subject",
        "secrets",
        "execution_authority",
        "approval_authority",
    ):
        assert payload[counter] == 0, counter
    assert "session" not in payload
    assert "token" not in " ".join(payload).lower()


async def test_owner_ref_is_never_treated_as_an_identity() -> None:
    # owner_ref is opaque provenance: it must not equal / become the product user id,
    # the member id, or the principal ref.
    projection = owner_projection()
    assert projection.owner_ref != projection.product_user_id
    assert projection.owner_ref != projection.member_id

    # The boundary refuses any projection that echoes the opaque token as an identity.
    with pytest.raises(ValueError):
        owner_projection(product_user_id=OWNER)
    with pytest.raises(ValueError):
        owner_projection(member_id=OWNER + " with spaces")


# --- fail-closed: authority -------------------------------------------------


async def test_missing_owner_authority_fails_closed() -> None:
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=None).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.status_code == 503
    assert raised.value.code == "automation_owner_authority_unavailable"


async def test_client_minted_mapping_is_never_authority() -> None:
    authority = OwnerAuthority(returns={"owner_ref": OWNER, "workspace_id": WORKSPACE})
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.code == "automation_owner_projection_invalid"


async def test_owner_authority_returning_none_fails_closed() -> None:
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=OwnerAuthority(returns=None)).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.code == "automation_owner_projection_invalid"


async def test_foreign_workspace_fails_closed() -> None:
    authority = OwnerAuthority(owner_projection(workspace_id=FOREIGN_WORKSPACE))
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.status_code == 403
    assert raised.value.code == "automation_owner_workspace_mismatch"


async def test_owner_ref_mismatch_fails_closed() -> None:
    authority = OwnerAuthority(owner_projection(owner_ref="owner:opaque:9999"))
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.status_code == 403
    assert raised.value.code == "automation_owner_mismatch"


async def test_expired_projection_fails_closed() -> None:
    authority = OwnerAuthority(
        owner_projection(issued_at=NOW - timedelta(hours=3), expires_at=NOW - timedelta(hours=1))
    )
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.status_code == 401
    assert raised.value.code == "automation_owner_projection_inactive"


async def test_not_yet_valid_projection_fails_closed() -> None:
    authority = OwnerAuthority(
        owner_projection(issued_at=NOW + timedelta(hours=1), expires_at=NOW + timedelta(hours=2))
    )
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.code == "automation_owner_projection_inactive"


async def test_failing_owner_authority_fails_closed() -> None:
    class Exploding(OwnerAuthority):
        def resolve_automation_owner(self, *, owner_ref, workspace_id, now):
            raise RuntimeError("authority down")

    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=Exploding()).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.code == "automation_owner_authority_unavailable"


# --- fail-closed: canonical session ----------------------------------------


async def test_missing_identity_shadow_fails_closed() -> None:
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=OwnerAuthority(owner_projection()), record=None).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.status_code == 503
    assert raised.value.code == "control_plane_identity_not_linked"


@pytest.mark.parametrize("state", [AuthSessionState.REVOKED, AuthSessionState.EXPIRED])
async def test_inactive_canonical_session_fails_closed(state) -> None:
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(
            owner_authority=OwnerAuthority(owner_projection()),
            session=canonical_session(state=state),
        ).resolve_owner(owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW)
    assert raised.value.status_code == 401
    assert raised.value.code == "control_plane_session_inactive"


async def test_session_revision_rollback_fails_closed() -> None:
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(
            owner_authority=OwnerAuthority(owner_projection()),
            session=canonical_session(revision=1),
            record=shadow_record(revision=4),
        ).resolve_owner(owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW)
    assert raised.value.status_code == 403
    assert raised.value.code == "control_plane_session_mismatch"


async def test_canonical_subject_mismatch_fails_closed() -> None:
    authority = OwnerAuthority(owner_projection(canonical_subject_id="subject:padiem:user:other"))
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.status_code == 403
    assert raised.value.code == "automation_owner_subject_mismatch"


async def test_shadow_pointer_mismatch_fails_closed() -> None:
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(
            owner_authority=OwnerAuthority(owner_projection()),
            record=shadow_record(subject="subject:padiem:user:shadow"),
        ).resolve_owner(owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW)
    assert raised.value.code == "control_plane_session_mismatch"


# --- fail-closed: input shapes ---------------------------------------------


@pytest.mark.parametrize("bad", ["user_abc", "", 123, None, "x" * 81, "usr_" + "a" * 77])
def test_invalid_product_user_id_is_refused(bad) -> None:
    with pytest.raises(ValueError):
        owner_projection(product_user_id=bad)


@pytest.mark.parametrize(
    "valid",
    [
        PRODUCT_USER,                 # usr_ + 32 hex (the historical generator shape)
        "usr_abc",                    # short non-hex ids stay valid
        "usr_google_user_01",         # provider-style id with underscores
        "usr_" + "a" * 76,            # exactly the 80 character boundary
    ],
)
def test_product_user_id_reuses_the_canonical_b62_contract(valid) -> None:
    # The new module must not introduce a tighter or looser grammar than the existing
    # B62 contract (TrustedProductAuthEvidence / auth.py session read: usr_ + <= 80).
    assert owner_projection(product_user_id=valid).product_user_id == valid
    assert len(valid) <= 80


def test_product_user_id_boundary_is_exactly_eighty() -> None:
    assert len("usr_" + "a" * 76) == 80
    with pytest.raises(ValueError):
        owner_projection(product_user_id="usr_" + "a" * 77)  # 81 characters


@pytest.mark.parametrize("bad", ["", "member id", "member\n1", 42, None, "x" * 200])
def test_invalid_member_id_is_refused(bad) -> None:
    with pytest.raises(ValueError):
        owner_projection(member_id=bad)


@pytest.mark.parametrize("bad", ["", "owner with spaces\n", 7, None])
async def test_invalid_owner_ref_argument_is_refused(bad) -> None:
    with pytest.raises(ValueError):
        await resolver(owner_authority=OwnerAuthority(owner_projection())).resolve_owner(
            owner_ref=bad, workspace_id=WORKSPACE, now=NOW
        )


async def test_naive_now_is_refused() -> None:
    with pytest.raises(ValueError):
        await resolver(owner_authority=OwnerAuthority(owner_projection())).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=datetime(2026, 9, 22, 5, 0)
        )


def test_projection_lifetime_is_bounded() -> None:
    with pytest.raises(ValueError):
        owner_projection(expires_at=NOW + timedelta(hours=25))
    with pytest.raises(ValueError):
        owner_projection(issued_at=NOW, expires_at=NOW)


def test_resolved_owner_revalidates_shapes() -> None:
    with pytest.raises(ValueError):
        ResolvedAutomationOwner(
            workspace_id=WORKSPACE,
            owner_ref=OWNER,
            product_user_id="not-a-product-user",
            member_id=MEMBER,
            canonical_subject_id=SUBJECT,
        )


# --- mutation-style proofs --------------------------------------------------


async def test_m1_owner_ref_as_product_user_id_is_caught() -> None:
    """M1: an authority that echoes owner_ref as the product user id must be refused.

    Covers both an opaque-shaped token and a token that *looks* like a product user id:
    the token's shape never grants identity, and the shadow/session chain still has to
    vouch for the id the authority issued.
    """

    for token in (OWNER, "usr_looks_like_a_user"):
        with pytest.raises((ValueError, IdentityBridgeError)) as raised:
            await resolver(owner_authority=EchoingOwnerAuthority(token)).resolve_owner(
                owner_ref=token, workspace_id=WORKSPACE, now=NOW
            )
        if isinstance(raised.value, IdentityBridgeError):
            assert raised.value.code in {
                "automation_owner_authority_unavailable",
                "control_plane_identity_not_linked",
            }
        else:
            assert "product_user_id" in str(raised.value)


async def test_owner_ref_shape_grants_no_identity() -> None:
    """OWNER_REF_SHAPE_GRANTS_IDENTITY=NO, even for a usr_-shaped token."""

    looks_like_user = "usr_looks_like_a_user"

    # 1. Nothing is resolved from the token alone: the shadow/session chain rejects the
    #    echoed id because no canonical identity is linked for it.
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=EchoingOwnerAuthority(looks_like_user)).resolve_owner(
            owner_ref=looks_like_user, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.code == "control_plane_identity_not_linked"

    # 2. The same token resolves only through the identity the authority issued, and the
    #    resolved product user id is the authority's, never the token.
    resolved = await resolver(
        owner_authority=OwnerAuthority(owner_projection(owner_ref=looks_like_user))
    ).resolve_owner(owner_ref=looks_like_user, workspace_id=WORKSPACE, now=NOW)
    assert resolved.owner_ref == looks_like_user
    assert resolved.product_user_id == PRODUCT_USER
    assert resolved.product_user_id != looks_like_user


async def test_m2_removing_canonical_session_refresh_is_caught() -> None:
    """M2: with the canonical session unavailable, resolution must fail (no shadow-only trust)."""

    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(
            owner_authority=OwnerAuthority(owner_projection()),
            raises=RuntimeError("control plane unavailable"),
        ).resolve_owner(owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW)
    assert raised.value.code in {"control_plane_session_unavailable", "control_plane_identity_not_linked"}


async def test_m3_foreign_workspace_acceptance_is_caught() -> None:
    """M3: accepting a projection for another workspace must be impossible."""

    authority = OwnerAuthority(owner_projection(workspace_id=FOREIGN_WORKSPACE))
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.code == "automation_owner_workspace_mismatch"


async def test_m4_expired_projection_acceptance_is_caught() -> None:
    """M4: accepting an expired projection must be impossible."""

    authority = OwnerAuthority(
        owner_projection(issued_at=NOW - timedelta(hours=4), expires_at=NOW - timedelta(hours=2))
    )
    with pytest.raises(IdentityBridgeError) as raised:
        await resolver(owner_authority=authority).resolve_owner(
            owner_ref=OWNER, workspace_id=WORKSPACE, now=NOW
        )
    assert raised.value.code == "automation_owner_projection_inactive"
