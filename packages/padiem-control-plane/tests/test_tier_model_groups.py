"""#4453 tier groups: explicit site choices + safe staged fallback contract."""
from __future__ import annotations

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.model_assignment_policy import (
    CatalogModel, ModelChange, ModelPolicySnapshot,
)
from padiem_control_plane.product_tier_routes import PLUS_HOLD_MODEL_ID
from padiem_control_plane.tier_model_groups import (
    TierModelGroup, SiteTierModelGroup, ProductModelPreference, StagedTierGroupSnapshot,
    preview_product_group, suggest_explicit_fallback,
)

A, B, C = "vendor/model-a", "other/model-b", "vendor/model-c"
CAT = {
    m: CatalogModel(m, True, True, True, True, frozenset({"chat"}))
    for m in (A, B, C)
}


def staged(*preferences):
    seen = set()
    site_groups = []
    for p in preferences:
        key = (p.product, p.tier)
        if key not in seen:
            seen.add(key)
            site_groups.append(SiteTierModelGroup(p.product, p.tier, (A, B, C)))
    return StagedTierGroupSnapshot(
        "padiem-global", 0, (TierModelGroup("PLUS", (A, B, C)),),
        tuple(preferences), tuple(site_groups),
    )


def prefs(product="chat", *, enabled=True, primary=A, backups=(B, C)):
    return ProductModelPreference(product, "PLUS", primary, backups, enabled)


def grants(*products, tier="PLUS", block=None):
    rules = []
    for product in ("central", *products):
        for model in (A, B, C):
            action = "block" if (product, model) == block else "allow"
            rules.append(ModelChange(product, tier, model, action))
    return ModelPolicySnapshot("padiem-global", 3, tuple(rules))


def preview(conf, product="chat", policy=None, fresh=True, caps=None, catalog=None):
    return preview_product_group(
        conf, product=product, tier="PLUS", workspace_id="padiem-global",
        policy=policy, catalog=CAT if catalog is None else catalog,
        capability_ready={m: True for m in CAT} if caps is None else caps,
        trusted_policy_fresh=fresh,
    )


def code(expected, callback):
    with pytest.raises(ControlPlaneContractError) as e:
        callback()
    assert e.value.code == expected


def test_same_tier_group_independent_chat_claw_b66_primary_and_fallback():
    group = staged(
        prefs("chat", primary=A, backups=(B,)),
        prefs("claw", primary=B, backups=(A,)),
        prefs("b66", primary=C, backups=(B,)),
    )
    policy = grants("chat", "claw", "b66")
    for product, primary, backup in (("chat", A, B), ("claw", B, A), ("b66", C, B)):
        v = preview(group, product, policy)
        assert v.primary_model_id == primary
        assert v.eligible_fallback_model_ids == (backup,)
        assert (v.persisted, v.runtime_enforced, v.dispatch_authorized) == (False, False, False)


def test_missing_policy_freshness_or_product_grant_never_makes_any_route_ready():
    group = staged(prefs())
    for policy, fresh in ((None, True), (grants("chat"), False), (grants("claw"), True)):
        v = preview(group, policy=policy, fresh=fresh)
        assert v.primary_model_id is None and not v.eligible_fallback_model_ids
        assert suggest_explicit_fallback(
            v, failure_code="upstream_timeout",
            attempted_model_ids=(A,), user_notice_possible=True,
        ) is None


def test_disabled_or_blocked_backup_never_selected():
    group = staged(prefs(backups=(B, C)))
    v = preview(group, policy=grants("chat", block=("chat", B)))
    assert v.primary_model_id == A
    assert v.eligible_fallback_model_ids == (C,)
    assert dict(v.model_reasons)[B] == "product_blocked"
    assert suggest_explicit_fallback(v, failure_code="upstream_timeout",
                                      attempted_model_ids=(A,), user_notice_possible=True) == C


def test_primary_b14_offline_does_not_promote_backup():
    group = staged(prefs())
    offline = dict(CAT)
    offline[A] = CatalogModel(A, True, False, True, True, frozenset({"chat"}))
    v = preview(group, policy=grants("chat"), catalog=offline)
    assert v.primary_model_id is None
    assert dict(v.model_reasons)[A] == "b14_model_offline"


