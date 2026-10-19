"""#4139 — product-common PC access contract tests.

Covers P1 (product-scoped PC capability contract), P3 (product-neutral
interface) and the P4 security/regression cases that are *new* for this
contract. Device-lifecycle and ONLINE projection are already covered by the
merged ``device_directory`` tests and the B62 projection tests, so they are
referenced rather than duplicated; the cases that matter here are the ones the
merged work does not have yet:

  S01  default policy is OFF — no product holds anything
  S02  an ungranted operation is refused for an enabled product
  S03  READ grant never implies WRITE
  S04  WRITE without a READ grant is refused
  S05  cross-product ticket/approval reuse is refused (both directions)
  S06  a workspace-scoped grant is refused from another workspace
  S07  product id is a routing/permission input, never authentication
  S08  device id is never a product-guard input (structural proof)
  S09  product, workspace and Broker internals never leak into the product view
  S10  same device id is preserved for every product (shared identity)
  S11  revoked / expired / session-less / unknown-state devices are not actionable
  S12  a malformed Broker directory fails the whole product view closed
  S13  no second engine / broker / device authority / P01 server is introduced
  S14  the local capability tokens still match the canonical vocabulary source

CENTRAL review hardening on top of the above:

  G01  only an ``owner_scoped:true`` **and** ``available:true`` envelope carries
       device facts; forged/false/missing attestation, an ``available:false``
       envelope that still lists devices, or an empty *attested* list refuses the
       whole view; the canonical ``no_device_binding`` read stays distinct
  G02  duplicated device id, more than the Broker device bound, a declared
       ``device_count`` mismatch, a malformed state/binding/session record or an
       out-of-bound ``max_devices`` refuses the whole view; the Broker's own
       ``reason`` / ``error.code`` / ``error.message`` text is never echoed
  G03  the P2 contract is **preflight only**: it can never return a dispatch
       authorization, has no fresh-online input, and a caller-supplied
       ``p01_verified_by_existing_path`` is an input, never proof
  G04  the product view leaks no credential / token / session material
  G05  the view device bound and state vocabulary still match the canonical
       Broker source
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_pc_access import (
    ACTIONABLE_DEVICE_STATE,
    B14_IS_PC_ACCESS_AUTHORITY,
    CANONICAL_LOCAL_CAPABILITY_FOR_OPERATION,
    CLIENT_DEVICE_ID_TRUSTED,
    CROSS_PRODUCT_TICKET_REUSE_ALLOWED,
    LOCAL_CAPABILITY_VOCABULARY_OWNER,
    NEW_BROKER_CREATED,
    NEW_DEVICE_AUTHORITY_CREATED,
    NEW_DEVICE_TABLE_CREATED,
    NEW_ENGINE_CREATED,
    NEW_P01_APPROVAL_SERVER_CREATED,
    ONLINE_DECIDED_IN_CONTRACT,
    PcAccessOperation,
    ProductPcAccessGrant,
    ProductPcAccessPolicy,
    PRODUCT_ID_IS_AUTHENTICATION,
    PRODUCT_ID_IS_ROUTING_PERMISSION_INPUT,
    PRODUCT_PC_ACCESS_CONTRACT_VERSION,
    PRODUCT_PC_ACCESS_DEFAULT,
    PRODUCT_VIEW_EXPOSES_BROKER_INTERNALS,
    READ_GRANT_IMPLIES_WRITE,
    SECOND_CAPABILITY_VOCABULARY,
    SECOND_DEVICE_AUTHORITY,
    SECOND_ONLINE_AUTHORITY,
    SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY,
    WRITE_REQUIRES_P01_APPROVAL,
    WRITE_REQUIRES_SEPARATE_GRANT,
    P01_VERIFIED_IS_AN_INPUT,
    PC_EXECUTION_PATH_NEWLY_WIRED,
    PC_EXECUTION_REPLAY_ALLOWED,
    READ_APPROVAL_CAN_AUTHORIZE_WRITE,
    build_product_device_view,
    device_eligible_for_pc_access,
    evaluate_pc_access,
    evaluate_pc_preflight,
    BROKER_MAX_DEVICE_CONSTANT,
    CANONICAL_DEVICE_STATES,
    DEVICE_VIEW_ECHOES_BROKER_ERROR_TEXT,
    DEVICE_VIEW_ENFORCES_DECLARED_DEVICE_COUNT,
    DEVICE_VIEW_ENFORCES_DUPLICATE_DEVICE_ID,
    DEVICE_VIEW_ENFORCES_MAX_DEVICES,
    DEVICE_VIEW_FAILS_CLOSED_ON_MALFORMED_ROW,
    DEVICE_VIEW_FAILS_CLOSED_ON_UNVERIFIED_ENVELOPE,
    DEVICE_VIEW_REPORTS_EMPTY_ATTESTED_DIRECTORY,
    DEVICE_VIEW_REQUIRES_AVAILABLE_ATTESTATION,
    DEVICE_VIEW_REQUIRES_OWNER_SCOPE_ATTESTATION,
    DISPATCH_AUTHORIZED_BY_THIS_CONTRACT,
    DISPATCH_GATE_WIRED,
    FRESH_ONLINE_PROVEN_IN_CONTRACT,
    MAX_PRODUCT_VIEW_DEVICES,
    NO_DEVICE_BINDING_REASON,
    ONLINE_PROOF_AUTHORITY,
    ONLINE_TRUTH_AUTHORITY,
    P01_VERIFIED_IS_A_CALLER_SUPPLIED_INPUT,
    PREFLIGHT_ONLY_NO_DISPATCH_GRANT,
    REQUIRED_DISPATCH_FACTS,
    TRUSTED_FRESH_ONLINE_FACT_AVAILABLE,
    VIEW_REASON_GRANTED,
    VIEW_REASON_MALFORMED,
    VIEW_REASON_UNAVAILABLE,
    VIEW_REASON_UNVERIFIED,
    pc_dispatch_requirements,
)

CLAW = "b54-padiem-claw"
CHAT = "b62"
QUOTE = "b66-padiem-quote"
ENGINE = "padiem-ai-engine"
WORKSPACE_A = "ws_a"
WORKSPACE_B = "ws_b"

READ_ONLY_GRANT = frozenset(
    {
        PcAccessOperation.DEVICE_LIST,
        PcAccessOperation.FILE_LIST,
        PcAccessOperation.FILE_READ,
        PcAccessOperation.TASK_STATUS,
        PcAccessOperation.TASK_RESULT,
    }
)


def _policy(*grants: ProductPcAccessGrant) -> ProductPcAccessPolicy:
    return ProductPcAccessPolicy(grants=tuple(grants))


def _row(
    *,
    device_id: str,
    canonical_state: str = ACTIONABLE_DEVICE_STATE,
    session: object = "present",
    heartbeat: object = "2026-10-12T00:00:00+00:00",
) -> dict:
    return {
        "canonical_state": canonical_state,
        "binding": {
            "binding_ref": f"bind_{device_id}",
            "device_id": device_id,
            "account_ref": "acct_a",
            "workspace_ref": WORKSPACE_A,
            "credential_generation": 1,
            "issued_at": "2026-10-01T00:00:00+00:00",
            "credential_expires_at": "2026-11-01T00:00:00+00:00",
            "credential_digest_exposed": False,
            "raw_device_credential": False,
        },
        "session": (
            {
                "session_id": f"sess_{device_id}",
                "binding_ref": f"bind_{device_id}",
                "device_id": device_id,
                "account_ref": "acct_a",
                "workspace_ref": WORKSPACE_A,
                "credential_generation": 1,
                "issued_at": "2026-10-01T00:00:00+00:00",
                "expires_at": "2026-10-02T00:00:00+00:00",
                "raw_session_secret": False,
            }
            if session == "present"
            else None
        ),
        "heartbeat_last_seen_at": heartbeat,
    }


def _directory(*rows: dict) -> dict:
    return {
        "ok": True,
        "available": True,
        "owner_scoped": True,
        "device_count": len(rows),
        "max_devices": MAX_PRODUCT_VIEW_DEVICES,
        "devices": list(rows),
    }


# --- S01 default OFF -------------------------------------------------------


def test_s01_default_policy_grants_nothing():
    policy = ProductPcAccessPolicy.default_off()
    assert policy.grants == ()
    assert PRODUCT_PC_ACCESS_DEFAULT == "off"
    for product in (CLAW, CHAT, QUOTE, ENGINE, "unknown-product"):
        for operation in PcAccessOperation:
            decision = evaluate_pc_access(policy=policy, product_id=product, operation=operation)
            assert decision.allowed is False
            assert decision.reason == "product_not_enabled"
            assert decision.requires_p01_approval is False


def test_s01_enabled_product_is_still_limited_to_its_grant():
    policy = _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST})))
    assert evaluate_pc_access(
        policy=policy, product_id=CLAW, operation=PcAccessOperation.DEVICE_LIST
    ).allowed is True
    denied = evaluate_pc_access(policy=policy, product_id=CLAW, operation=PcAccessOperation.FILE_READ)
    assert denied.allowed is False
    assert denied.reason == "capability_not_granted"


# --- S02/S03/S04 read/write isolation --------------------------------------


def test_s02_pc_touching_operations_keep_the_approval_floor():
    policy = _policy(ProductPcAccessGrant(CLAW, READ_ONLY_GRANT))
    for operation in (PcAccessOperation.FILE_LIST, PcAccessOperation.FILE_READ):
        decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation=operation)
        assert decision.allowed is True
        assert decision.requires_p01_approval is True
        assert decision.write_boundary is False
    for operation in (
        PcAccessOperation.DEVICE_LIST,
        PcAccessOperation.TASK_STATUS,
        PcAccessOperation.TASK_RESULT,
    ):
        decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation=operation)
        assert decision.allowed is True
        assert decision.requires_p01_approval is False


def test_s03_read_grant_never_implies_write():
    policy = _policy(ProductPcAccessGrant(CLAW, READ_ONLY_GRANT))
    decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation=PcAccessOperation.FILE_WRITE)
    assert decision.allowed is False
    assert decision.reason == "capability_not_granted"
    assert decision.write_boundary is True
    assert READ_GRANT_IMPLIES_WRITE is False


def test_s03_write_grant_keeps_the_write_boundary_and_approval():
    policy = _policy(ProductPcAccessGrant(CLAW, READ_ONLY_GRANT | {PcAccessOperation.FILE_WRITE}))
    decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation=PcAccessOperation.FILE_WRITE)
    assert decision.allowed is True
    assert decision.write_boundary is True
    assert decision.requires_p01_approval is True
    assert WRITE_REQUIRES_SEPARATE_GRANT is True
    assert WRITE_REQUIRES_P01_APPROVAL is True


def test_s04_write_without_read_grant_is_refused():
    policy = _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.FILE_WRITE})))
    decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation=PcAccessOperation.FILE_WRITE)
    assert decision.allowed is False
    assert decision.reason == "write_requires_read_grant"


# --- S05 cross-product reuse ----------------------------------------------


@pytest.mark.parametrize("caller,bound", [(CHAT, CLAW), (CLAW, CHAT), (QUOTE, CHAT)])
def test_s05_cross_product_ticket_reuse_is_refused(caller, bound):
    policy = _policy(ProductPcAccessGrant(caller, READ_ONLY_GRANT))
    decision = evaluate_pc_access(
        policy=policy,
        product_id=caller,
        operation=PcAccessOperation.TASK_RESULT,
        bound_product_id=bound,
    )
    assert decision.allowed is False
    assert decision.reason == "cross_product_ticket_reuse_denied"
    assert CROSS_PRODUCT_TICKET_REUSE_ALLOWED is False


def test_s05_same_product_ticket_is_accepted():
    policy = _policy(ProductPcAccessGrant(CLAW, READ_ONLY_GRANT))
    decision = evaluate_pc_access(
        policy=policy,
        product_id=CLAW,
        operation=PcAccessOperation.TASK_RESULT,
        bound_product_id=CLAW,
    )
    assert decision.allowed is True


# --- S06 workspace narrowing ----------------------------------------------


def test_s06_workspace_scoped_grant_is_refused_from_another_workspace():
    policy = _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST}), WORKSPACE_A))
    other = evaluate_pc_access(
        policy=policy,
        product_id=CLAW,
        operation=PcAccessOperation.DEVICE_LIST,
        workspace_ref=WORKSPACE_B,
    )
    assert other.allowed is False
    assert other.reason == "product_workspace_not_granted"
    same = evaluate_pc_access(
        policy=policy,
        product_id=CLAW,
        operation=PcAccessOperation.DEVICE_LIST,
        workspace_ref=WORKSPACE_A,
    )
    assert same.allowed is True
    ungranted = evaluate_pc_access(
        policy=policy,
        product_id=CLAW,
        operation=PcAccessOperation.DEVICE_LIST,
    )
    assert ungranted.allowed is False
    assert ungranted.reason == "product_workspace_not_granted"


# --- S07 product id is routing, not authentication ------------------------


def test_s07_product_id_is_not_identity():
    policy = _policy(ProductPcAccessGrant(CLAW, READ_ONLY_GRANT))
    decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation=PcAccessOperation.DEVICE_LIST)
    payload = decision.safe_dict()
    assert payload["product_id_is_identity"] is False
    assert payload["caller_approval_authority"] is False
    assert payload["p01_approval_authority"].startswith("existing")
    # No subject / account / tenant / token can be asserted through this guard.
    for forbidden in ("subject", "account_ref", "tenant_id", "token", "credential", "session"):
        assert forbidden not in payload
    assert PRODUCT_ID_IS_AUTHENTICATION is False
    assert PRODUCT_ID_IS_ROUTING_PERMISSION_INPUT is True
    assert SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY is False


def test_s07_malformed_request_fails_closed():
    policy = _policy(ProductPcAccessGrant(CLAW, READ_ONLY_GRANT))
    for bad_product in ("", " ", "a b", None, 7, "x" * 200):
        decision = evaluate_pc_access(policy=policy, product_id=bad_product, operation=PcAccessOperation.DEVICE_LIST)
        assert decision.allowed is False
        assert decision.reason == "invalid_pc_access_request"
    decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation="not.an.operation")
    assert decision.allowed is False
    assert decision.reason == "invalid_pc_access_request"
    decision = evaluate_pc_access(policy=policy, product_id=CLAW, operation=PcAccessOperation.DEVICE_LIST, bound_product_id="bad ref!")
    assert decision.allowed is False
    assert decision.reason == "invalid_pc_access_request"


# --- S08 device id is never an input --------------------------------------


def test_s08_guard_accepts_no_device_id():
    evaluate_signature = inspect.signature(evaluate_pc_access)
    view_signature = inspect.signature(build_product_device_view)
    for signature in (evaluate_signature, view_signature):
        assert "device_id" not in signature.parameters
        assert "device_ref" not in signature.parameters
    assert CLIENT_DEVICE_ID_TRUSTED is False


# --- S09/S10 product view --------------------------------------------------


def test_s09_product_view_is_sanitized():
    policy = _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST})))
    view = build_product_device_view(
        policy=policy,
        product_id=CLAW,
        directory_result=_directory(_row(device_id="office-pc"), _row(device_id="home-pc")),
    )
    assert view["available"] is True
    assert view["sanitized"] is True
    assert view["online_decided_here"] is False
    serialized = json.dumps(view)
    for forbidden in (
        "account_ref",
        "workspace_ref",
        "binding_ref",
        "session_id",
        "credential",
        "raw_session_secret",
        "heartbeat_last_seen_at",
    ):
        assert forbidden not in serialized
    assert PRODUCT_VIEW_EXPOSES_BROKER_INTERNALS is False
    assert set(view["devices"][0]) == {
        "device_id",
        "canonical_state",
        "has_session",
        "heartbeat_present",
        "actionable",
        "online_decided_here",
    }


def test_s09_product_without_device_list_grant_gets_no_devices():
    policy = ProductPcAccessPolicy.default_off()
    view = build_product_device_view(
        policy=policy,
        product_id=CHAT,
        directory_result=_directory(_row(device_id="office-pc")),
    )
    assert view["available"] is False
    assert view["product_may_list_devices"] is False
    assert view["reason"] == "product_not_enabled"
    assert view["devices"] == []
    assert view["device_count"] == 0


def test_s09_unavailable_directory_is_not_invented():
    policy = _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST})))
    view = build_product_device_view(
        policy=policy,
        product_id=CLAW,
        directory_result={"ok": True, "available": False, "reason": "no_device_binding"},
    )
    assert view["available"] is False
    assert view["reason"] == "no_device_binding"
    assert view["devices"] == []


def test_s09_cross_product_bound_ticket_is_refused_in_the_view():
    policy = _policy(ProductPcAccessGrant(CHAT, frozenset({PcAccessOperation.DEVICE_LIST})))
    view = build_product_device_view(
        policy=policy,
        product_id=CHAT,
        directory_result=_directory(_row(device_id="office-pc")),
        bound_product_id=CLAW,
    )
    assert view["available"] is False
    assert view["reason"] == "cross_product_ticket_reuse_denied"


def test_s10_every_product_sees_the_same_device_id():
    directory = _directory(_row(device_id="office-pc"), _row(device_id="home-pc"), _row(device_id="laptop"))
    for product in (CLAW, QUOTE, CHAT, ENGINE):
        policy = _policy(ProductPcAccessGrant(product, frozenset({PcAccessOperation.DEVICE_LIST})))
        view = build_product_device_view(policy=policy, product_id=product, directory_result=directory)
        assert [row["device_id"] for row in view["devices"]] == ["office-pc", "home-pc", "laptop"]


# --- S11 device lifecycle --------------------------------------------------


def test_s11_terminal_and_session_less_devices_are_not_actionable():
    assert device_eligible_for_pc_access(_row(device_id="ok")) is True
    assert device_eligible_for_pc_access(_row(device_id="rev", canonical_state="revoked")) is False
    assert device_eligible_for_pc_access(_row(device_id="exp", canonical_state="credential_expired")) is False
    assert device_eligible_for_pc_access(_row(device_id="odd", canonical_state="online")) is False
    assert device_eligible_for_pc_access(_row(device_id="new", canonical_state="pending")) is False
    assert device_eligible_for_pc_access(_row(device_id="nosess", session="absent")) is False
    assert device_eligible_for_pc_access({}) is False
    assert device_eligible_for_pc_access("not-a-mapping") is False
    assert ONLINE_DECIDED_IN_CONTRACT is False


def test_s11_view_reports_actionable_without_claiming_online():
    policy = _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST})))
    view = build_product_device_view(
        policy=policy,
        product_id=CLAW,
        directory_result=_directory(
            _row(device_id="office-pc"),
            _row(device_id="old-pc", canonical_state="revoked"),
            _row(device_id="quiet-pc", heartbeat=None),
        ),
    )
    by_id = {row["device_id"]: row for row in view["devices"]}
    assert by_id["office-pc"]["actionable"] is True
    assert by_id["old-pc"]["actionable"] is False
    assert by_id["quiet-pc"]["actionable"] is True
    assert by_id["quiet-pc"]["heartbeat_present"] is False
    assert all(row["online_decided_here"] is False for row in view["devices"])


# --- S12 fail-closed Brokker directory ------------------------------------

@pytest.mark.parametrize(
    "directory_result",
    [
        {"ok": False, "error": {"code": "device_directory_too_large"}},
        {"ok": True, "devices": "not-a-list"},
        {"ok": True, "devices": ["not-a-mapping"]},
        {"ok": True, "devices": [{"canonical_state": ACTIONABLE_DEVICE_STATE, "session": {}}]},
        {"ok": True, "devices": [_row(device_id="bad id!")]},
        "not-a-mapping",
        None,
    ],
)
def test_s12_malformed_directory_fails_the_whole_view_closed(directory_result):
    policy = _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST})))
    view = build_product_device_view(policy=policy, product_id=CLAW, directory_result=directory_result)
    assert view["available"] is False
    assert view["devices"] == []
    assert view["device_count"] == 0


# --- policy validation -----------------------------------------------------


def test_policy_rejects_duplicate_grants_and_bad_inputs():
    grant = ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST}))
    with pytest.raises(ControlPlaneContractError):
        ProductPcAccessPolicy(grants=(grant, grant))
    with pytest.raises(ControlPlaneContractError):
        ProductPcAccessPolicy(grants=[grant])  # type: ignore[arg-type]
    with pytest.raises(ControlPlaneContractError):
        ProductPcAccessGrant(CLAW, frozenset())
    with pytest.raises(ControlPlaneContractError):
        ProductPcAccessGrant("bad ref!", frozenset({PcAccessOperation.DEVICE_LIST}))
    with pytest.raises(ControlPlaneContractError):
        ProductPcAccessGrant(CLAW, frozenset({"not.an.operation"}))
    with pytest.raises(ControlPlaneContractError):
        evaluate_pc_access(policy="not-a-policy", product_id=CLAW, operation=PcAccessOperation.DEVICE_LIST)


def test_policy_accepts_string_operations_and_normalizes():
    grant = ProductPcAccessGrant(CLAW, frozenset({"device.list", "task.result"}))
    policy = _policy(grant)
    assert grant.operations == frozenset({PcAccessOperation.DEVICE_LIST, PcAccessOperation.TASK_RESULT})
    assert evaluate_pc_access(
        policy=policy, product_id=CLAW, operation="task.result"
    ).allowed is True


def test_policy_safe_dict_is_bounded():
    policy = _policy(ProductPcAccessGrant(CLAW, READ_ONLY_GRANT))
    payload = policy.safe_dict()
    assert payload["default"] == "off"
    assert payload["contract_version"] == PRODUCT_PC_ACCESS_CONTRACT_VERSION
    assert payload["grants"][0]["product_id_is_identity"] is False
    assert payload["grants"][0]["operations"] == sorted(item.value for item in READ_ONLY_GRANT)


# --- S13 no new authority --------------------------------------------------


def test_s13_no_second_authority_constants():
    assert B14_IS_PC_ACCESS_AUTHORITY is False
    assert NEW_ENGINE_CREATED is False
    assert NEW_BROKER_CREATED is False
    assert NEW_DEVICE_AUTHORITY_CREATED is False
    assert NEW_DEVICE_TABLE_CREATED is False
    assert NEW_P01_APPROVAL_SERVER_CREATED is False
    assert SECOND_ONLINE_AUTHORITY is False
    assert SECOND_DEVICE_AUTHORITY is False
    assert SECOND_CAPABILITY_VOCABULARY is False


# --- P2 preflight eligibility (never a dispatch grant) ---------------------

WRITE_GRANT = READ_ONLY_GRANT | {PcAccessOperation.FILE_WRITE}


def _view(**overrides):
    """Build a product view with a granted ``device.list`` unless overridden."""

    policy = overrides.pop(
        "policy",
        _policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST}))),
    )
    directory_result = overrides.pop(
        "directory_result", _directory(_row(device_id="office-pc"))
    )
    return build_product_device_view(
        policy=policy,
        product_id=overrides.pop("product_id", CLAW),
        directory_result=directory_result,
        **overrides,
    )


def _assert_refused(view: dict) -> None:
    """A refused view never carries a device fact or an attestation."""

    assert view["available"] is False
    assert view["devices"] == []
    assert view["device_count"] == 0
    assert view["owner_scoped"] is False
    assert view["directory_verified"] is False
    assert view["dispatch_authorized"] is False


def _preflight(**overrides):
    facts = overrides.pop("device_facts", _row(device_id="office-pc"))
    kwargs = dict(
        policy=_policy(ProductPcAccessGrant(CLAW, WRITE_GRANT)),
        product_id=CLAW,
        operation=PcAccessOperation.FILE_READ,
        bound_product_id=CLAW,
        account_ref="acct_a",
        workspace_ref=WORKSPACE_A,
        device_facts=facts,
        p01_verified_by_existing_path=True,
        p01_product_id=CLAW,
        p01_read_only=True,
        replay=False,
    )
    kwargs.update(overrides)
    return evaluate_pc_preflight(**kwargs)


def test_p02_preflight_requires_the_product_grant_first():
    decision = _preflight(policy=ProductPcAccessPolicy.default_off())
    assert decision.preflight_eligible is False
    assert decision.reason == "product_not_enabled"
    assert decision.dispatch_authorized is False


def test_p02_preflight_refuses_a_foreign_account_or_workspace():
    other_account = _row(device_id="office-pc")
    other_account["binding"]["account_ref"] = "acct_b"
    assert _preflight(device_facts=other_account).reason == "device_scope_mismatch"
    other_workspace = _row(device_id="office-pc")
    other_workspace["binding"]["workspace_ref"] = WORKSPACE_B
    assert _preflight(device_facts=other_workspace).reason == "device_scope_mismatch"


@pytest.mark.parametrize(
    "facts",
    [
        _row(device_id="rev", canonical_state="revoked"),
        _row(device_id="exp", canonical_state="credential_expired"),
        _row(device_id="nosess", session="absent"),
        _row(device_id="odd", canonical_state="online"),
    ],
)
def test_p02_preflight_refuses_non_actionable_devices(facts):
    decision = _preflight(device_facts=facts)
    assert decision.preflight_eligible is False
    assert decision.reason == "device_not_actionable"
    assert decision.dispatch_authorized is False


def test_p02_pc_touching_operation_requires_p01():
    decision = _preflight(p01_verified_by_existing_path=False)
    assert decision.preflight_eligible is False
    assert decision.reason == "p01_approval_required"
    assert P01_VERIFIED_IS_AN_INPUT is True
    assert P01_VERIFIED_IS_A_CALLER_SUPPLIED_INPUT is True


def test_p02_pc_touching_operation_requires_p01_minted_for_this_product():
    decision = _preflight(p01_product_id=CHAT)
    assert decision.preflight_eligible is False
    assert decision.reason == "cross_product_approval_reuse_denied"
    decision = _preflight(p01_product_id=None)
    assert decision.preflight_eligible is False
    assert decision.reason == "cross_product_approval_reuse_denied"


def test_p02_read_approval_cannot_authorize_write():
    decision = _preflight(operation=PcAccessOperation.FILE_WRITE, p01_read_only=True)
    assert decision.preflight_eligible is False
    assert decision.reason == "read_approval_cannot_write"
    assert READ_APPROVAL_CAN_AUTHORIZE_WRITE is False
    eligible = _preflight(operation=PcAccessOperation.FILE_WRITE, p01_read_only=False)
    assert eligible.preflight_eligible is True
    # Fully satisfied preflight still releases nothing.
    assert eligible.dispatch_authorized is False


def test_p02_replay_is_denied():
    decision = _preflight(replay=True)
    assert decision.preflight_eligible is False
    assert decision.reason == "replay_denied"
    assert PC_EXECUTION_REPLAY_ALLOWED is False


def test_p02_server_reads_do_not_need_p01_but_still_need_the_grant():
    eligible = _preflight(
        operation=PcAccessOperation.TASK_RESULT,
        p01_verified_by_existing_path=False,
        p01_product_id=None,
    )
    assert eligible.preflight_eligible is True
    assert eligible.dispatch_authorized is False
    denied = evaluate_pc_preflight(
        policy=_policy(ProductPcAccessGrant(CLAW, frozenset({PcAccessOperation.DEVICE_LIST}))),
        product_id=CLAW,
        operation=PcAccessOperation.TASK_RESULT,
        bound_product_id=CLAW,
        account_ref="acct_a",
        workspace_ref=WORKSPACE_A,
        device_facts=_row(device_id="office-pc"),
    )
    assert denied.preflight_eligible is False
    assert denied.reason == "capability_not_granted"


def test_p02_preflight_cross_product_ticket_is_refused():
    decision = _preflight(bound_product_id=CHAT)
    assert decision.preflight_eligible is False
    assert decision.reason == "cross_product_ticket_reuse_denied"


def test_p02_no_implicit_approval_and_no_caller_authority():
    # Omitting the approval inputs must not imply approval.
    implicit = evaluate_pc_preflight(
        policy=_policy(ProductPcAccessGrant(CLAW, WRITE_GRANT)),
        product_id=CLAW,
        operation=PcAccessOperation.FILE_READ,
        bound_product_id=CLAW,
        account_ref="acct_a",
        workspace_ref=WORKSPACE_A,
        device_facts=_row(device_id="office-pc"),
    )
    assert implicit.preflight_eligible is False
    assert implicit.reason == "p01_approval_required"
    payload = implicit.safe_dict()
    assert payload["caller_approval_authority"] is False
    assert payload["p01_verification_authority"].startswith("existing")
    assert payload["dispatch_authorized"] is False
    assert PC_EXECUTION_PATH_NEWLY_WIRED is False


# --- G01 owner-scope / availability attestation ---------------------------


def test_g01_device_facts_require_the_owner_scope_attestation():
    forged = _directory(_row(device_id="office-pc"))
    forged.pop("owner_scoped")
    view = _view(directory_result=forged)
    _assert_refused(view)
    assert view["reason"] == VIEW_REASON_UNVERIFIED
    assert DEVICE_VIEW_REQUIRES_OWNER_SCOPE_ATTESTATION is True
    assert DEVICE_VIEW_FAILS_CLOSED_ON_UNVERIFIED_ENVELOPE is True


@pytest.mark.parametrize("value", [False, None, 1, "true", []])
def test_g01_owner_scope_false_or_non_boolean_is_refused(value):
    forged = _directory(_row(device_id="office-pc"))
    forged["owner_scoped"] = value
    view = _view(directory_result=forged)
    _assert_refused(view)
    assert view["reason"] == VIEW_REASON_UNVERIFIED


@pytest.mark.parametrize("value", [False, None, 1, "true", []])
def test_g01_available_false_or_non_boolean_is_refused(value):
    forged = _directory(_row(device_id="office-pc"))
    forged["available"] = value
    view = _view(directory_result=forged)
    _assert_refused(view)
    assert view["reason"] == VIEW_REASON_UNVERIFIED
    assert DEVICE_VIEW_REQUIRES_AVAILABLE_ATTESTATION is True


@pytest.mark.parametrize("owner_scoped", [True, False])
def test_g01_available_false_with_device_facts_is_refused(owner_scoped):
    contradictory = {
        "ok": True,
        "available": False,
        "owner_scoped": owner_scoped,
        "devices": [_row(device_id="office-pc")],
        "device_count": 1,
    }
    _assert_refused(_view(directory_result=contradictory))


def test_g01_canonical_no_binding_read_stays_distinct_and_verified():
    view = _view(
        directory_result={"ok": True, "available": False, "reason": NO_DEVICE_BINDING_REASON}
    )
    assert view["available"] is False
    assert view["reason"] == NO_DEVICE_BINDING_REASON
    assert view["devices"] == []
    assert view["owner_scoped"] is True
    assert view["directory_verified"] is True
    assert view["dispatch_authorized"] is False


def test_g01_empty_attested_directory_is_a_contradiction_not_a_connected_state():
    empty = _directory()
    view = _view(directory_result=empty)
    _assert_refused(view)
    assert view["reason"] == VIEW_REASON_UNVERIFIED
    assert DEVICE_VIEW_REPORTS_EMPTY_ATTESTED_DIRECTORY is False


@pytest.mark.parametrize(
    "directory_result",
    [
        None,
        "not-a-mapping",
        [],
        {"ok": "true", "available": True, "owner_scoped": True, "devices": []},
        {"ok": True, "owner_scoped": True, "devices": []},
    ],
)
def test_g01_unattested_or_unusable_envelopes_are_refused(directory_result):
    _assert_refused(_view(directory_result=directory_result))


# --- G02 directory integrity invariants -----------------------------------


def test_g02_duplicate_device_id_is_refused_whole():
    duplicated = _directory(_row(device_id="office-pc"), _row(device_id="office-pc"))
    view = _view(directory_result=duplicated)
    _assert_refused(view)
    assert view["reason"] == VIEW_REASON_MALFORMED
    assert DEVICE_VIEW_ENFORCES_DUPLICATE_DEVICE_ID is True


def test_g02_more_than_the_broker_device_bound_is_refused_whole():
    rows = [_row(device_id=f"pc-{index:02d}") for index in range(MAX_PRODUCT_VIEW_DEVICES)]
    full = _view(directory_result=_directory(*rows))
    assert full["available"] is True
    assert full["device_count"] == MAX_PRODUCT_VIEW_DEVICES
    over = _directory(*rows, _row(device_id="pc-over"))
    _assert_refused(_view(directory_result=over))
    assert MAX_PRODUCT_VIEW_DEVICES == 24
    assert DEVICE_VIEW_ENFORCES_MAX_DEVICES is True


def test_g02_declared_device_count_must_match_the_list():
    mismatched = _directory(_row(device_id="office-pc"))
    mismatched["device_count"] = 7
    _assert_refused(_view(directory_result=mismatched))
    missing = _directory(_row(device_id="office-pc"))
    missing.pop("device_count")
    _assert_refused(_view(directory_result=missing))
    boolean_count = _directory(_row(device_id="office-pc"))
    boolean_count["device_count"] = True
    _assert_refused(_view(directory_result=boolean_count))
    text_count = _directory(_row(device_id="office-pc"))
    text_count["device_count"] = "1"
    _assert_refused(_view(directory_result=text_count))
    assert DEVICE_VIEW_ENFORCES_DECLARED_DEVICE_COUNT is True


def test_g02_max_devices_field_must_agree_with_the_canonical_bound():
    for value in (500, 0, "24", True):
        widened = _directory(_row(device_id="office-pc"))
        widened["max_devices"] = value
        _assert_refused(_view(directory_result=widened))


@pytest.mark.parametrize(
    "row",
    [
        {"canonical_state": ACTIONABLE_DEVICE_STATE},
        {"binding": "office-pc", "canonical_state": ACTIONABLE_DEVICE_STATE},
        {"binding": {}, "canonical_state": ACTIONABLE_DEVICE_STATE},
        {"binding": {"device_id": "bad id!"}, "canonical_state": ACTIONABLE_DEVICE_STATE},
        {"binding": {"device_id": "office-pc"}, "canonical_state": 7},
        {"binding": {"device_id": "office-pc"}, "canonical_state": "ONLINE"},
        {"binding": {"device_id": "office-pc"}, "canonical_state": "pending"},
        {"binding": {"device_id": "office-pc"}, "canonical_state": ACTIONABLE_DEVICE_STATE, "session": "session"},
        {"binding": {"device_id": "office-pc"}, "canonical_state": ACTIONABLE_DEVICE_STATE, "session": {}},
        {
            "binding": {"device_id": "office-pc"},
            "canonical_state": ACTIONABLE_DEVICE_STATE,
            "session": {"device_id": "other-pc"},
        },
        {
            "binding": {"device_id": "office-pc", "workspace_ref": WORKSPACE_A},
            "canonical_state": ACTIONABLE_DEVICE_STATE,
            "session": {"device_id": "office-pc", "workspace_ref": WORKSPACE_B},
        },
        {
            "binding": {"device_id": "office-pc", "binding_ref": "bind_a"},
            "canonical_state": ACTIONABLE_DEVICE_STATE,
            "session": {"device_id": "office-pc", "binding_ref": "bind_b"},
        },
        {"binding": {"device_id": "office-pc"}, "canonical_state": ACTIONABLE_DEVICE_STATE, "heartbeat_last_seen_at": 12345},
    ],
)
def test_g02_malformed_records_fail_the_whole_view_closed(row):
    view = _view(directory_result=_directory(row))
    _assert_refused(view)
    assert view["reason"] == VIEW_REASON_MALFORMED
    assert DEVICE_VIEW_FAILS_CLOSED_ON_MALFORMED_ROW is True


def test_g02_broker_error_text_and_reason_are_never_echoed():
    error_view = _view(
        directory_result={
            "ok": False,
            "error": {
                "code": "device_directory_too_large",
                "message": "internal broker detail",
            },
        }
    )
    _assert_refused(error_view)
    assert error_view["reason"] == VIEW_REASON_UNAVAILABLE
    serialized = json.dumps(error_view)
    assert "device_directory_too_large" not in serialized
    assert "internal broker detail" not in serialized
    odd = _view(
        directory_result={"ok": True, "available": False, "reason": "internal_state_dump"}
    )
    assert odd["reason"] == VIEW_REASON_UNAVAILABLE
    assert "internal_state_dump" not in json.dumps(odd)
    assert DEVICE_VIEW_ECHOES_BROKER_ERROR_TEXT is False


def test_g02_a_valid_directory_still_carries_the_product_neutral_rows():
    view = _view(
        directory_result=_directory(
            _row(device_id="home-pc"),
            _row(device_id="office-pc"),
            _row(device_id="old-pc", canonical_state="revoked"),
        )
    )
    assert view["available"] is True
    assert view["directory_verified"] is True
    assert view["reason"] == VIEW_REASON_GRANTED
    assert view["dispatch_authorized"] is False
    by_id = {row["device_id"]: row for row in view["devices"]}
    assert by_id["home-pc"]["actionable"] is True
    assert by_id["old-pc"]["actionable"] is False
    assert CANONICAL_DEVICE_STATES == {"paired_offline", "revoked", "credential_expired"}


# --- G03 preflight is never a dispatch authorization ----------------------


def test_g03_preflight_never_authorizes_dispatch():
    eligible = _preflight()
    assert eligible.preflight_eligible is True
    assert eligible.dispatch_authorized is False
    payload = eligible.safe_dict()
    assert payload["dispatch_authorized"] is False
    assert payload["dispatch_gate_wired"] is False
    assert payload["preflight_only"] is True
    assert payload["fresh_online_proven_here"] is False
    assert payload["online_proof_authority"] == ONLINE_PROOF_AUTHORITY
    assert set(payload["required_dispatch_facts"]) == set(REQUIRED_DISPATCH_FACTS)
    assert "allowed" not in payload
    assert PREFLIGHT_ONLY_NO_DISPATCH_GRANT is True
    assert DISPATCH_AUTHORIZED_BY_THIS_CONTRACT is False
    assert FRESH_ONLINE_PROVEN_IN_CONTRACT is False
    assert TRUSTED_FRESH_ONLINE_FACT_AVAILABLE is False
    assert ONLINE_TRUTH_AUTHORITY == "canonical_broker_fresh_online_projection"


def test_g03_a_fresh_looking_heartbeat_never_becomes_a_dispatch_grant():
    fresh = _row(device_id="office-pc", heartbeat="2026-10-12T23:59:59+00:00")
    decision = _preflight(device_facts=fresh)
    assert decision.preflight_eligible is True
    assert decision.dispatch_authorized is False
    # And without any heartbeat fact at all, nothing is released either.
    quiet = _preflight(device_facts=_row(device_id="office-pc", heartbeat=None))
    assert quiet.dispatch_authorized is False


def test_g03_caller_supplied_p01_boolean_is_an_input_not_proof():
    payload = _preflight(p01_verified_by_existing_path=True).safe_dict()
    assert payload["p01_verified_is_caller_supplied_input"] is True
    assert payload["caller_approval_authority"] is False
    assert payload["dispatch_authorized"] is False


def test_g03_the_contract_accepts_no_fresh_online_input():
    parameters = set(inspect.signature(evaluate_pc_preflight).parameters)
    for forbidden in (
        "fresh_online",
        "fresh_online_verified",
        "online",
        "heartbeat_last_seen_at",
        "dispatch_authorized",
    ):
        assert forbidden not in parameters


def test_g03_dispatch_requirements_declare_the_trusted_facts_and_grant_nothing():
    requirements = pc_dispatch_requirements(
        product_id=CLAW, operation=PcAccessOperation.FILE_WRITE
    )
    assert requirements["ok"] is True
    assert requirements["dispatch_authorized"] is False
    assert requirements["dispatch_gate_wired"] is False
    assert requirements["new_authority_created"] is False
    assert requirements["pc_touching"] is True
    assert requirements["online_proof_authority"] == ONLINE_PROOF_AUTHORITY
    assert set(requirements["required_dispatch_facts"]) == set(REQUIRED_DISPATCH_FACTS)
    assert DISPATCH_GATE_WIRED is False
    assert len(REQUIRED_DISPATCH_FACTS) == 4
    invalid = pc_dispatch_requirements(
        product_id="bad ref!", operation=PcAccessOperation.FILE_READ
    )
    assert invalid["ok"] is False
    assert invalid["dispatch_authorized"] is False


# --- G04/G05 view confidentiality and canonical parity --------------------


def test_g04_the_view_never_exposes_credential_token_or_session_material():
    view = _view(
        directory_result=_directory(
            _row(device_id="office-pc"),
            _row(device_id="old-pc", canonical_state="revoked"),
        )
    )
    serialized = json.dumps(view)
    for forbidden in (
        "account_ref",
        "workspace_ref",
        "binding_ref",
        "session_id",
        "credential",
        "credential_generation",
        "raw_session_secret",
        "raw_device_credential",
        "token",
        "secret",
        "heartbeat_last_seen_at",
        "issued_at",
        "expires_at",
    ):
        assert forbidden not in serialized


def test_g05_view_device_bound_matches_the_canonical_broker_constant():
    repo_root = Path(__file__).resolve().parents[3]
    runtime = repo_root / "packages" / "padiem-control-plane" / "local_agent_broker_durable_runtime.py"
    if not runtime.is_file():
        pytest.skip("canonical broker runtime is not checked out in this environment")
    text = runtime.read_text(encoding="utf-8")
    assert f"MAX_DEVICE_DIRECTORY_DEVICES = {MAX_PRODUCT_VIEW_DEVICES}" in text
    assert (
        BROKER_MAX_DEVICE_CONSTANT
        == "local_agent_broker_durable_runtime.MAX_DEVICE_DIRECTORY_DEVICES"
    )
    assert CANONICAL_DEVICE_STATES == {"paired_offline", "revoked", "credential_expired"}


# --- S14 canonical vocabulary parity --------------------------------------


def test_s14_local_capability_tokens_match_the_canonical_source():
    repo_root = Path(__file__).resolve().parents[3]
    canonical = repo_root / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "local_agent_permissions.py"
    if not canonical.is_file():
        pytest.skip("canonical kagent local permission source is not checked out in this environment")
    text = canonical.read_text(encoding="utf-8")
    assert "class LocalCapability" in text
    for operation, token in CANONICAL_LOCAL_CAPABILITY_FOR_OPERATION.items():
        assert operation in PcAccessOperation
        assert f'"{token}"' in text, f"{token} is not a canonical LocalCapability token"
    # Only the two local file capabilities are referenced; the rest of the
    # product vocabulary is server-side Broker reads, not local capabilities.
    assert set(CANONICAL_LOCAL_CAPABILITY_FOR_OPERATION.values()) == {
        "filesystem.read",
        "filesystem.write",
    }
    assert LOCAL_CAPABILITY_VOCABULARY_OWNER == "kagent.local_agent_permissions.LocalCapability"
