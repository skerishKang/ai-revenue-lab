"""Canonical tenant entity and subject-membership contracts for #2176 S2.

The Control Plane identity authority is the sole owner of tenant truth:

* ``tenant_id`` is server-minted only — never derived from, defaulted to, or
  aliased to a product/app id, a subject id, or connector workspace/account
  references (#2157, #2173);
* a membership is the canonical relation from a canonical subject to a
  tenant, with deterministic ACTIVE/INACTIVE state;
* a payload that asserts its own tenant identity is structurally invalid:
  these contracts accept only already-minted bounded identifiers;
* an alias of tenant to product or subject is rejected at contract level,
  matching the auth-session guards #2159 locked.

This module is pure contract: no storage, no network, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TENANT_ID_PREFIX = "tenant_"
_TENANT_ID_RE = re.compile(r"^tenant_[0-9a-f]{32}$")


class ControlPlaneTenantError(ValueError):
    """Fail-closed canonical-tenant contract violation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CanonicalTenantState(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TenantMembershipState(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ControlPlaneTenantError(
            "invalid_canonical_tenant",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _server_minted_tenant_id(value: object) -> str:
    if not isinstance(value, str) or not _TENANT_ID_RE.fullmatch(value):
        raise ControlPlaneTenantError(
            "invalid_canonical_tenant",
            "tenant_id must be a server-minted bounded identifier",
        )
    return value


def _aware(name: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ControlPlaneTenantError(
            "invalid_canonical_tenant",
            f"{name} must be timezone-aware",
        )
    return value


@dataclass(frozen=True, slots=True)
class CanonicalTenant:
    """Server-minted canonical tenancy entity. No derivation source exists."""

    tenant_id: str
    state: CanonicalTenantState = CanonicalTenantState.ACTIVE
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _server_minted_tenant_id(self.tenant_id))
        if not isinstance(self.state, CanonicalTenantState):
            raise ControlPlaneTenantError(
                "invalid_canonical_tenant", "state must be CanonicalTenantState"
            )
        if self.created_at is not None:
            object.__setattr__(self, "created_at", _aware("created_at", self.created_at))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "state": self.state.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass(frozen=True, slots=True)
class TenantMembership:
    """Canonical subject-to-tenant membership relation.

    ``tenant_id`` must already exist as a canonical tenant and can never
    alias the subject it links; product aliasing is enforced where the
    product is known (auth-session minting, #2159 guards).
    """

    tenant_id: str
    canonical_subject_id: str
    state: TenantMembershipState = TenantMembershipState.ACTIVE
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _server_minted_tenant_id(self.tenant_id))
        object.__setattr__(
            self, "canonical_subject_id", _identifier("canonical_subject_id", self.canonical_subject_id)
        )
        if self.tenant_id == self.canonical_subject_id:
            raise ControlPlaneTenantError(
                "invalid_canonical_tenant",
                "tenant_id must be distinct from the subject id",
            )
        if not isinstance(self.state, TenantMembershipState):
            raise ControlPlaneTenantError(
                "invalid_canonical_tenant", "state must be TenantMembershipState"
            )
        if self.created_at is not None:
            object.__setattr__(self, "created_at", _aware("created_at", self.created_at))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "canonical_subject_id": self.canonical_subject_id,
            "state": self.state.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


TENANT_ID_PREFIX = _TENANT_ID_PREFIX
TENANT_ID_CHARS = len(_TENANT_ID_PREFIX) + 32
CANONICAL_TENANT_CONTRACT_SOURCE = True
TENANT_SERVER_MINTED_ONLY = True
REQUEST_ASSERTED_TENANT_AUTHORITY = False
DEFAULT_TENANT = False
