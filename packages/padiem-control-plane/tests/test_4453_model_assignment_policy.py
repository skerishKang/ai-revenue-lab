"""#4453 contracts: deny by default, exact IDs, scoped CAS/audit/rollback."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.model_assignment_policy import (
    CatalogModel, ModelAssignmentService, ModelChange, ModelPolicySnapshot,
    VerifiedModelAdminGrant, effective_model,
)
from padiem_control_plane.model_assignment_sqlite_reference import SQLiteModelPolicyStore

NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
KEY = b"a" * 32
A = "provider/model-a"
B = "provider/model-b"
CATALOG = {
    A: CatalogModel(A, True, True, True, True, frozenset({"chat", "coding"})),
    B: CatalogModel(B, True, True, True, True, frozenset({"chat"})),
}
OFFLINE = CatalogModel(A, True, False, True, True, frozenset({"chat"}))


def admin(*, product=None, ws="ws-1", actor="usr-1", permissions=None):
    return VerifiedModelAdminGrant(
        subject_id=actor, workspace_id=ws, product=product,
        authority_ref="cp-global-identity-v1",
        permissions=frozenset(permissions or {"preview", "apply", "rollback"}),
        issued_at=NOW-timedelta(minutes=1), expires_at=NOW+timedelta(hours=1),
    )


def change(product, tier="PLUS", model=A, action="allow"):
    return ModelChange(product, tier, model, action)


def service(tmp_path=None, *, on=True):
    store = SQLiteModelPolicyStore(str(tmp_path / "policies.sqlite") if tmp_path else ":memory:")
    return ModelAssignmentService(store=store, signing_key=KEY, enabled=on), store


def preview(svc, *changes, grant=None, now=NOW, ws="ws-1", catalog=CATALOG):
    return svc.preview(grant=grant or admin(ws=ws), workspace_id=ws,
                       changes=tuple(changes), catalog=catalog, now=now)


def apply(svc, receipt, *, grant=None, now=NOW, ws="ws-1", catalog=CATALOG):
    return svc.apply(grant=grant or admin(ws=ws), workspace_id=ws,
                     receipt=receipt, catalog=catalog, now=now)


def assert_error(code, callback):
    with pytest.raises(ControlPlaneContractError) as exc:
        callback()
    assert exc.value.code == code


def test_defaults_off_and_missing_policy_fail_closed():
    svc, store = service()
    assert store.snapshot("ws-1").revision == 0
    assert not effective_model(None, workspace_id="ws-1", product="chat",
                               tier="PLUS", model=CATALOG[A], model_id=A,
                               capability_ready=True, trusted_policy_fresh=True).allowed
    state = effective_model(store.snapshot("ws-1"), workspace_id="ws-1", product="chat",
                            tier="PLUS", model=CATALOG[A], model_id=A,
                            capability_ready=True, trusted_policy_fresh=True)
    assert state.reason == "central_unassigned"
    assert state.revision == 0
    store.close()


def test_preview_never_mutates_or_authorizes_dispatch():
    svc, store = service()
    receipt = preview(svc, change("central"), change("chat"))
    assert receipt["applied"] is False
    assert receipt["persisted"] is False
    assert receipt["dispatch_authorized"] is False
    assert receipt["expected_revision"] == 0
    assert len(receipt["diff"]) == 2
    assert store.snapshot("ws-1").revision == 0
    assert not store.safe_audit("ws-1")
    store.close()


def test_central_and_product_intersection_then_global_off_priority():
    svc, store = service()
    first = preview(svc, change("central"), change("chat"))
    snapshot = apply(svc, first["confirmation_receipt"])
    yes = effective_model(snapshot, workspace_id="ws-1", product="chat",
                          tier="PLUS", model=CATALOG[A], model_id=A,
                          capability_ready=True, trusted_policy_fresh=True)
    assert yes.allowed and yes.reason == "allowed"
    other = effective_model(snapshot, workspace_id="ws-1", product="claw",
                            tier="PLUS", model=CATALOG[A], model_id=A,
                            capability_ready=True, trusted_policy_fresh=True)
    assert not other.allowed and other.reason == "product_unassigned"
    changed = preview(svc, change("central", action="block"))
    blocked = apply(svc, changed["confirmation_receipt"])
    decision = effective_model(blocked, workspace_id="ws-1", product="chat",
                               tier="PLUS", model=CATALOG[A], model_id=A,
                               capability_ready=True, trusted_policy_fresh=True)
    assert decision.reason == "central_blocked"
    assert decision.product_action == "allow"
    assert len(store.safe_audit("ws-1")) == 2
    store.close()


def test_free_plus_pro_max_multiple_models_not_one_model_per_tier():
    svc, store = service()
    c = [change("central", tier, m) for tier in ("FREE", "PLUS", "PRO", "MAX") for m in (A, B)]
    c += [change("b66", tier, m) for tier in ("FREE", "PLUS", "PRO", "MAX") for m in (A, B)]
    s = apply(svc, preview(svc, *c)["confirmation_receipt"])
    assert len(s.rules) == 16
    for tier in ("FREE", "PLUS", "PRO", "MAX"):
        for m in (A, B):
            result = effective_model(s, workspace_id="ws-1", product="b66",
                                     tier=tier, model=CATALOG[m], model_id=m,
                                     capability_ready=True, trusted_policy_fresh=True)
            assert result.allowed
    store.close()


def test_product_admin_can_only_change_single_product_never_global():
    svc, store = service()
    g = admin(product="claw")
    one = preview(svc, change("claw"), grant=g)
    s = apply(svc, one["confirmation_receipt"], grant=g)
    assert s.lookup("claw", "PLUS", A) == "allow"
    assert s.lookup("central", "PLUS", A) == "inherit"
    assert_error("model_admin_scope_forbidden",
                 lambda: preview(svc, change("central"), grant=g))
    assert_error("model_admin_scope_forbidden",
                 lambda: preview(svc, change("claw"), change("chat"), grant=g))
    assert_error("model_admin_scope_forbidden",
                 lambda: svc.preview_rollback(grant=g, workspace_id="ws-1", target_revision=0, now=NOW))
    store.close()


def test_missing_permissions_expired_and_wrong_workspace_rejected():
    svc, store = service()
    g = admin(permissions={"preview"})
    p = preview(svc, change("chat"), grant=g)
    assert_error("model_admin_forbidden", lambda: apply(svc, p["confirmation_receipt"], grant=g))
    assert_error("model_admin_forbidden", lambda: preview(svc, change("chat"), grant=admin(ws="ws-2")))
    assert_error("model_admin_grant_expired",
                 lambda: preview(svc, change("chat"), now=NOW+timedelta(days=1)))
    store.close()


def test_unknown_disabled_and_duplicate_change_rejected_atomically():
    svc, store = service()
    assert_error("model_policy_unknown_model",
                 lambda: preview(svc, change("central", model="missing/model")))
    assert_error("model_policy_offline_model",
                 lambda: preview(svc, change("central"), catalog={A: OFFLINE}))
    assert_error("duplicate_model_policy_change",
                 lambda: preview(svc, change("chat"), change("chat")))
    assert_error("invalid_model_policy_batch",
                 lambda: preview(svc, *[change(p, t, m) for p in sorted({"central", "chat", "claw", "b66", "b14-router"}) for t in sorted({"FREE", "PLUS", "PRO", "MAX"}) for m in (A, B)][:21]))
    assert store.snapshot("ws-1").revision == 0
    store.close()


def test_offline_model_cannot_dispatch_even_if_saved_then_disabled():
    svc, store = service()
    p = preview(svc, change("central"), change("chat"))
    s = apply(svc, p["confirmation_receipt"])
    result = effective_model(s, workspace_id="ws-1", product="chat", tier="PLUS",
                             model=OFFLINE, model_id=A, capability_ready=True,
                             trusted_policy_fresh=True)
    assert not result.allowed and result.reason == "b14_model_offline"
    assert_error("model_policy_offline_model",
                 lambda: apply(svc, preview(svc, change("claw"))["confirmation_receipt"],
                               catalog={A: OFFLINE}))
    store.close()


def test_unknown_forged_model_b14_auto_and_disabled_capability():
    svc, store = service()
    assert_error("invalid_model_policy_model", lambda: change("chat", model="b14/auto"))
    p = preview(svc, change("central"), change("chat"))
    s = apply(svc, p["confirmation_receipt"])
    assert effective_model(s, workspace_id="ws-1", product="chat", tier="PLUS",
                           model=CATALOG[A], model_id=A, capability_ready=False,
                           trusted_policy_fresh=True).reason == "product_capability_blocked"
    assert effective_model(s, workspace_id="ws-1", product="chat", tier="PLUS",
                           model=CATALOG[A], model_id=A, capability_ready=True,
                           trusted_policy_fresh=False).reason == "policy_unavailable"
    assert effective_model(s, workspace_id="ws-2", product="chat", tier="PLUS",
                           model=CATALOG[A], model_id=A, capability_ready=True,
                           trusted_policy_fresh=True).reason == "policy_unavailable"
    store.close()


def test_stale_revision_and_receipt_replay_fail_closed():
    svc, store = service()
    p1 = preview(svc, change("central"))
    p2 = preview(svc, change("chat"))
    apply(svc, p1["confirmation_receipt"])
    assert_error("model_policy_revision_conflict", lambda: apply(svc, p2["confirmation_receipt"]))
    assert_error("model_policy_receipt_replayed", lambda: apply(svc, p1["confirmation_receipt"]))
    assert store.snapshot("ws-1").revision == 1
    store.close()


def test_receipt_expiry_forgery_actor_and_cross_workspace():
    svc, store = service()
    token = preview(svc, change("central"))["confirmation_receipt"]
    assert_error("model_policy_receipt_expired", lambda: apply(svc, token, now=NOW+timedelta(minutes=6)))
    assert_error("model_policy_receipt_scope_mismatch",
                 lambda: apply(svc, token, grant=admin(actor="usr-other")))
    assert_error("model_policy_receipt_scope_mismatch",
                 lambda: apply(svc, token, grant=admin(ws="ws-2"), ws="ws-2"))
    assert_error("model_policy_invalid_receipt", lambda: apply(svc, token[:-1] + ("1" if token[-1] == "0" else "0")))
    assert store.snapshot("ws-1").revision == 0
    store.close()


def test_inherit_removes_only_exact_target_and_audit_is_content_blind():
    svc, store = service()
    original = preview(svc, change("central"), change("chat"), change("claw", model=B))
    apply(svc, original["confirmation_receipt"])
    p = preview(svc, change("chat", action="inherit"))
    s = apply(svc, p["confirmation_receipt"])
    assert s.lookup("chat", "PLUS", A) == "inherit"
    assert s.lookup("central", "PLUS", A) == "allow"
    assert s.lookup("claw", "PLUS", B) == "allow"
    audit = json.dumps(store.safe_audit("ws-1"))
    assert "Authorization" not in audit and "Bearer" not in audit
    assert "prompt" not in audit and "api_key" not in audit
    store.close()


def test_atomic_durable_reopen_and_tenant_isolation(tmp_path):
    svc, store = service(tmp_path)
    p = preview(svc, change("central"), change("b66"))
    apply(svc, p["confirmation_receipt"])
    store.close()
    store2 = SQLiteModelPolicyStore(str(tmp_path / "policies.sqlite"))
    assert store2.snapshot("ws-1").revision == 1
    assert store2.snapshot("ws-2").revision == 0
    assert len(store2.safe_audit("ws-1")) == 1
    assert store2.safe_audit("ws-2") == []
    store2.close()


def test_explicit_rollback_requires_grant_and_cas():
    svc, store = service()
    p1 = preview(svc, change("central"), change("chat"))
    apply(svc, p1["confirmation_receipt"])
    p2 = preview(svc, change("central", action="block"))
    apply(svc, p2["confirmation_receipt"])
    rollback = svc.preview_rollback(grant=admin(), workspace_id="ws-1",
                                    target_revision=1, now=NOW)
    restored = apply(svc, rollback["confirmation_receipt"])
    assert restored.revision == 3
    assert restored.lookup("central", "PLUS", A) == "allow"
    assert store.safe_audit("ws-1")[-1]["operation"] == "rollback"
    assert_error("model_policy_receipt_replayed", lambda: apply(svc, rollback["confirmation_receipt"]))
    store.close()


def test_disabled_service_fails_closed_without_production_attachment():
    svc, store = service(on=False)
    assert_error("model_policy_apply_not_configured", lambda: preview(svc, change("chat")))
    assert store.snapshot("ws-1").revision == 0
    store.close()


def test_malformed_receipts_and_model_changes_rejected():
    svc, store = service()
    for invalid in ("", "a.b", "aaa", None, "x"*13000):
        assert_error("model_policy_invalid_receipt", lambda t=invalid: apply(svc, t))
    assert_error("invalid_model_policy_change", lambda: ModelChange("invalid", "PLUS", A, "allow"))
    assert_error("invalid_model_policy_change", lambda: ModelChange("chat", "INVALID", A, "allow"))
    assert_error("invalid_model_policy_change", lambda: ModelChange("chat", "PLUS", A, "auto"))
    assert store.snapshot("ws-1").revision == 0
    store.close()


def test_owner_excluded_catalog_cannot_be_granted_or_dispatched():
    svc, store = service()
    excluded = CatalogModel(A, True, True, True, False, frozenset({"chat"}))
    assert_error("model_policy_offline_model",
                 lambda: preview(svc, change("central"), catalog={A: excluded}))
    initial = preview(svc, change("central"), change("chat"))
    state = apply(svc, initial["confirmation_receipt"])
    result = effective_model(state, workspace_id="ws-1", product="chat",
                             tier="PLUS", model=excluded, model_id=A,
                             capability_ready=True, trusted_policy_fresh=True)
    assert not result.allowed and result.reason == "b14_owner_not_allowed"
    store.close()


def test_malformed_batch_rejected_before_authorization_lookup():
    svc, store = service()
    assert_error("invalid_model_policy_batch",
                 lambda: svc.preview(grant=admin(), workspace_id="ws-1",
                                     changes=({"product": "central"},),
                                     catalog=CATALOG, now=NOW))
    assert_error("invalid_model_policy_batch",
                 lambda: svc.preview(grant=admin(), workspace_id="ws-1",
                                     changes=[], catalog=CATALOG, now=NOW))
    assert store.snapshot("ws-1").revision == 0
    store.close()


def test_unconfigured_signing_key_denied():
    s = ModelAssignmentService(store=SQLiteModelPolicyStore(), signing_key=None, enabled=True)
    assert_error("model_policy_apply_not_configured",
                 lambda: preview(s, change("chat")))
