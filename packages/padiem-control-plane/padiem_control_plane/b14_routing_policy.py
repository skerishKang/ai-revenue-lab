from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import CanonicalSubjectRef, ControlPlaneContractError
from .entitlements import EntitlementSnapshot

B14_ROUTING_POLICY_VERSION_V1 = "b14.routing.entitlement.v1"
B14_EXTERNAL_ROUTE_GRANT_V1 = "b14.route.external"
_B14_ROUTING_GRANT_PREFIX = "b14."
_B14_ROUTING_GRANTS_V1 = frozenset({B14_EXTERNAL_ROUTE_GRANT_V1})


def _aware_now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_b14_routing_policy",
            "now must be timezone-aware",
        )
    return value


@dataclass(frozen=True, slots=True)
class TrustedB14RoutingPolicyV1:
    """Narrow Control-Plane-produced routing policy consumed by Business 14.

    This is not an account, subscription, payment, credit, or product-plan
    record.  It carries only routing authority that has already been resolved
    by trusted Control Plane state for one exact product subject.
    """

    snapshot_id: str
    product_id: str
    subject: CanonicalSubjectRef
    revision: str
    issued_at: datetime
    expires_at: datetime
    external_routes_allowed: bool
    policy_version: str = B14_ROUTING_POLICY_VERSION_V1

    def __post_init__(self) -> None:
        if self.policy_version != B14_ROUTING_POLICY_VERSION_V1:
            raise ControlPlaneContractError(
                "invalid_b14_routing_policy",
                "unsupported B14 routing policy version",
            )
        if not isinstance(self.subject, CanonicalSubjectRef):
            raise ControlPlaneContractError(
                "invalid_b14_routing_policy",
                "subject must be CanonicalSubjectRef",
            )
        if not isinstance(self.external_routes_allowed, bool):
            raise ControlPlaneContractError(
                "invalid_b14_routing_policy",
                "external_routes_allowed must be bool",
            )
        _aware_now(self.issued_at)
        _aware_now(self.expires_at)
        if self.expires_at <= self.issued_at:
            raise ControlPlaneContractError(
                "invalid_b14_routing_policy",
                "expires_at must be after issued_at",
            )

    def to_policy_dict(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "snapshot_id": self.snapshot_id,
            "product_id": self.product_id,
            "subject": self.subject.to_public_dict(),
            "revision": self.revision,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "external_routes_allowed": self.external_routes_allowed,
        }


def trusted_b14_routing_policy_v1_from_entitlement(
    snapshot: EntitlementSnapshot,
    *,
    expected_product_id: str,
    expected_subject: CanonicalSubjectRef,
    now: datetime,
) -> TrustedB14RoutingPolicyV1:
    """Project one trusted entitlement snapshot into B14 routing policy v1.

    V1 intentionally freezes only one machine grant:

        ``b14.route.external``

    Missing grant means deny.  Model tiers, cost classes, product plan names and
    capability entitlements are deliberately not part of v1 and must be added
    only through a later versioned cross-axis contract.
    """

    if not isinstance(snapshot, EntitlementSnapshot):
        raise ControlPlaneContractError(
            "invalid_b14_routing_policy",
            "snapshot must be EntitlementSnapshot",
        )
    if not isinstance(expected_product_id, str) or not expected_product_id:
        raise ControlPlaneContractError(
            "invalid_b14_routing_policy",
            "expected_product_id must be a non-empty product identifier",
        )
    if not isinstance(expected_subject, CanonicalSubjectRef):
        raise ControlPlaneContractError(
            "invalid_b14_routing_policy",
            "expected_subject must be CanonicalSubjectRef",
        )

    checked_now = _aware_now(now)
    if snapshot.product_id != expected_product_id:
        raise ControlPlaneContractError(
            "b14_routing_product_mismatch",
            "entitlement snapshot product does not match the trusted B14 request context",
        )
    if snapshot.subject != expected_subject:
        raise ControlPlaneContractError(
            "b14_routing_subject_mismatch",
            "entitlement snapshot subject does not match the trusted B14 request context",
        )
    if checked_now < snapshot.issued_at:
        raise ControlPlaneContractError(
            "b14_routing_snapshot_not_yet_valid",
            "entitlement snapshot is not yet valid",
        )
    if checked_now >= snapshot.expires_at:
        raise ControlPlaneContractError(
            "b14_routing_snapshot_expired",
            "entitlement snapshot has expired",
        )

    unknown_b14_keys = tuple(
        grant.key
        for grant in snapshot.grants
        if grant.key.startswith(_B14_ROUTING_GRANT_PREFIX)
        and grant.key not in _B14_ROUTING_GRANTS_V1
    )
    if unknown_b14_keys:
        raise ControlPlaneContractError(
            "unsupported_b14_routing_entitlement",
            "entitlement snapshot contains a B14 routing grant not supported by policy v1",
        )

    external_grant = snapshot.resolve(B14_EXTERNAL_ROUTE_GRANT_V1)
    if external_grant is not None and external_grant.limit is not None:
        raise ControlPlaneContractError(
            "invalid_b14_routing_entitlement",
            "b14.route.external is a boolean grant and cannot carry a limit",
        )

    return TrustedB14RoutingPolicyV1(
        snapshot_id=snapshot.snapshot_id,
        product_id=snapshot.product_id,
        subject=snapshot.subject,
        revision=snapshot.revision,
        issued_at=snapshot.issued_at,
        expires_at=snapshot.expires_at,
        external_routes_allowed=(
            external_grant.allowed if external_grant is not None else False
        ),
    )
