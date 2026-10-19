from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class WorkspaceRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    OWNER = "owner"


class ProductViewKind(str, Enum):
    RUN_STATUS = "run_status"
    OPERATIONAL_ALERTS = "operational_alerts"
    APPROVAL_INBOX = "approval_inbox"
    SUPPLIER_COST = "supplier_cost"
    FINANCE = "finance"
    ORDER_ECONOMICS = "order_economics"
    AUDIT_REFERENCES = "audit_references"


@dataclass(frozen=True, slots=True)
class TrustedWorkspaceMembershipProjection:
    membership_id: str
    workspace_id: str
    principal_ref: str
    role: WorkspaceRole
    authority_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("membership_id", "workspace_id", "principal_ref", "authority_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.role, WorkspaceRole):
            try:
                object.__setattr__(self, "role", WorkspaceRole(self.role))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid workspace role") from exc
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 86_400:
            raise ContractError("workspace membership projection lifetime must be positive and at most 24 hours")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def valid_at(self, now: datetime) -> bool:
        now = _aware(now, "now")
        return self.issued_at <= now < self.expires_at

    def safe_dict(self) -> dict[str, Any]:
        return {
            "membership_id": self.membership_id,
            "workspace_id": self.workspace_id,
            "principal_ref": self.principal_ref,
            "role": self.role.value,
            "authority_ref": self.authority_ref,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "client_asserted": False,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceVisibilityDecision:
    workspace_id: str
    principal_ref: str
    role: WorkspaceRole
    view_kind: ProductViewKind
    allowed: bool
    reason_code: str
    supplier_cost_visible: bool = False
    finance_visible: bool = False
    approval_fields_visible: bool = False
    audit_refs_visible: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "principal_ref", _ref(self.principal_ref, "principal_ref"))
        if not isinstance(self.role, WorkspaceRole) or not isinstance(self.view_kind, ProductViewKind):
            raise ContractError("role and view_kind must use visibility enums")
        if not isinstance(self.allowed, bool):
            raise ContractError("allowed must be boolean")
        object.__setattr__(self, "reason_code", _ref(self.reason_code, "reason_code"))
        for field_name in ("supplier_cost_visible", "finance_visible", "approval_fields_visible", "audit_refs_visible"):
            if not isinstance(getattr(self, field_name), bool):
                raise ContractError(f"{field_name} must be boolean")
        if not self.allowed and any((self.supplier_cost_visible, self.finance_visible, self.approval_fields_visible, self.audit_refs_visible)):
            raise ContractError("denied view cannot expose sensitive visibility flags")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "principal_ref": self.principal_ref,
            "role": self.role.value,
            "view_kind": self.view_kind.value,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "supplier_cost_visible": self.supplier_cost_visible,
            "finance_visible": self.finance_visible,
            "approval_fields_visible": self.approval_fields_visible,
            "audit_refs_visible": self.audit_refs_visible,
            "execution_authority_granted": False,
            "write_authority_granted": False,
            "approval_authority_granted": False,
            "raw_audit_payload_visible": False,
            "credential_values_visible": False,
            "hidden_reasoning_visible": False,
        }


_ALLOWED_BY_ROLE: dict[WorkspaceRole, frozenset[ProductViewKind]] = {
    WorkspaceRole.VIEWER: frozenset({ProductViewKind.RUN_STATUS}),
    WorkspaceRole.OPERATOR: frozenset({ProductViewKind.RUN_STATUS, ProductViewKind.OPERATIONAL_ALERTS}),
    WorkspaceRole.APPROVER: frozenset({
        ProductViewKind.RUN_STATUS,
        ProductViewKind.OPERATIONAL_ALERTS,
        ProductViewKind.APPROVAL_INBOX,
        ProductViewKind.SUPPLIER_COST,
    }),
    WorkspaceRole.OWNER: frozenset(ProductViewKind),
}


class WorkspaceVisibilityPolicy:
    def decide(
        self,
        *,
        membership: TrustedWorkspaceMembershipProjection,
        workspace_id: str,
        view_kind: ProductViewKind,
        now: datetime,
    ) -> WorkspaceVisibilityDecision:
        if not isinstance(membership, TrustedWorkspaceMembershipProjection):
            raise ContractError("trusted workspace membership projection is required")
        workspace_id = _ref(workspace_id, "workspace_id")
        now = _aware(now, "now")
        if not isinstance(view_kind, ProductViewKind):
            try:
                view_kind = ProductViewKind(view_kind)
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid product view kind") from exc
        if membership.workspace_id != workspace_id:
            raise ContractError("workspace membership does not match requested workspace")
        if not membership.valid_at(now):
            return WorkspaceVisibilityDecision(
                workspace_id=workspace_id,
                principal_ref=membership.principal_ref,
                role=membership.role,
                view_kind=view_kind,
                allowed=False,
                reason_code="membership_not_current",
            )
        allowed = view_kind in _ALLOWED_BY_ROLE[membership.role]
        if not allowed:
            return WorkspaceVisibilityDecision(
                workspace_id=workspace_id,
                principal_ref=membership.principal_ref,
                role=membership.role,
                view_kind=view_kind,
                allowed=False,
                reason_code="role_view_denied",
            )
        owner = membership.role is WorkspaceRole.OWNER
        approver_cost = membership.role is WorkspaceRole.APPROVER and view_kind is ProductViewKind.SUPPLIER_COST
        return WorkspaceVisibilityDecision(
            workspace_id=workspace_id,
            principal_ref=membership.principal_ref,
            role=membership.role,
            view_kind=view_kind,
            allowed=True,
            reason_code="trusted_membership_view_allowed",
            supplier_cost_visible=owner or approver_cost,
            finance_visible=owner and view_kind in {ProductViewKind.FINANCE, ProductViewKind.ORDER_ECONOMICS},
            approval_fields_visible=membership.role in {WorkspaceRole.APPROVER, WorkspaceRole.OWNER} and view_kind is ProductViewKind.APPROVAL_INBOX,
            audit_refs_visible=owner and view_kind is ProductViewKind.AUDIT_REFERENCES,
        )


CLIENT_ASSERTED_ROLE_TRUSTED = False
REAL_CONTROL_PLANE_MEMBERSHIP_CALL_CONFIGURED = False
VISIBILITY_DECISION_GRANTS_EXECUTION_AUTHORITY = False
