"""Pure contract tests for #2107 Padiem routing-profile Admin ACT-1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import FrozenInstanceError

import pytest

from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.padiem_routing_profile_admin import (
    PadiemRoutingProfileAuditPayload,
    PadiemRoutingProfileCatalogRoute,
    PadiemRoutingProfileCredentialState,
    PadiemRoutingProfileDiff,
    PadiemRoutingProfileOperatorAction,
    PadiemRoutingProfileOperatorGrant,
    PadiemRoutingProfileRevision,
    PadiemRoutingProfileRollbackAnchor,
    PadiemRoutingProfileRouteState,
    PadiemRoutingProfileStatus,
    PadiemRoutingProfileStagedChange,
    PadiemRoutingProfileTierChange,
    PadiemRoutingProfileTierSelection,
    apply_padiem_routing_profile_stage,
    build_padiem_routing_profile_diff,
    rollback_padiem_routing_profile,
    validate_padiem_routing_profile_stage,
)
from padiem_control_plane.product_tier_routes import (
    MAX_HOLD_MODEL_ID,
    PRODUCT_TIER_POLICY_VERSION,
    ProductTierLabel,
)


NOW = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="operator-1")


def selection(tier: ProductTierLabel, *, route_id: str | None = None, model_id: str | None = None, state=None, credential=None, reason=None):
    if tier is ProductTierLabel.MAX:
        return PadiemRoutingProfileTierSelection(
            tier=tier,
            route_id=route_id,
            provider_id="qwen" if state is PadiemRoutingProfileRouteState.REGISTERED else None,
            model_id=model_id if model_id is not None else MAX_HOLD_MODEL_ID,
            route_state=state or PadiemRoutingProfileRouteState.HOLD,
            credential_state=credential or PadiemRoutingProfileCredentialState.NOT_REQUIRED,
            reason_code=reason or "MAX_HOLD",
            catalog_route_ref="b14:catalog:v1" if state is PadiemRoutingProfileRouteState.REGISTERED else None,
        )
    provider = "kilo"
    model = model_id or ("kilo/poolside-laguna-s-2.1-free" if tier is ProductTierLabel.PLUS else "kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
    return PadiemRoutingProfileTierSelection(
        tier=tier,
        route_id=route_id or ("plus.kilo-laguna-s-2.1-free.v1" if tier is ProductTierLabel.PLUS else "pro.kilo-nemotron-3-ultra-free.v1"),
        provider_id=provider,
        model_id=model,
        route_state=state or PadiemRoutingProfileRouteState.REGISTERED,
        credential_state=credential or PadiemRoutingProfileCredentialState.NOT_REQUIRED,
        reason_code=reason,
        catalog_route_ref="b14:catalog:v1" if (state or PadiemRoutingProfileRouteState.REGISTERED) is PadiemRoutingProfileRouteState.REGISTERED else None,
    )


def revision(number: int = 1, *, selections=None) -> PadiemRoutingProfileRevision:
    return PadiemRoutingProfileRevision(
        profile_id="padiem",
        revision=number,
        policy_version=PRODUCT_TIER_POLICY_VERSION,
        selections=selections or tuple(selection(tier) for tier in ProductTierLabel),
        created_at=NOW,
    )


def grant(*actions: PadiemRoutingProfileOperatorAction) -> PadiemRoutingProfileOperatorGrant:
    return PadiemRoutingProfileOperatorGrant(
        grant_ref="grant-1",
        operator_subject=SUBJECT,
        authority_ref="control-plane:operator",
        allowed_actions=actions or (
            PadiemRoutingProfileOperatorAction.STAGE,
            PadiemRoutingProfileOperatorAction.APPLY,
            PadiemRoutingProfileOperatorAction.ROLLBACK,
        ),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def staged(*, base: int = 1, selections=None) -> PadiemRoutingProfileStagedChange:
    before = revision(base)
    after_selections = selections or tuple(selection(tier) for tier in ProductTierLabel)
    after = revision(base + 1, selections=after_selections)
    return PadiemRoutingProfileStagedChange(
        stage_ref="stage-1",
        profile_id="padiem",
        base_revision=base,
        proposed_revision=base + 1,
        selections=after_selections,
        diff=build_padiem_routing_profile_diff(before, after),
        operator_grant=grant(),
        staged_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def test_value_objects_are_immutable_and_have_safe_projections() -> None:
    value = revision()
    with pytest.raises(FrozenInstanceError):
        value.revision = 2  # type: ignore[misc]
    public = value.safe_dict()
    assert public["profile_id"] == "padiem"
    assert "credential_value" not in str(public).lower()
    assert "secret_value" not in str(public).lower()
    assert public["selections"][2]["route_state"] == "hold"  # type: ignore[index]


def test_registered_selection_requires_trusted_catalog_reference() -> None:
    with pytest.raises(ValueError, match="trusted catalog reference"):
        PadiemRoutingProfileTierSelection(
            tier=ProductTierLabel.PLUS,
            route_id="plus.route.v1",
            provider_id="kilo",
            model_id="kilo/model",
            route_state=PadiemRoutingProfileRouteState.REGISTERED,
            credential_state=PadiemRoutingProfileCredentialState.NOT_REQUIRED,
        )


def test_selection_can_only_be_derived_from_safe_catalog_projection() -> None:
    route = PadiemRoutingProfileCatalogRoute(
        catalog_ref="b14:catalog:v1",
        route_id="plus.route.v1",
        provider_id="kilo",
        model_id="kilo/model",
        state=PadiemRoutingProfileRouteState.REGISTERED,
        credential_state=PadiemRoutingProfileCredentialState.NOT_REQUIRED,
    )
    selected = PadiemRoutingProfileTierSelection.from_catalog(
        tier=ProductTierLabel.PLUS,
        route=route,
    )
    assert selected.catalog_route_ref == route.catalog_ref


def test_exact_revision_conflict_fails_closed_and_never_auto_merges() -> None:
    with pytest.raises(ValueError) as error:
        validate_padiem_routing_profile_stage(staged(), current_revision=2, now=NOW)
    assert getattr(error.value, "code") == "padiem_profile_revision_conflict"
    with pytest.raises(ValueError):
        apply_padiem_routing_profile_stage(
            staged(), current_revision=2, now=NOW,
            apply_operator_grant=grant(PadiemRoutingProfileOperatorAction.APPLY),
            receipt_ref="receipt-1", audit_ref="audit-1", confirmation_ref="confirm-1", rollback_anchor_ref="anchor-1",
        )


@pytest.mark.parametrize(
    ("state", "code"),
    [
        (PadiemRoutingProfileRouteState.UNREGISTERED, "padiem_profile_route_unregistered"),
        (PadiemRoutingProfileRouteState.RETIRED, "padiem_profile_route_retired"),
        (PadiemRoutingProfileRouteState.DISABLED, "padiem_profile_route_disabled"),
    ],
)
def test_unavailable_route_states_are_rejected(state, code) -> None:
    proposed = tuple(
        selection(tier, state=state, reason="ROUTE_BLOCKED") if tier is ProductTierLabel.PRO else selection(tier)
        for tier in ProductTierLabel
    )
    with pytest.raises(ValueError) as error:
        validate_padiem_routing_profile_stage(staged(selections=proposed), current_revision=1, now=NOW)
    assert getattr(error.value, "code") == code


def test_hold_route_and_max_hold_are_fail_closed() -> None:
    max_selection = selection(
        ProductTierLabel.MAX,
        route_id="max.explicit.v1",
        model_id="qwen/ready",
        state=PadiemRoutingProfileRouteState.REGISTERED,
    )
    with pytest.raises(ValueError):
        PadiemRoutingProfileRevision(
            profile_id="padiem", revision=1, policy_version=PRODUCT_TIER_POLICY_VERSION,
            selections=(selection(ProductTierLabel.PLUS), selection(ProductTierLabel.PRO), max_selection),
            created_at=NOW,
        )
    assert revision().selections[2].model_id == MAX_HOLD_MODEL_ID


def test_credential_not_ready_is_rejected_without_raw_credential_fields() -> None:
    proposed = tuple(
        selection(tier, credential=PadiemRoutingProfileCredentialState.NOT_READY, reason="CREDENTIAL_MISSING")
        if tier is ProductTierLabel.PRO else selection(tier)
        for tier in ProductTierLabel
    )
    with pytest.raises(ValueError) as error:
        validate_padiem_routing_profile_stage(staged(selections=proposed), current_revision=1, now=NOW)
    assert getattr(error.value, "code") == "padiem_profile_credential_not_ready"
    assert "secret_value" not in str(staged().safe_dict()).lower()


def test_operator_grant_has_no_tenant_or_entitlement_authority() -> None:
    fields = set(grant().__dataclass_fields__)
    assert "tenant_id" not in fields
    assert "entitlement_id" not in fields
    public = grant().safe_dict()
    assert public["tenant_authority"] is False
    assert public["entitlement_authority"] is False


def test_apply_is_a_pure_receipt_and_requires_exact_stage() -> None:
    receipt = apply_padiem_routing_profile_stage(
        staged(), current_revision=1, now=NOW,
        apply_operator_grant=grant(PadiemRoutingProfileOperatorAction.APPLY),
        receipt_ref="receipt-1", audit_ref="audit-1", confirmation_ref="confirm-1", rollback_anchor_ref="anchor-1",
    )
    assert receipt.status is PadiemRoutingProfileStatus.APPLIED
    assert receipt.applied_revision == 2
    assert receipt.rollback_anchor_ref == "anchor-1"


def test_apply_requires_apply_capability_separately_from_stage() -> None:
    staged_change = staged()
    with pytest.raises(ValueError) as error:
        apply_padiem_routing_profile_stage(
            staged_change, current_revision=1, now=NOW,
            apply_operator_grant=grant(PadiemRoutingProfileOperatorAction.STAGE),
            receipt_ref="receipt-1", audit_ref="audit-1", confirmation_ref="confirm-1", rollback_anchor_ref="anchor-1",
        )
    assert getattr(error.value, "code") == "padiem_profile_operator_not_authorized"


def test_rollback_creates_new_revision_and_retains_history_anchor() -> None:
    original = revision(1)
    changed = revision(2, selections=tuple(selection(tier) for tier in ProductTierLabel))
    anchor = PadiemRoutingProfileRollbackAnchor(
        anchor_ref="anchor-1", profile_id="padiem", source_revision=2, target_revision=1,
        target_selections=original.selections, created_at=NOW,
    )
    rolled = rollback_padiem_routing_profile(changed, anchor, grant(PadiemRoutingProfileOperatorAction.ROLLBACK), now=NOW)
    assert rolled.revision == 3
    assert rolled.selections == original.selections
    assert anchor.target_revision == 1
    assert anchor.safe_dict()["history_retained"] is True


def test_audit_payload_is_refs_status_and_reason_only() -> None:
    payload = PadiemRoutingProfileAuditPayload(
        event_ref="event-1", profile_id="padiem", status=PadiemRoutingProfileStatus.APPLIED,
        actor_ref="operator-1", revision=2, correlation_ref="corr-1", reason_code="PROFILE_APPLIED",
    ).safe_dict()
    assert set(payload) == {
        "event_ref", "profile_id", "status", "actor_ref", "revision", "correlation_ref",
        "reason_code",
    }
    assert "secret_value" not in str(payload).lower()
    assert "provider_payload" not in str(payload).lower()


def test_contract_module_is_network_and_provider_free() -> None:
    from pathlib import Path

    source = (Path(__file__).parents[1] / "padiem_control_plane" / "padiem_routing_profile_admin.py").read_text()
    assert "httpx" not in source
    assert "requests" not in source
    assert "socket" not in source
    assert "provider_call" not in source
    assert "os.environ" not in source