def test_fallback_only_on_explicit_enable_transient_error_and_notice():
    active = preview(staged(prefs()), policy=grants("chat"))
    inactive = preview(staged(prefs(enabled=False)), policy=grants("chat"))
    def pick(v, error, attempted=(A,), notice=True):
        return suggest_explicit_fallback(v, failure_code=error,
                                         attempted_model_ids=attempted,
                                         user_notice_possible=notice)
    assert pick(active, "upstream_timeout") == B
    assert pick(active, "upstream_server_error", (A, B)) == C
    assert pick(active, "upstream_timeout", (A, B, C)) is None
    assert pick(inactive, "upstream_timeout") is None
    assert pick(active, "upstream_timeout", notice=False) is None


@pytest.mark.parametrize("denial", [
    "model_profile_unassigned", "tier_unavailable", "provider_auth_error",
    "central_blocked", "product_blocked", "model_admin_forbidden",
    "permission_denied", "invalid_request", "quota_exceeded",
    "upstream_execution_failed", "malformed_upstream",
])
def test_never_fallback_on_denial_auth_policy_or_unknown_errors(denial):
    v = preview(staged(prefs()), policy=grants("chat"))
    assert suggest_explicit_fallback(v, failure_code=denial,
                                     attempted_model_ids=(A,),
                                     user_notice_possible=True) is None


def test_cannot_skip_primary_or_replay_model_chain():
    v = preview(staged(prefs()), policy=grants("chat"))
    for attempts in ((B,), (A, C), (A, A), (A, B, B), (), (A, C, B)):
        assert suggest_explicit_fallback(
            v, failure_code="upstream_timeout", attempted_model_ids=attempts,
            user_notice_possible=True,
        ) is None


def test_group_duplicate_unknown_auto_retired_and_hold_models_denied():
    code("duplicate_tier_group_model", lambda: TierModelGroup("PLUS", (A, A)))
    code("invalid_tier_group_model", lambda: TierModelGroup("PLUS", (PLUS_HOLD_MODEL_ID,)))
    code("invalid_tier_group_model", lambda: TierModelGroup("PLUS", ("b14/auto",)))
    code("invalid_tier_group_model", lambda: TierModelGroup("PLUS", ("kilo/tencent-hy3-free",)))
    code("product_route_outside_site_tier_group", lambda: staged(prefs(primary="other/not-member", backups=())))
    code("invalid_product_group_fallbacks", lambda: prefs(backups=(B, B)))
    code("invalid_product_group_target", lambda: ProductModelPreference("central", "PLUS", A))


def test_duplicate_routes_and_out_of_scope_site_are_denied():
    code("duplicate_product_group_route", lambda: staged(prefs(), prefs()))
    code("invalid_product_group_target", lambda: ProductModelPreference("b14-router", "PLUS", A))
    code("invalid_tier_group_workspace", lambda: preview_product_group(
        staged(prefs()), product="chat", tier="PLUS", workspace_id="other",
        policy=grants("chat"), catalog=CAT,
        capability_ready={m: True for m in CAT}, trusted_policy_fresh=True,
    ))


def test_unassigned_product_not_assumed_from_same_tier_global_group():
    v = preview(staged(prefs("chat")), product="b66", policy=grants("chat", "b66"))
    assert v.primary_model_id is None
    assert v.eligible_fallback_model_ids == ()
    assert v.model_reasons == ()


