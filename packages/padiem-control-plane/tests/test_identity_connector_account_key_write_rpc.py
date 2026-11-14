"""Account-keyed mutations use real authority storage and remain independently off."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from test_identity_connector_account_key_read_rpc import (
    authority, owner, account, run, code, B62, B54, BOOKAI, USER_A, USER_B,
    DEVICE, CONFIRMATION, _worker_mod, _non_owner,
)
from canonical_connector_account_rpc import CONNECTOR_ACCOUNT_KEY_RPC_SWITCH
from canonical_connector_account_write_rpc import (
    CONNECTOR_ACCOUNT_KEY_WRITE_METHODS, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH,
    CONNECTOR_ACCOUNT_KEY_WRITE_RPC_DISABLED,
)
from padiem_control_plane.local_agent_broker_pairing import MAX_PAIRING_TTL_SECONDS

GRANT = "grant_connector_enrollment_consent_for_subject"
REVOKE = "revoke_connector_enrollment_consent_for_subject"
BIND = "bind_connector_enrollment_challenge_for_subject"
REDEEM = "authorize_connector_enrollment_redeem_for_subject"
TICKET = "issue_google_connect_ticket_for_subject"
METHODS = (GRANT, REVOKE, BIND, REDEEM, TICKET)
CHALLENGE = "challenge.account.one"


def ready():
    do = authority()
    setattr(do.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH, "true")
    subject, tenant, sid = owner(do)
    return do, subject, tenant, sid


def wire(method, subject, *, consent="consent.missing", **changes):
    fields = {
        GRANT: {"device_id": DEVICE, "confirmed": True, "confirmation_version": CONFIRMATION},
        REVOKE: {"consent_id": consent, "confirmed": True, "confirmation_version": CONFIRMATION},
        BIND: {"challenge_id": CHALLENGE},
        REDEEM: {"challenge_id": CHALLENGE, "consent_id": consent, "device_id": DEVICE},
        TICKET: {"connector_id": "google-drive"},
    }[method]
    return account(subject, **fields) | changes


def invoke(do, method, subject, **changes):
    return run(getattr(do, method)(wire(method, subject, **changes)))


def prepare(do, subject):
    granted = invoke(do, GRANT, subject)
    assert granted["ok"] is True
    assert invoke(do, BIND, subject)["ok"] is True
    return granted["consent"]["consent_id"]


def snapshot(do):
    return tuple(do._storage.connection.iterdump())


@pytest.mark.parametrize("switch", [None, "", "false", "0", "1", "yes"])
def test_read_enabled_write_disabled_never_reads_or_writes(switch):
    do, subject, _, _ = ready()
    if switch is None:
        delattr(do.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH)
    else:
        setattr(do.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH, switch)
    statements = []
    do._storage.connection.set_trace_callback(statements.append)
    for method in METHODS:
        assert code(invoke(do, method, subject)) == CONNECTOR_ACCOUNT_KEY_WRITE_RPC_DISABLED
    assert not statements


def test_write_requires_read_gate_and_explicit_schema_install():
    do, subject, _, _ = ready()
    setattr(do.env, CONNECTOR_ACCOUNT_KEY_RPC_SWITCH, "false")
    before = snapshot(do)
    assert all(invoke(do, method, subject)["ok"] is False for method in METHODS)
    assert snapshot(do) == before
    raw = authority()
    # The fixture installs the schema explicitly; construction itself must not.
    from test_identity_connector_account_key_read_rpc import _AlarmStorage
    import types
    raw = _worker_mod.CanonicalIdentityDurableObject(types.SimpleNamespace(storage=_AlarmStorage()), raw.env)
    assert not raw._storage.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='canonical_connector_enrollment_account_binding'").fetchone()


def test_five_writes_succeed_and_replays_do_not_repeat_the_mutation():
    do, subject, tenant, _ = ready()
    before = datetime.now(timezone.utc)
    consent = prepare(do, subject)
    row = do._storage.connection.execute(
        "SELECT owner_subject_id,product_id,tenant_id,expires_at,consumed_at FROM canonical_connector_enrollment_account_binding"
    ).fetchone()
    assert tuple(row[:3]) == (subject, B62, tenant) and row[4] is None
    assert before < datetime.fromisoformat(row[3].replace("Z", "+00:00")) <= datetime.now(timezone.utc) + timedelta(seconds=MAX_PAIRING_TTL_SECONDS)
    for method in (GRANT, BIND):
        state = snapshot(do)
        assert invoke(do, method, subject)["ok"] is False
        assert snapshot(do) == state
    assert invoke(do, REDEEM, subject, consent=consent)["ok"] is True
    state = snapshot(do)
    assert code(invoke(do, REDEEM, subject, consent=consent)) == "connector_enrollment_challenge_consumed"
    assert snapshot(do) == state
    assert invoke(do, REVOKE, subject, consent=consent)["ok"] is True
    state = snapshot(do)
    assert invoke(do, REVOKE, subject, consent=consent)["ok"] is False
    assert snapshot(do) == state
    ticket = invoke(do, TICKET, subject)
    assert ticket["ok"] is True and ticket["ticket"]["connect_ticket"].startswith("v2.")


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("change", [{"tenant_id": "tenant.injected"}, {"role": "owner"},
                                    {"now": "2026-01-01"}, {"expires_at": "2099-01-01"},
                                    {"session_id": "session.injected"}])
def test_writes_reject_caller_authority_fields_without_mutation(method, change):
    do, subject, _, _ = ready()
    consent = prepare(do, subject)
    before = snapshot(do)
    assert code(invoke(do, method, subject, consent=consent, **change)) == "invalid_identity_authority_rpc"
    assert snapshot(do) == before


def withdraw_membership(do, tenant, subject):
    # #7542 P1-A closed the revoke_tenant_membership RPC; the membership state
    # these tests need is set through the store the RPC used to call.
    do._store.revoke_tenant_membership(
        tenant_id=tenant, canonical_subject_id=subject, now=datetime.now().astimezone(),
    )


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("condition", ["wrong_account", "wrong_product", "two_memberships", "withdrawn_membership", "unlinked", "deleted"])
def test_every_write_rejudges_current_authority_before_mutation(method, condition):
    do, subject, tenant, _ = ready()
    consent = prepare(do, subject)
    if condition == "wrong_account":
        subject = "sub_" + "0" * 32
    elif condition == "two_memberships":
        second = run(do.create_tenant({}))["tenant"]["tenant_id"]
        assert run(do.assign_tenant_membership({"tenant_id": second, "canonical_subject_id": subject, "role": "owner"}))["ok"]
    elif condition == "withdrawn_membership":
        withdraw_membership(do, tenant, subject)
    elif condition in {"unlinked", "deleted"}:
        products = (B62, B54) if condition == "deleted" else (B62,)
        for product in products:
            assert run(do.remove_product_link({"product_id": product, "product_user_id": USER_A,
                       "canonical_subject_id": subject, "account_deletion_operation_id": str(uuid.uuid4())}))["ok"]
    changes = {"product_id": BOOKAI} if condition == "wrong_product" else {}
    before = snapshot(do)
    assert invoke(do, method, subject, consent=consent, **changes)["ok"] is False
    assert snapshot(do) == before


def test_redemption_rechecks_consent_binding_product_tenant_and_expiry():
    for condition in ("other_owner", "other_product", "withdrawn", "expired", "other_tenant"):
        do, subject, tenant, _ = ready()
        consent = prepare(do, subject)
        target = subject
        changes = {}
        if condition == "other_owner":
            target, _, _ = owner(do, user=USER_B, person="person-b")
        elif condition == "other_product":
            changes["product_id"] = B54
        elif condition == "withdrawn":
            assert invoke(do, REVOKE, subject, consent=consent)["ok"]
        elif condition == "expired":
            do._storage.connection.execute("UPDATE canonical_connector_enrollment_account_binding SET expires_at='2000-01-01T00:00:00Z'")
        else:
            withdraw_membership(do, tenant, subject)
            second = run(do.create_tenant({}))["tenant"]["tenant_id"]
            assert run(do.assign_tenant_membership({"tenant_id": second, "canonical_subject_id": subject, "role": "owner"}))["ok"]
        before = snapshot(do)
        assert invoke(do, REDEEM, target, consent=consent, **changes)["ok"] is False
        assert snapshot(do) == before


def test_nonowners_cannot_register_and_ticket_accepts_only_its_reviewed_product():
    do = authority()
    setattr(do.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH, "true")
    subject = _non_owner(do, "operator")
    for method in (GRANT, REVOKE, BIND, REDEEM):
        assert code(invoke(do, method, subject)) == "connector_enrollment_owner_required"
    assert invoke(do, TICKET, subject)["ok"] is True
    assert invoke(do, TICKET, subject, product_id=B54)["ok"] is False


@pytest.mark.parametrize("account_first", [False, True])
def test_challenge_cannot_cross_key_types_in_either_order(account_first):
    do, subject, _, sid = ready()
    other, _, other_sid = owner(do, user=USER_B, person="person-b")
    legacy = {"session_id": other_sid, "challenge_id": CHALLENGE,
              "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}
    first = lambda: invoke(do, BIND, subject)
    second = lambda: run(do.bind_connector_enrollment_challenge(legacy))
    if not account_first:
        first, second = second, first
    assert first()["ok"] is True
    before = snapshot(do)
    assert second()["ok"] is False
    assert snapshot(do) == before
    # Another account's separate challenge remains allowed.
    assert invoke(do, BIND, other, challenge_id="challenge.other")["ok"] is True


def test_legacy_session_binding_works_without_the_new_schema_or_switch():
    do, _, _, sid = ready()
    do._storage.connection.execute("DROP TABLE canonical_connector_enrollment_account_binding")
    delattr(do.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH)
    assert run(do.bind_connector_enrollment_challenge({"session_id": sid, "challenge_id": CHALLENGE,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}))["ok"] is True


def test_legacy_write_answers_do_not_depend_on_the_account_write_switch():
    shapes = []
    for enabled in (False, True):
        do, _, _, sid = ready()
        setattr(do.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH, str(enabled).lower())
        grant = run(do.grant_connector_enrollment_consent({"session_id": sid, "device_id": DEVICE,
                    "confirmed": True, "confirmation_version": CONFIRMATION}))
        binding = run(do.bind_connector_enrollment_challenge({"session_id": sid, "challenge_id": CHALLENGE,
                      "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()}))
        scope = run(do.resolve_connector_owner_scope({"session_id": sid}))["scope"]
        redemption = {"challenge_id": CHALLENGE, "consent_id": grant["consent"]["consent_id"], "device_id": DEVICE,
                      "owner_ref": scope["owner_subject_id"], "account_ref": scope["account_ref"],
                      "workspace_ref": scope["workspace_ref"]}
        approved = run(do.authorize_connector_enrollment_redeem(redemption))
        # The old session-keyed authorization remains a recheck, not a new consumption contract.
        assert run(do.authorize_connector_enrollment_redeem(redemption))["ok"] is True
        revoked = run(do.revoke_connector_enrollment_consent({"session_id": sid,
                      "consent_id": grant["consent"]["consent_id"], "confirmed": True,
                      "confirmation_version": CONFIRMATION}))
        ticket = run(do.issue_google_connect_ticket({"session_id": sid, "connector_id": "google-drive"}))
        assert ticket["ticket"]["connect_ticket"].startswith("v1.")
        results = (grant, binding, approved, revoked, ticket)
        assert all(result["ok"] is True for result in results)
        shapes.append([sorted(result) for result in results])
        assert do._storage.connection.execute("SELECT count(*) FROM canonical_connector_enrollment_account_binding").fetchone()[0] == 0
    assert shapes[0] == shapes[1]


def test_switch_is_pinned_off_and_private_doors_export_only_reviewed_writes():
    from com2_identity_rpc_ingress import COM2_IDENTITY_RPC_METHODS
    assert set(METHODS) == CONNECTOR_ACCOUNT_KEY_WRITE_METHODS
    assert CONNECTOR_ACCOUNT_KEY_WRITE_METHODS <= _worker_mod.IDENTITY_RPC_INGRESS_METHODS
    assert CONNECTOR_ACCOUNT_KEY_WRITE_METHODS <= COM2_IDENTITY_RPC_METHODS
    assert all(callable(getattr(_worker_mod.Default, method, None)) for method in METHODS)
    assert CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH == "CONTROL_PLANE_CONNECTOR_ACCOUNT_KEY_WRITE_RPC_ENABLED"
