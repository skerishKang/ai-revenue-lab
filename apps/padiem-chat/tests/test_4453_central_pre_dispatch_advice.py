"""#4453: independent pre-dispatch advice; never authorizes model transport."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.central_model_pre_dispatch_advice import (
    GLOBAL_WORKSPACE, PreDispatchPolicyDecision, VerifiedProductModelSelection,
    inspect_pre_dispatch_policy,
)
from padiem_control_plane.model_assignment_policy import ModelChange, ModelPolicySnapshot

MODEL = "test-provider/model-a"
OTHER = "test-provider/model-b"
USER = "usr_" + "a" * 32


class CanonicalPolicy:
    def __init__(self, rules=None, *, revision=1, failure=False):
        self.rules = tuple(rules if rules is not None else [
            ModelChange("central", "PRO", MODEL, "allow"),
            ModelChange("chat", "PRO", MODEL, "allow"),
        ])
        self.revision = revision
        self.failure = failure
        self.calls = []

    async def snapshot(self, workspace_id):
        self.calls.append(workspace_id)
        if self.failure:
            raise RuntimeError("D1 offline")
        return ModelPolicySnapshot(workspace_id, self.revision, self.rules)


class B14Catalog:
    def __init__(self, *, enabled=True, excluded=False, selectable=True, broken=False):
        self.enabled = enabled
        self.excluded = excluded
        self.selectable = selectable
        self.broken = broken

    async def list_registered_models(self):
        if self.broken:
            return [{"model_id": MODEL, "owner_excluded": False}]
        return [
            {"model_id": MODEL, "b14_enabled": self.enabled,
             "owner_excluded": self.excluded, "capabilities": ["chat"]},
        ]

    async def list_selectable_models(self):
        return [{"model_id": MODEL, "name": "Test"}] if self.selectable else []


def selection(*, product="chat", tier="PRO", model=MODEL):
    return VerifiedProductModelSelection(
        canonical_user_id=USER, workspace_id=GLOBAL_WORKSPACE,
        product_id=product, tier=tier, exact_model_id=model,
        authority_ref="canonical-product-session",
    )


def run(*, selection_value=None, policy=None, catalog=None, capability=True):
    return asyncio.run(inspect_pre_dispatch_policy(
        selection=selection_value or selection(),
        store=policy if policy is not None else CanonicalPolicy(),
        b14_catalog_source=catalog if catalog is not None else B14Catalog(),
        product_capability_verified=capability,
    ))


def test_explicit_exact_model_allow_is_advice_not_provider_dispatch():
    result = run()
    assert result.allowed is True and result.reason == "allowed"
    assert result.revision == 1
    assert result.global_action == result.product_action == "allow"
    assert result.model_id == MODEL and result.product_id == "chat" and result.tier == "PRO"
    assert result.advisory_only and result.dispatch_authorized is False


def test_central_off_outranks_product_allow():
    policy = CanonicalPolicy([
        ModelChange("central", "PRO", MODEL, "block"),
        ModelChange("chat", "PRO", MODEL, "allow"),
    ])
    decision = run(policy=policy)
    assert not decision.allowed and decision.reason == "central_blocked"
    assert decision.product_action == "allow" and decision.global_action == "block"


def test_product_block_and_missing_tier_deny():
    policy = CanonicalPolicy([
        ModelChange("central", "PRO", MODEL, "allow"),
        ModelChange("chat", "PRO", MODEL, "block"),
    ])
    assert run(policy=policy).reason == "product_blocked"
    assert run(selection_value=selection(tier="MAX")).reason == "central_unassigned"
    assert run(selection_value=selection(product="b66")).reason == "product_unassigned"


@pytest.mark.parametrize("catalog, reason", [
    (B14Catalog(enabled=False, selectable=False), "b14_model_offline"),
    (B14Catalog(excluded=True, selectable=False), "b14_owner_not_allowed"),
    (B14Catalog(broken=True), "b14_catalog_invalid"),
    (B14Catalog(enabled=False, selectable=True), "b14_catalog_mismatch"),
])
def test_b14_readiness_and_integrity_fail_closed(catalog, reason):
    result = run(catalog=catalog)
    assert not result.allowed and result.reason == reason
    assert result.dispatch_authorized is False


def test_unknown_exact_model_cannot_fallback():
    result = run(selection_value=selection(model=OTHER))
    assert result.reason == "b14_model_unknown"
    assert result.model_id == OTHER and not result.allowed


def test_missing_capability_fails_without_d1_or_b14_lookup():
    policy = CanonicalPolicy()
    result = run(policy=policy, capability=False)
    assert result.reason == "product_capability_unverified"
    assert policy.calls == []


def test_d1_unavailable_or_source_missing_deny():
    assert run(policy=CanonicalPolicy(failure=True)).reason == "model_policy_evaluation_unavailable"
    result = asyncio.run(inspect_pre_dispatch_policy(
        selection=selection(), store=None, b14_catalog_source=None,
        product_capability_verified=True,
    ))
    assert result.reason == "model_policy_source_unavailable"
    assert not result.allowed


@pytest.mark.parametrize("bad", [
    {"canonical_user_id": "browser supplied"},
    {"workspace_id": "another-workspace"},
    {"product_id": "central"},
    {"tier": "owner"},
    {"exact_model_id": "b14/auto"},
    {"authority_ref": ""},
])
def test_invalid_or_untrusted_context_cannot_be_constructed(bad):
    values = dict(
        canonical_user_id=USER, workspace_id=GLOBAL_WORKSPACE,
        product_id="chat", tier="PRO", exact_model_id=MODEL,
        authority_ref="canonical-product-session",
    )
    values.update(bad)
    with pytest.raises(ValueError):
        VerifiedProductModelSelection(**values)


def test_non_host_admission_throws_and_never_defaults():
    with pytest.raises(ValueError):
        asyncio.run(inspect_pre_dispatch_policy(
            selection=object(), store=CanonicalPolicy(), b14_catalog_source=B14Catalog(),
            product_capability_verified=True,
        ))


def test_snapshot_evaluation_current_revision_every_call():
    source = CanonicalPolicy()
    assert run(policy=source).revision == 1
    source.revision = 2
    source.rules = (
        ModelChange("central", "PRO", MODEL, "block"),
        ModelChange("chat", "PRO", MODEL, "allow"),
    )
    result = run(policy=source)
    assert result.revision == 2 and result.reason == "central_blocked"
    assert source.calls == [GLOBAL_WORKSPACE, GLOBAL_WORKSPACE]
