"""BookAI withdrawal uses the actual reviewed authority permission boundary."""
from __future__ import annotations

import types
from datetime import timedelta

import pytest

from test_bookai_identity_registration import (
    B62, BOOKAI, DEPLOYED_PRODUCTS, MISMATCH, NOW, USER, _AlarmStorage, _KEY,
    _worker_mod, authority, link, run,
)
from identity_authority_durable import CloudflareCanonicalIdentityAuthorityStore
from padiem_control_plane.contracts import SubjectType

OPERATION = "00000000-0000-4000-8000-000000007547"


def payload(subject, *, product=BOOKAI, user=USER, validate_only=False, operation=None):
    value = {"product_id": product, "product_user_id": user,
             "canonical_subject_id": subject, "account_deletion_operation_id": operation}
    if validate_only:
        value["validate_only"] = True
    return value


def snapshot(do):
    return tuple(do._storage.connection.iterdump())


def test_bookai_last_link_requires_preparation_then_removes_and_replays():
    do = authority()
    subject = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    before = snapshot(do)
    assert run(do.remove_product_link(payload(subject, validate_only=True))) == {"ok": True, "removable": True}
    assert snapshot(do) == before
    refused = run(do.remove_product_link(payload(subject)))
    assert refused["error"]["code"] == "account_deletion_unprepared"
    assert snapshot(do) == before
    result = run(do.remove_product_link(payload(subject, operation=OPERATION)))
    assert result == {"ok": True, "removed": True, "remaining_links": 0,
                      "common_account_deleted": True, "revoked_sessions": 0, "already_deleted": False}
    repeated = run(do.remove_product_link(payload(subject, operation=OPERATION)))
    assert repeated == {**result, "removed": False, "already_deleted": True}


@pytest.mark.parametrize("first", [BOOKAI, B62])
def test_both_first_product_orders_remove_bookai_without_revoking_chat(first):
    do = authority()
    subject = link(do, product=first)["link"]["canonical_subject_id"]
    link(do, product=B62 if first == BOOKAI else BOOKAI, expected=subject)
    session = run(do.establish_auth_session({
        "product_id": B62, "subject": {"subject_type": SubjectType.USER.value, "subject_id": subject},
        "authenticated_at": NOW.isoformat(), "not_after": (NOW + timedelta(hours=1)).isoformat(),
    }))
    assert session["ok"] is True
    result = run(do.remove_product_link(payload(subject)))
    assert result["ok"] is True and result["remaining_links"] == 1
    assert result["common_account_deleted"] is False and result["revoked_sessions"] == 0
    assert run(do.resolve_current_auth_session({"product_id": B62, "product_user_id": USER}))["ok"] is True
    final = run(do.remove_product_link(payload(subject, product=B62, operation=OPERATION)))
    assert final["ok"] is True and final["common_account_deleted"] is True


def test_validation_does_not_change_links_sessions_audits_or_alarms():
    do = authority()
    subject = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    link(do, product=B62, expected=subject)
    assert run(do.establish_auth_session({
        "product_id": B62, "subject": {"subject_type": SubjectType.USER.value, "subject_id": subject},
        "authenticated_at": NOW.isoformat(), "not_after": (NOW + timedelta(hours=1)).isoformat(),
    }))["ok"] is True
    do._storage.connection.execute(
        "INSERT INTO canonical_account_deletion_audit VALUES (?,?)", ("a" * 64, "2000-01-01T00:00:00+00:00"),
    )
    async def no_alarm():
        raise AssertionError("validation must not schedule an alarm")
    do._schedule_deletion_audit_expiry = no_alarm
    before = snapshot(do)
    for product in (BOOKAI, B62):
        assert run(do.remove_product_link(payload(subject, product=product, validate_only=True))) == {
            "ok": True, "removable": True,
        }
    assert snapshot(do) == before


