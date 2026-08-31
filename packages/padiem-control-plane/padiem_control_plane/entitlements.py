from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from .contracts import CanonicalSubjectRef, ControlPlaneContractError

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_ENTITLEMENT_GRANTS = 64


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_entitlement",
            f"{name} must be a non-empty safe identifier",
        )
    return value


def _aware_datetime(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_entitlement",
            f"{name} must be timezone-aware",
        )
    return value


@dataclass(frozen=True, slots=True)
class EntitlementGrant:
    """One machine-enforced entitlement decision.

    Product plan names are intentionally absent.  A product policy may map its
    own plan to these machine grants, but consumers receive only the resolved
    server-trusted entitlement result.
    """

    key: str
    allowed: bool
    limit: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _identifier("entitlement key", self.key))
        if not isinstance(self.allowed, bool):
            raise ControlPlaneContractError(
                "invalid_entitlement",
                "allowed must be bool",
            )
        if self.limit is not None:
            if (
                isinstance(self.limit, bool)
                or not isinstance(self.limit, int)
                or self.limit < 1
            ):
                raise ControlPlaneContractError(
                    "invalid_entitlement",
                    "limit must be a positive integer or None",
                )
            if not self.allowed:
                raise ControlPlaneContractError(
                    "invalid_entitlement",
                    "a denied entitlement cannot carry a positive limit",
                )

    def to_policy_dict(self) -> dict[str, str | bool | int | None]:
        return {
            "key": self.key,
            "allowed": self.allowed,
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class EntitlementSnapshot:
    """Bounded server-trusted entitlement snapshot for one product subject.

    This value is an execution-policy input, not a browser assertion and not a
    subscription/payment record.  Absence of a grant does not imply allow.
    """

    snapshot_id: str
    product_id: str
    subject: CanonicalSubjectRef
    revision: str
    issued_at: datetime
    expires_at: datetime
    grants: tuple[EntitlementGrant, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _identifier("snapshot_id", self.snapshot_id))
        object.__setattr__(self, "product_id", _identifier("product_id", self.product_id))
        object.__setattr__(self, "revision", _identifier("revision", self.revision))
        if not isinstance(self.subject, CanonicalSubjectRef):
            raise ControlPlaneContractError(
                "invalid_entitlement",
                "subject must be CanonicalSubjectRef",
            )
        object.__setattr__(self, "issued_at", _aware_datetime("issued_at", self.issued_at))
        object.__setattr__(self, "expires_at", _aware_datetime("expires_at", self.expires_at))
        if self.expires_at <= self.issued_at:
            raise ControlPlaneContractError(
                "invalid_entitlement",
                "expires_at must be after issued_at",
            )

        grants = tuple(self.grants)
        if len(grants) > MAX_ENTITLEMENT_GRANTS:
            raise ControlPlaneContractError(
                "invalid_entitlement",
                "entitlement grant count exceeds the bounded limit",
            )
        if any(not isinstance(grant, EntitlementGrant) for grant in grants):
            raise ControlPlaneContractError(
                "invalid_entitlement",
                "grants must contain only EntitlementGrant values",
            )
        keys = tuple(grant.key for grant in grants)
        if len(keys) != len(set(keys)):
            raise ControlPlaneContractError(
                "duplicate_entitlement",
                "entitlement keys must be unique within one snapshot",
            )
        object.__setattr__(self, "grants", grants)

    def resolve(self, key: str) -> EntitlementGrant | None:
        safe_key = _identifier("entitlement key", key)
        return next((grant for grant in self.grants if grant.key == safe_key), None)

    def allows(self, key: str) -> bool:
        grant = self.resolve(key)
        return grant.allowed if grant is not None else False

    def to_policy_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "product_id": self.product_id,
            "subject": self.subject.to_public_dict(),
            "revision": self.revision,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "grants": [grant.to_policy_dict() for grant in self.grants],
        }