def test_central_max_and_claw_pro_can_use_same_exact_model_without_mutation():
    # User requirement: global MAX suggestion does not force Claw's tier.
    from padiem_control_plane.tier_model_groups import SiteTierModelGroup
    site_groups = (
        SiteTierModelGroup("chat", "MAX", (A, B)),
        SiteTierModelGroup("claw", "PRO", (A, C)),
        SiteTierModelGroup("b66", "PLUS", (A, B)),
    )
    preferences = (
        ProductModelPreference("chat", "MAX", A, (B,), False),
        ProductModelPreference("claw", "PRO", A, (C,), False),
        ProductModelPreference("b66", "PLUS", A, (B,), False),
    )
    # A is recommended under global MAX, but chosen independently under
    # Claw PRO and B66 PLUS after separate central AND product grants.
    conf = StagedTierGroupSnapshot(
        "padiem-global", 3, (TierModelGroup("MAX", (A,)),),
        preferences, site_groups,
    )
    rules = tuple(
        ModelChange(product, tier, A, "allow")
        for product, tier in (
            ("central", "MAX"), ("chat", "MAX"),
            ("central", "PRO"), ("claw", "PRO"),
            ("central", "PLUS"), ("b66", "PLUS"),
        )
    )
    policy = ModelPolicySnapshot("padiem-global", 4, rules)
    results = {
        product: preview_product_group(
            conf, workspace_id="padiem-global", product=product, tier=tier,
            policy=policy, catalog=CAT,
            capability_ready={A: True}, trusted_policy_fresh=True,
        )
        for product, tier in (("chat", "MAX"), ("claw", "PRO"), ("b66", "PLUS"))
    }
    assert all(result.primary_model_id == A for result in results.values())
    assert all(result.dispatch_authorized is False for result in results.values())
    # Reclassifying or removing central recommendations has no side effects on
    # existing per-site rosters or primary/fallback selections.
    revised = StagedTierGroupSnapshot(
        conf.workspace_id, conf.revision + 1,
        (TierModelGroup("MAX", (C,)),), conf.preferences, conf.site_groups,
    )
    assert revised.site_groups == conf.site_groups
    assert revised.preferences == conf.preferences
    for product, tier in (("chat", "MAX"), ("claw", "PRO"), ("b66", "PLUS")):
        after = preview_product_group(
            revised, workspace_id="padiem-global", product=product, tier=tier,
            policy=policy, catalog=CAT, capability_ready={A: True},
            trusted_policy_fresh=True,
        )
        assert after.primary_model_id == results[product].primary_model_id


def test_site_assignment_must_be_in_own_site_group_not_global_suggestion():
    # Global Plus recommendation alone grants nothing to a missing site group.
    code("product_route_outside_site_tier_group", lambda: StagedTierGroupSnapshot(
        "padiem-global", 0, (TierModelGroup("PLUS", (A, B)),),
        (ProductModelPreference("claw", "PLUS", A),), (),
    ))
    code("product_route_outside_site_tier_group", lambda: StagedTierGroupSnapshot(
        "padiem-global", 0, (TierModelGroup("PLUS", (A, B)),),
        (ProductModelPreference("claw", "PLUS", A),),
        (SiteTierModelGroup("claw", "PLUS", (B,)),),
    ))
    code("duplicate_site_tier_group", lambda: StagedTierGroupSnapshot(
        "padiem-global", 0, (), (),
        (SiteTierModelGroup("chat", "MAX", (A,)),
         SiteTierModelGroup("chat", "MAX", (B,))),
    ))
    code("invalid_site_tier_group_target", lambda: SiteTierModelGroup("central", "PRO", (A,)))
    code("duplicate_site_tier_group_model", lambda: SiteTierModelGroup("claw", "PRO", (A, A)))


def test_site_tier_reclassification_isolated_from_other_products():
    groups = (
        SiteTierModelGroup("chat", "MAX", (A,)),
        SiteTierModelGroup("claw", "PRO", (A,)),
    )
    original = StagedTierGroupSnapshot(
        "padiem-global", 0, (TierModelGroup("MAX", (A,)),),
        (ProductModelPreference("chat", "MAX", A),
         ProductModelPreference("claw", "PRO", A)), groups,
    )
    updated = StagedTierGroupSnapshot(
        original.workspace_id, 1, original.groups,
        original.preferences, (
            SiteTierModelGroup("chat", "MAX", (A, B)),
            original.site_groups[1],
        ),
    )
    assert updated.site_groups[1] == original.site_groups[1]
    assert updated.preferences[1] == original.preferences[1]
    assert updated.groups == original.groups