@pytest.mark.parametrize("change,code", [
    ({"product_id": "unreviewed"}, MISMATCH),
    ({"product_user_id": "missing"}, "canonical_product_identity_link_not_found"),
    ({"canonical_subject_id": "sub_" + "b" * 32}, "identity_rebind_forbidden"),
    ({"account_deletion_operation_id": "invalid"}, "invalid_identity_authority"),
    ({"validate_only": False}, "invalid_identity_authority"),
    ({"validate_only": 1}, "invalid_identity_authority"),
    ({"validate_only": "true"}, "invalid_identity_authority"),
    ({"unexpected": True}, "invalid_identity_authority_rpc"),
])
def test_validation_refuses_invalid_or_foreign_targets_without_mutation(change, code):
    do = authority()
    subject = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    before = snapshot(do)
    result = run(do.remove_product_link({**payload(subject, validate_only=True), **change}))
    assert result["ok"] is False and result["error"]["code"] == code
    assert snapshot(do) == before


def test_validation_refuses_inactive_link_without_mutation():
    do = authority()
    subject = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    do._storage.connection.execute("UPDATE canonical_product_identity_link SET state='revoked'")
    before = snapshot(do)
    result = run(do.remove_product_link(payload(subject, validate_only=True)))
    assert result["error"]["code"] == "canonical_product_identity_link_not_active"
    assert snapshot(do) == before


@pytest.mark.parametrize("configured", [None, "", "b61", "b62,b54-padiem-claw,lovetree-4-0", DEPLOYED_PRODUCTS + ",unknown"])
def test_code_and_removal_configuration_must_match_before_startup(configured):
    env = types.SimpleNamespace(CONTROL_PLANE_ALLOWED_PRODUCTS=DEPLOYED_PRODUCTS,
                                CONTROL_PLANE_IDENTITY_LOOKUP_KEY=_KEY, GOOGLE_CONNECT_TICKET_KEY=_KEY)
    if configured is not None:
        env.CONTROL_PLANE_LINK_REMOVAL_PRODUCTS = configured
    storage = _AlarmStorage()
    with pytest.raises(RuntimeError, match="removal boundary"):
        _worker_mod.CanonicalIdentityDurableObject(types.SimpleNamespace(storage=storage), env)
    assert storage.connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0


def test_removal_set_is_explicit_and_cannot_register_a_product():
    assert _worker_mod._LINK_REMOVAL_PRODUCTS <= _worker_mod._ALLOWED_PRODUCTS
    assert _worker_mod._LINK_ONLY_PRODUCTS == frozenset({BOOKAI})
    kwargs = {"lookup_key": b"K" * 32, "allowed_product_ids": _worker_mod._ALLOWED_PRODUCTS,
              "link_only_product_ids": _worker_mod._LINK_ONLY_PRODUCTS}
    store = CloudflareCanonicalIdentityAuthorityStore(_AlarmStorage(), **kwargs)
    assert BOOKAI not in store.safe_dict()["removable_product_ids"]
    with pytest.raises(ValueError, match="subset"):
        CloudflareCanonicalIdentityAuthorityStore(_AlarmStorage(), **kwargs, removable_product_ids=frozenset({"unreviewed"}))
    with pytest.raises(ValueError, match="frozenset"):
        CloudflareCanonicalIdentityAuthorityStore(_AlarmStorage(), **kwargs, removable_product_ids={BOOKAI})


@pytest.mark.parametrize("validate_only", [False, True])
def test_unreviewed_bookai_removal_stays_closed_before_any_mutation(validate_only):
    do = authority()
    do._store = CloudflareCanonicalIdentityAuthorityStore(
        do._storage, lookup_key=b"K" * 32,
        allowed_product_ids=_worker_mod._ALLOWED_PRODUCTS,
        link_only_product_ids=_worker_mod._LINK_ONLY_PRODUCTS,
    )
    subject = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    before = snapshot(do)
    refused = run(do.remove_product_link(payload(subject, validate_only=validate_only, operation=OPERATION)))
    assert refused["ok"] is False and refused["error"]["code"] == MISMATCH
    assert snapshot(do) == before
