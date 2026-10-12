"""#4139 canonical account-wide PC device-list and product-view projection.

SOURCE ONLY: the existing Identity DO must resolve an active canonical login,
membership and the *reviewed* product-neutral scope. The existing Broker DO
must provide its private device_directory(account_ref, workspace_ref) result.
No new device store, product grant database, ONLINE authority or HTTP route.

Two different consumers share one Broker directory: the authenticated
account OWNER can view their computers in My Devices, while products see only
the subset permitted by the existing default-OFF ProductPcAccessPolicy.
Neither view grants any P01 READ/WRITE or task dispatch permission.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from collections.abc import Mapping

from .auth_sessions import AuthSessionSnapshot
from .connector_enrollment_owner_policy import require_canonical_connector_owner_session
from .contracts import ControlPlaneContractError
from .local_agent_pc_access import (
    PcAccessOperation,
    ProductPcAccessGrant,
    ProductPcAccessPolicy,
    build_product_device_view,
    NO_DEVICE_BINDING_REASON,
)
from .padiem_connector_enrollment import ConnectorEnrollmentScope

PC_ACCOUNT_DEVICE_MANAGEMENT_CONTRACT = "padiem.canonical-pc-account-devices.v1"
PC_ACCOUNT_DEVICE_ROUTES_MOUNTED = False
PC_ACCOUNT_DEVICE_REVOCATION_WIRED = False
PC_ACCOUNT_DEVICE_READ_DEPLOYED = False
PC_ACCOUNT_CREATES_PRODUCT_GRANTS = False
PC_ACCOUNT_DECIDES_ONLINE = False

# Private projection discriminator used only to reuse the already-reviewed
# closed Broker directory parser. This does NOT persist an operator entitlement
# or authorize any product. The account OWNER is independently checked first.
_PRIVATE_OWNER_PROJECTION = "padiem-account-device-view"


def _denied(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "available": False,
        "reason": reason,
        "devices": [],
        "device_count": 0,
        "owner_scoped": False,
        "directory_verified": False,
        "online_decided_here": False,
        "dispatch_authorized": False,
        "grants_read": False,
        "grants_write": False,
    }


def _verified_owner_scope(
    *, session: Any, membership_role: Any, scope: Any, now: datetime,
) -> bool:
    # The injection site MUST retrieve all three from the canonical Identity
    # DO; never reuse account, scope, role or session fields from client JSON.
    try:
        require_canonical_connector_owner_session(
            session=session, membership_role=membership_role, now=now,
        )
    except (ControlPlaneContractError, TypeError, ValueError):
        return False
    return (
        isinstance(session, AuthSessionSnapshot)
        and isinstance(scope, ConnectorEnrollmentScope)
        and scope.owner_subject_id == session.subject.subject_id
        and scope.product_scoped is False
    )


def _directory_matches_scope(result: Any, scope: ConnectorEnrollmentScope) -> bool:
    """Reject a mixed-in/forged device even when the Broker envelope attests true.

    The Broker authority scopes the read server-side; this is defense-in-depth
    at the common account/projection boundary. Never partially filter rows.
    """
    if not isinstance(result, Mapping):
        return False
    if result.get("ok") is not True:
        return False
    if result.get("available") is False:
        return (
            set(result) == {"ok", "available", "reason"}
            and result.get("reason") == NO_DEVICE_BINDING_REASON
        )
    if result.get("available") is not True or result.get("owner_scoped") is not True:
        return False
    devices = result.get("devices")
    if not isinstance(devices, (list, tuple)):
        return False
    for facts in devices:
        if not isinstance(facts, Mapping):
            return False
        binding = facts.get("binding")
        if (
            not isinstance(binding, Mapping)
            or binding.get("account_ref") != scope.account_ref
            or binding.get("workspace_ref") != scope.workspace_ref
        ):
            return False
    return True


def account_device_view(
    *, session: AuthSessionSnapshot, membership_role: Any,
    scope: ConnectorEnrollmentScope, directory_result: Any,
    now: datetime,
) -> dict[str, Any]:
    """Account-level My Devices, read-only, without product entitlement.

    This is an OWNER read, *not* an implicit device.list grant to B66 or Claw.
    It reuses the strict product-neutral Broker projection parser with a
    private, ephemeral view-only policy AFTER canonical owner verification.
    The private policy is never stored in ProductPcAccessPolicy configuration,
    never passed to a product, and grants nothing beyond this projection.
    """
    if not _verified_owner_scope(
        session=session, membership_role=membership_role, scope=scope, now=now,
    ):
        return _denied("canonical_owner_scope_required")
    if not _directory_matches_scope(directory_result, scope):
        return _denied("canonical_broker_directory_unverified")

    ephemeral_parser_policy = ProductPcAccessPolicy(grants=(
        ProductPcAccessGrant(
            product_id=_PRIVATE_OWNER_PROJECTION,
            operations=frozenset({PcAccessOperation.DEVICE_LIST}),
            workspace_ref=scope.workspace_ref,
        ),
    ))
    view = build_product_device_view(
        policy=ephemeral_parser_policy,
        product_id=_PRIVATE_OWNER_PROJECTION,
        directory_result=directory_result,
        workspace_ref=scope.workspace_ref,
    )
    if not view["directory_verified"]:
        return _denied("canonical_broker_directory_unverified")

    # Strict output keys: no account/tenant/workspace/subject or broker refs,
    # no credential/session tokens, no product permissions, no ONLINE claims.
    devices = [{
        "device_id": row["device_id"],
        "canonical_state": row["canonical_state"],
        "has_session": row["has_session"],
        "heartbeat_present": row["heartbeat_present"],
        "online_decided_here": False,
    } for row in view["devices"]]
    return {
        "ok": True,
        "available": bool(view["available"]),
        "reason": view["reason"],
        "devices": devices,
        "device_count": len(devices),
        "owner_scoped": True,
        "directory_verified": True,
        "online_decided_here": False,
        "dispatch_authorized": False,
        "grants_read": False,
        "grants_write": False,
    }


def product_device_view_for_owner(
    *, session: AuthSessionSnapshot, membership_role: Any,
    scope: ConnectorEnrollmentScope, directory_result: Any,
    policy: ProductPcAccessPolicy, product_id: str, now: datetime,
) -> dict[str, Any]:
    """Product view on the SAME canonical directory, with separate grants.

    A real caller must validate the signed-in product user's canonical
    linkage before passing session and product ID to this source contract.
    Until those login bridges are reviewed, only B54 owner eligibility exists.
    """
    if not _verified_owner_scope(
        session=session, membership_role=membership_role, scope=scope, now=now,
    ):
        return _denied("canonical_owner_scope_required")
    if not isinstance(policy, ProductPcAccessPolicy):
        return _denied("product_pc_policy_required")
    if not _directory_matches_scope(directory_result, scope):
        return _denied("canonical_broker_directory_unverified")
    return build_product_device_view(
        policy=policy,
        product_id=product_id,
        directory_result=directory_result,
        workspace_ref=scope.workspace_ref,
    )
