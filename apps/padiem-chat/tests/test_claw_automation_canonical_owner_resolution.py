"""#3247 — canonical background owner resolution tests.

The background owner is derived exclusively from server-persisted canonical
rule facts plus the private Control Plane: exact active role-bearing tenant
membership, the B62 product-user reverse link and the current B54 canonical
session (#3243 reuse). ``owner_ref`` is provenance only. This suite proves the
happy contract and every fail-closed branch, at the resolver and at the
composition seam:

- CANONICAL_RULE_OWNER_RESOLUTION: rule subject + tenant resolves the owner
- B62_PRODUCT_USER_REVERSE_LOOKUP: identity comes from the B62 link, product
  pinned server-side; a B54 link can never substitute it
- MEMBER_ID_EQUALS_SERVER_B62_USER: the existing Task/Alert inbox contract
- CURRENT_B54_SESSION_REVALIDATED: subject/tenant equality + ACTIVE required
- EXACT_TENANT_SUBJECT_MEMBERSHIP: active AND role-bearing required
- OWNER_REF_AS_IDENTITY=0: shaped tokens, token changes and token reuse can
  never select, move or transfer identity
- composition supplies the persisted ``rule.canonical_subject_id`` and
  collapses every resolver refusal into one non-disclosing refusal
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
)
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from app.claw_automation_background_execution import _resolve_owner_or_none
from app.claw_automation_owner_resolution import (
    CANONICAL_AUTOMATION_OWNER_PRODUCT_ID,
    ClawAutomationOwnerResolver,
    ResolvedAutomationOwner,
)
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID, IdentityBridgeError

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
TENANT = "tenant_" + "a" * 32
FOREIGN_TENANT = "tenant_" + "b" * 32
SUBJECT = "sub_" + "c" * 32
FOREIGN_SUBJECT = "sub_" + "d" * 32
B62_USER = "usr_" + "1" * 32
B54_ONLY_USER = "usr_" + "2" * 32
B54_PRODUCT_ID = "b54-padiem-claw"
SESSION_ID = "sess_" + "e" * 32
OWNER_REF = "owner:opaque:0001"
RULE_ID = "rule_3247_1"


# ── fakes ───────────────────────────────────────────────────────────────────


def b54_session(
    *,
    subject: str = SUBJECT,
    tenant_id: str = TENANT,
    state: AuthSessionState = AuthSessionState.ACTIVE,
    product_id: str = B54_PRODUCT_ID,
) -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id=SESSION_ID,
        product_id=product_id,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=2),
        state=state,
        revision=1,
        tenant_id=tenant_id,
    )


def role_membership(
    *,
    tenant_id: str = TENANT,
    subject_id: str = SUBJECT,
    role: TenantMembershipRole | None = TenantMembershipRole.OWNER,
) -> TenantMembership:
    return TenantMembership(
        tenant_id=tenant_id,
        canonical_subject_id=subject_id,
        state=TenantMembershipState.ACTIVE,
        created_at=NOW - timedelta(days=1),
        role=role,
    )


class FakeCanonicalOwnerAuthority:
    """Fake of the private Control Plane adapter's canonical owner surface.

    Facts are bound to one (tenant, subject) pair and one per-product link
    table; anything else raises the exact codes the real adapter raises.
    """

    def __init__(
        self,
        *,
        member: TenantMembership | None = role_membership(),
        links: dict[str, str] | None = None,
        session: AuthSessionSnapshot | None = None,
        membership_exc: IdentityBridgeError | None = None,
        link_exc: IdentityBridgeError | None = None,
    ) -> None:
        self.member = member
        self.links = dict(links) if links is not None else {PADIEM_CHAT_PRODUCT_ID: B62_USER}
        self.session = session
        self.membership_exc = membership_exc
        self.link_exc = link_exc
        self.calls: list[tuple[str, ...]] = []

    async def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        self.calls.append(("membership", tenant_id, canonical_subject_id))
        if self.membership_exc is not None:
            raise self.membership_exc
        if (
            self.member is None
            or tenant_id != self.member.tenant_id
            or canonical_subject_id != self.member.canonical_subject_id
        ):
            raise IdentityBridgeError(
                403, "canonical_tenant_membership_not_found", "no such membership"
            )
        return self.member

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        self.calls.append(("link", product_id, canonical_subject_id))
        if self.link_exc is not None:
            raise self.link_exc
        if product_id not in self.links:
            raise IdentityBridgeError(
                401, "canonical_product_identity_link_not_found", "no such link"
            )
        return self.links[product_id]

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.calls.append(("session", product_id, product_user_id))
        if self.session is None or product_id != B54_PRODUCT_ID:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "no such session"
            )
        return self.session


def resolver(authority: FakeCanonicalOwnerAuthority | None) -> ClawAutomationOwnerResolver:
    return ClawAutomationOwnerResolver(
        owner_authority=None,
        session_authority=None,
        shadow_store=None,
        canonical_owner_authority=authority,
    )


async def resolve(authority: FakeCanonicalOwnerAuthority, **overrides) -> ResolvedAutomationOwner:
    kwargs = {
        "owner_ref": OWNER_REF,
        "workspace_id": TENANT,
        "canonical_subject_id": SUBJECT,
        "now": NOW,
    }
    kwargs.update(overrides)
    return await resolver(authority).resolve_owner(**kwargs)


# ── happy contract ──────────────────────────────────────────────────────────


async def test_canonical_rule_facts_resolve_owner():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    owner = await resolve(authority)

    assert isinstance(owner, ResolvedAutomationOwner)
    assert owner.workspace_id == TENANT
    assert owner.canonical_subject_id == SUBJECT
    assert owner.product_user_id == B62_USER
    assert owner.member_id == B62_USER
    assert owner.owner_ref == OWNER_REF
    # Exact chain order: membership -> B62 reverse link -> current B54 session.
    assert authority.calls == [
        ("membership", TENANT, SUBJECT),
        ("link", PADIEM_CHAT_PRODUCT_ID, SUBJECT),
        ("session", B54_PRODUCT_ID, B62_USER),
    ]


async def test_member_id_is_the_server_derived_b62_product_user():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    owner = await resolve(authority)

    # The existing claw_inbox_routes ownership contract: member_id == the B62
    # product user, never a separately minted member identity.
    assert owner.member_id == owner.product_user_id == B62_USER


async def test_products_are_pinned_server_side():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    await resolve(authority)

    looked_up_product = authority.calls[1][1]
    session_product = authority.calls[2][1]
    assert looked_up_product == PADIEM_CHAT_PRODUCT_ID == "b62"
    assert session_product == B54_PRODUCT_ID


# ── owner_ref is authority-free ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "shaped_ref",
    [
        "usr_" + "f" * 32,
        "sub_" + "f" * 32,
        "tenant_" + "f" * 32,
    ],
)
async def test_identity_shaped_owner_ref_grants_nothing(shaped_ref):
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    owner = await resolve(authority, owner_ref=shaped_ref)

    assert owner.product_user_id == B62_USER
    assert owner.member_id == B62_USER
    assert owner.canonical_subject_id == SUBJECT
    assert owner.workspace_id == TENANT
    assert owner.owner_ref == shaped_ref


async def test_changing_the_owner_ref_token_changes_nothing_but_the_token():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    first = await resolve(authority, owner_ref="owner:token:A")
    second = await resolve(authority, owner_ref="owner:token:B")

    assert first.product_user_id == second.product_user_id
    assert first.member_id == second.member_id
    assert first.canonical_subject_id == second.canonical_subject_id
    assert first.workspace_id == second.workspace_id
    assert first.owner_ref != second.owner_ref


async def test_same_owner_ref_cannot_transfer_identity_across_subjects():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    with pytest.raises(IdentityBridgeError):
        await resolve(authority, canonical_subject_id=FOREIGN_SUBJECT)
    with pytest.raises(IdentityBridgeError):
        await resolve(authority, workspace_id=FOREIGN_TENANT)


async def test_missing_owner_ref_fails_closed():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    with pytest.raises(ValueError):
        await resolve(authority, owner_ref="")


# ── canonical shape gates ───────────────────────────────────────────────────


async def test_non_canonical_workspace_fails_closed():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority, workspace_id="workspace_a")
    assert err.value.code == "automation_owner_workspace_invalid"
    assert authority.calls == [], "shape gates run before any authority call"


async def test_non_canonical_subject_fails_closed():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    for bad in ("subject:padiem:user:1", "usr_" + "3" * 32, "sub_short"):
        with pytest.raises(IdentityBridgeError) as err:
            await resolve(authority, canonical_subject_id=bad)
        assert err.value.code == "automation_owner_subject_invalid"
    assert authority.calls == []


async def test_missing_canonical_subject_fails_closed():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority, canonical_subject_id=None)
    assert err.value.status_code == 503


async def test_canonical_authority_is_required():
    with pytest.raises(IdentityBridgeError) as err:
        await resolve(None)
    assert err.value.status_code == 503


# ── membership revalidation ─────────────────────────────────────────────────


async def test_foreign_tenant_membership_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        member=role_membership(tenant_id=FOREIGN_TENANT), session=b54_session()
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "canonical_tenant_membership_not_found"


async def test_inactive_membership_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        membership_exc=IdentityBridgeError(
            401, "canonical_tenant_membership_inactive", "membership is not active"
        ),
        session=b54_session(),
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "canonical_tenant_membership_inactive"


async def test_roleless_membership_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        member=role_membership(role=None), session=b54_session()
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "automation_owner_membership_invalid"


async def test_foreign_subject_membership_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        member=role_membership(subject_id=FOREIGN_SUBJECT), session=b54_session()
    )

    with pytest.raises(IdentityBridgeError):
        await resolve(authority)


# ── B62 product-user reverse link ───────────────────────────────────────────


async def test_missing_b62_product_link_fails_closed():
    authority = FakeCanonicalOwnerAuthority(links={}, session=b54_session())

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "canonical_product_identity_link_not_found"


async def test_inactive_b62_product_link_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        link_exc=IdentityBridgeError(
            401, "canonical_product_identity_link_not_active", "link is not active"
        ),
        session=b54_session(),
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "canonical_product_identity_link_not_active"


async def test_ambiguous_b62_product_link_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        link_exc=IdentityBridgeError(
            503, "identity_authority_storage_error", "ambiguous link"
        ),
        session=b54_session(),
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "identity_authority_storage_error"


async def test_b54_product_link_cannot_substitute_the_b62_link():
    # Only a B54 link exists for the subject. The resolver must pin B62, refuse
    # the B54 link, and never fall back to its product user.
    authority = FakeCanonicalOwnerAuthority(links={B54_PRODUCT_ID: B54_ONLY_USER})

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "canonical_product_identity_link_not_found"
    assert ("link", PADIEM_CHAT_PRODUCT_ID, SUBJECT) in authority.calls
    assert all(call[1] == PADIEM_CHAT_PRODUCT_ID for call in authority.calls if call[0] == "link")


async def test_malformed_product_user_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        links={PADIEM_CHAT_PRODUCT_ID: "not-a-product-user"},
        session=b54_session(),
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "automation_owner_product_user_invalid"


# ── current B54 session revalidation (#3243 reuse) ──────────────────────────


async def test_missing_current_b54_session_fails_closed():
    authority = FakeCanonicalOwnerAuthority(session=None)

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    # The #3243 bridge masks the underlying authority code behind its own
    # non-disclosing unavailable error; either way the resolution fails closed.
    assert err.value.code == "b54_control_plane_session_unavailable"


async def test_inactive_current_b54_session_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        session=b54_session(state=AuthSessionState.REVOKED)
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "b54_control_plane_session_inactive"


async def test_b54_session_subject_mismatch_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        session=b54_session(subject=FOREIGN_SUBJECT)
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "automation_owner_subject_mismatch"


async def test_b54_session_tenant_mismatch_fails_closed():
    authority = FakeCanonicalOwnerAuthority(
        session=b54_session(tenant_id=FOREIGN_TENANT)
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "automation_owner_workspace_mismatch"


async def test_b62_session_is_never_b54_authority():
    authority = FakeCanonicalOwnerAuthority(
        session=b54_session(product_id=PADIEM_CHAT_PRODUCT_ID)
    )

    with pytest.raises(IdentityBridgeError) as err:
        await resolve(authority)
    assert err.value.code == "b54_control_plane_session_mismatch"


async def test_resolved_owner_mints_no_authority():
    authority = FakeCanonicalOwnerAuthority(session=b54_session())

    owner = await resolve(authority)

    safe = owner.safe_dict()
    assert safe["credentials"] == 0
    assert safe["raw_auth_session"] == 0
    assert safe["provider_subject"] == 0
    assert safe["secrets"] == 0
    assert safe["execution_authority"] == 0
    assert safe["approval_authority"] == 0
    assert safe["authority_minted"] is False


# ── composition seam ────────────────────────────────────────────────────────


def background_rule(*, owner_ref: str | None = OWNER_REF) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=RULE_ID,
        workspace_id=TENANT,
        name="Nightly check",
        schedule=ClawScheduleExpression(ClawScheduleKind.CRON, "0 3 * * *", "UTC"),
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.ALERT,
        owner_ref=owner_ref,
        canonical_subject_id=SUBJECT,
    )


class SpyResolver:
    def __init__(self, owner: ResolvedAutomationOwner | None):
        self.owner = owner
        self.kwargs: dict | None = None

    async def resolve_owner(self, **kwargs):
        self.kwargs = kwargs
        if self.owner is None:
            raise IdentityBridgeError(403, "automation_owner_mismatch", "refused")
        return self.owner


async def test_composition_supplies_the_persisted_canonical_subject():
    spy = SpyResolver(
        ResolvedAutomationOwner(
            workspace_id=TENANT,
            owner_ref=OWNER_REF,
            product_user_id=B62_USER,
            member_id=B62_USER,
            canonical_subject_id=SUBJECT,
        )
    )

    owner = await _resolve_owner_or_none(
        resolver=spy,
        rule=background_rule(),
        workspace_id=TENANT,
        observed_at=NOW,
    )

    assert owner is not None
    assert spy.kwargs["canonical_subject_id"] == SUBJECT
    assert spy.kwargs["workspace_id"] == TENANT
    assert spy.kwargs["owner_ref"] == OWNER_REF
    assert spy.kwargs["now"] == NOW


async def test_composition_collapses_resolver_refusals_to_one_refusal():
    owner = await _resolve_owner_or_none(
        resolver=SpyResolver(None),
        rule=background_rule(),
        workspace_id=TENANT,
        observed_at=NOW,
    )
    assert owner is None


async def test_composition_fails_closed_on_missing_owner_ref():
    owner = await _resolve_owner_or_none(
        resolver=SpyResolver(None),
        rule=background_rule(owner_ref=None),
        workspace_id=TENANT,
        observed_at=NOW,
    )
    assert owner is None


async def test_composition_refuses_a_foreign_workspace_owner():
    spy = SpyResolver(
        ResolvedAutomationOwner(
            workspace_id=FOREIGN_TENANT,
            owner_ref=OWNER_REF,
            product_user_id=B62_USER,
            member_id=B62_USER,
            canonical_subject_id=SUBJECT,
        )
    )

    owner = await _resolve_owner_or_none(
        resolver=spy,
        rule=background_rule(),
        workspace_id=TENANT,
        observed_at=NOW,
    )
    assert owner is None
