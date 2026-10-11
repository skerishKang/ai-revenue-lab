"""Pure Admin contracts for versioned Padiem routing-profile changes.

This module is a source-only, stdlib-only contract layer. It does not perform
I/O, resolve credentials, call B14, persist revisions, or authorize a browser.
The trusted host supplies the operator grant and the B14 catalog projection;
these value objects only validate and safely project those facts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import re

from .contracts import CanonicalSubjectRef, ControlPlaneContractError
from .product_tier_routes import (
    MAX_HOLD_MODEL_ID,
    PRODUCT_TIER_POLICY_VERSION,
    RETIRED_PRODUCT_MODEL_IDS,
    ProductTierLabel,
)


_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")
_FORBIDDEN_ROUTE_TOKENS = ("auto", "fallback")


class PadiemRoutingProfileStatus(str, Enum):
    STAGED = "staged"
    VALID = "valid"
    INVALID = "invalid"
    APPLIED = "applied"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    REVISION_CONFLICT = "revision_conflict"
    ROUTE_UNREGISTERED = "route_unregistered"
    ROUTE_RETIRED = "route_retired"
    ROUTE_DISABLED = "route_disabled"
    ROUTE_HOLD = "route_hold"
    CREDENTIAL_NOT_READY = "credential_not_ready"
    OPERATOR_NOT_AUTHORIZED = "operator_not_authorized"


class PadiemRoutingProfileRouteState(str, Enum):
    REGISTERED = "registered"
    UNREGISTERED = "unregistered"
    RETIRED = "retired"
    DISABLED = "disabled"
    HOLD = "hold"


class PadiemRoutingProfileCredentialState(str, Enum):
    NOT_REQUIRED = "not_required"
    READY = "ready"
    NOT_READY = "not_ready"
    EXPIRED = "expired"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class PadiemRoutingProfileOperatorAction(str, Enum):
    STAGE = "stage"
    APPLY = "apply"
    ROLLBACK = "rollback"


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileCatalogRoute:
    """Trusted, safe B14 route projection used to build a tier selection."""

    catalog_ref: str
    route_id: str
    provider_id: str
    model_id: str
    state: PadiemRoutingProfileRouteState
    credential_state: PadiemRoutingProfileCredentialState
    retired: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "catalog_ref", _ref("catalog_ref", self.catalog_ref))
        for name in ("route_id", "provider_id", "model_id"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        if any(token in self.route_id.lower() for token in _FORBIDDEN_ROUTE_TOKENS):
            raise _error("invalid_padiem_profile_route", "catalog route cannot be auto or fallback")
        if not isinstance(self.state, PadiemRoutingProfileRouteState):
            raise _error("invalid_padiem_profile_route", "catalog route state is invalid")
        if not isinstance(self.credential_state, PadiemRoutingProfileCredentialState):
            raise _error("invalid_padiem_profile_credential", "catalog credential state is invalid")
        if not isinstance(self.retired, bool):
            raise _error("invalid_padiem_profile_route", "catalog retired flag is invalid")
        if self.retired and self.state is not PadiemRoutingProfileRouteState.RETIRED:
            raise _error("invalid_padiem_profile_route", "retired catalog route must be retired")

    def safe_dict(self) -> dict[str, object]:
        return {
            "catalog_ref": self.catalog_ref,
            "route_id": self.route_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "state": self.state.value,
            "credential_state": self.credential_state.value,
            "retired": self.retired,
        }


PADIEM_ROUTING_PROFILE_STATUS_VALUES = frozenset(PadiemRoutingProfileStatus)
RAW_SECRET_IN_CONTRACT = False
ARBITRARY_ROUTE_ID_FREE_TEXT = False
AUTO_ROUTING = False
SILENT_FALLBACK = False
MAX_HOLD_FAIL_CLOSED = True
B14_EXECUTION_AUTHORITY_MOVES = False
PADIEM_PROFILE_SOT_REUSED = True


def _error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


def _ref(name: str, value: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise _error("invalid_padiem_profile_reference", f"{name} must be a bounded reference")
    return value


def _code(name: str, value: str) -> str:
    if not isinstance(value, str) or not _CODE_RE.fullmatch(value):
        raise _error("invalid_padiem_profile_code", f"{name} must be a bounded machine code")
    return value


def _positive_revision(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error("invalid_padiem_profile_revision", f"{name} must be a positive integer")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _error("invalid_padiem_profile_timestamp", f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _tuple_of(value: object, item_type: type, name: str, maximum: int) -> tuple:
    if not isinstance(value, tuple) or len(value) > maximum or any(
        not isinstance(item, item_type) for item in value
    ):
        raise _error("invalid_padiem_profile_contract", f"{name} must be a bounded tuple")
    return value


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileOperatorGrant:
    """Trusted operator capability projection; no tenant or entitlement authority."""

    grant_ref: str
    operator_subject: CanonicalSubjectRef
    authority_ref: str
    allowed_actions: tuple[PadiemRoutingProfileOperatorAction, ...]
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_ref", _ref("grant_ref", self.grant_ref))
        object.__setattr__(self, "authority_ref", _ref("authority_ref", self.authority_ref))
        if not isinstance(self.operator_subject, CanonicalSubjectRef):
            raise _error("invalid_padiem_profile_operator", "operator_subject must be canonical")
        actions = _tuple_of(self.allowed_actions, PadiemRoutingProfileOperatorAction, "allowed_actions", 3)
        if not actions or len(set(actions)) != len(actions):
            raise _error("invalid_padiem_profile_operator", "allowed_actions must be unique and non-empty")
        object.__setattr__(self, "issued_at", _aware("issued_at", self.issued_at))
        object.__setattr__(self, "expires_at", _aware("expires_at", self.expires_at))
        if self.expires_at <= self.issued_at:
            raise _error("invalid_padiem_profile_operator", "expires_at must follow issued_at")

    def allows(self, action: PadiemRoutingProfileOperatorAction) -> bool:
        return action in self.allowed_actions

    def is_active(self, *, now: datetime) -> bool:
        checked = _aware("now", now)
        return self.issued_at <= checked < self.expires_at

    def safe_dict(self) -> dict[str, object]:
        return {
            "grant_ref": self.grant_ref,
            "operator_subject": self.operator_subject.to_public_dict(),
            "authority_ref": self.authority_ref,
            "allowed_actions": [item.value for item in self.allowed_actions],
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "tenant_authority": False,
            "entitlement_authority": False,
        }


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileTierSelection:
    """One tier selection projected from the trusted B14 catalog boundary."""

    tier: ProductTierLabel
    route_id: str | None
    provider_id: str | None
    model_id: str | None
    route_state: PadiemRoutingProfileRouteState
    credential_state: PadiemRoutingProfileCredentialState
    reason_code: str | None = None
    catalog_route_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tier, ProductTierLabel):
            raise _error("invalid_padiem_profile_tier", "tier must be ProductTierLabel")
        if not isinstance(self.route_state, PadiemRoutingProfileRouteState):
            raise _error("invalid_padiem_profile_route", "route_state is invalid")
        if not isinstance(self.credential_state, PadiemRoutingProfileCredentialState):
            raise _error("invalid_padiem_profile_credential", "credential_state is invalid")
        for name in ("route_id", "provider_id", "model_id"):
            value = getattr(self, name)
            if value is not None:
                _ref(name, value)
        if self.route_id is not None and any(token in self.route_id.lower() for token in _FORBIDDEN_ROUTE_TOKENS):
            raise _error("invalid_padiem_profile_route", "route_id cannot select auto or fallback")
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", _code("reason_code", self.reason_code))
        if self.route_state is PadiemRoutingProfileRouteState.REGISTERED:
            if not self.route_id or not self.provider_id or not self.model_id:
                raise _error("invalid_padiem_profile_route", "registered route requires explicit route identity")
            if self.catalog_route_ref is None:
                raise _error("invalid_padiem_profile_route", "registered route requires trusted catalog reference")
        elif self.catalog_route_ref is not None:
            object.__setattr__(self, "catalog_route_ref", _ref("catalog_route_ref", self.catalog_route_ref))
        elif self.route_state is PadiemRoutingProfileRouteState.HOLD:
            if self.tier is not ProductTierLabel.MAX:
                raise _error("padiem_profile_route_hold", "only Padiem Max may be HOLD")
            if self.provider_id is not None:
                raise _error("padiem_profile_route_hold", "HOLD route cannot name a provider")
            if self.model_id not in (None, MAX_HOLD_MODEL_ID):
                raise _error("padiem_profile_route_hold", "Max HOLD must use the hold sentinel")
        elif not self.reason_code:
            raise _error("invalid_padiem_profile_route", "non-registered route requires a reason")

    def safe_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "route_id": self.route_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "route_state": self.route_state.value,
            "credential_state": self.credential_state.value,
            "reason_code": self.reason_code,
            "catalog_route_ref": self.catalog_route_ref,
        }

    @classmethod
    def from_catalog(
        cls,
        *,
        tier: ProductTierLabel,
        route: PadiemRoutingProfileCatalogRoute,
        reason_code: str | None = None,
    ) -> "PadiemRoutingProfileTierSelection":
        if not isinstance(route, PadiemRoutingProfileCatalogRoute):
            raise _error("invalid_padiem_profile_route", "trusted catalog route is required")
        return cls(
            tier=tier,
            route_id=route.route_id,
            provider_id=route.provider_id,
            model_id=route.model_id,
            route_state=route.state,
            credential_state=route.credential_state,
            reason_code=reason_code,
            catalog_route_ref=route.catalog_ref,
        )


def _validate_selections(selections: tuple[PadiemRoutingProfileTierSelection, ...]) -> None:
    selections = _tuple_of(selections, PadiemRoutingProfileTierSelection, "selections", 3)
    by_tier = {item.tier: item for item in selections}
    if len(by_tier) != 3 or set(by_tier) != set(ProductTierLabel):
        raise _error("invalid_padiem_profile_tiers", "exactly Plus, Pro, and Max selections are required")
    for tier in (ProductTierLabel.PLUS, ProductTierLabel.PRO):
        item = by_tier[tier]
        if item.route_state is not PadiemRoutingProfileRouteState.REGISTERED:
            raise _status_error(item.route_state)
        if item.credential_state not in {
            PadiemRoutingProfileCredentialState.NOT_REQUIRED,
            PadiemRoutingProfileCredentialState.READY,
        }:
            raise _error("padiem_profile_credential_not_ready", PadiemRoutingProfileStatus.CREDENTIAL_NOT_READY.value)
        if item.model_id in RETIRED_PRODUCT_MODEL_IDS:
            raise _error("padiem_profile_route_retired", PadiemRoutingProfileStatus.ROUTE_RETIRED.value)
    max_item = by_tier[ProductTierLabel.MAX]
    if max_item.route_state is not PadiemRoutingProfileRouteState.HOLD:
        raise _error("padiem_profile_max_hold", PadiemRoutingProfileStatus.ROUTE_HOLD.value)


def _status_error(state: PadiemRoutingProfileRouteState) -> ControlPlaneContractError:
    mapping = {
        PadiemRoutingProfileRouteState.UNREGISTERED: PadiemRoutingProfileStatus.ROUTE_UNREGISTERED,
        PadiemRoutingProfileRouteState.RETIRED: PadiemRoutingProfileStatus.ROUTE_RETIRED,
        PadiemRoutingProfileRouteState.DISABLED: PadiemRoutingProfileStatus.ROUTE_DISABLED,
        PadiemRoutingProfileRouteState.HOLD: PadiemRoutingProfileStatus.ROUTE_HOLD,
    }
    status = mapping[state]
    return _error(f"padiem_profile_{status.value}", status.value)


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileRevision:
    profile_id: str
    revision: int
    policy_version: str
    selections: tuple[PadiemRoutingProfileTierSelection, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _ref("profile_id", self.profile_id))
        object.__setattr__(self, "revision", _positive_revision("revision", self.revision))
        if self.policy_version != PRODUCT_TIER_POLICY_VERSION:
            raise _error("invalid_padiem_profile_policy", "unsupported Padiem profile policy version")
        object.__setattr__(self, "created_at", _aware("created_at", self.created_at))
        _validate_selections(self.selections)

    def safe_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "revision": self.revision,
            "policy_version": self.policy_version,
            "selections": [item.safe_dict() for item in self.selections],
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileTierChange:
    tier: ProductTierLabel
    before_route_id: str | None
    after_route_id: str | None
    before_state: PadiemRoutingProfileRouteState
    after_state: PadiemRoutingProfileRouteState
    before_model_id: str | None = None
    after_model_id: str | None = None
    before_credential_state: PadiemRoutingProfileCredentialState = PadiemRoutingProfileCredentialState.UNKNOWN
    after_credential_state: PadiemRoutingProfileCredentialState = PadiemRoutingProfileCredentialState.UNKNOWN

    def __post_init__(self) -> None:
        if not isinstance(self.tier, ProductTierLabel):
            raise _error("invalid_padiem_profile_diff", "tier is invalid")
        for name in ("before_route_id", "after_route_id"):
            value = getattr(self, name)
            if value is not None:
                _ref(name, value)
        if not isinstance(self.before_state, PadiemRoutingProfileRouteState) or not isinstance(
            self.after_state, PadiemRoutingProfileRouteState
        ):
            raise _error("invalid_padiem_profile_diff", "route states are invalid")
        for name in ("before_model_id", "after_model_id"):
            value = getattr(self, name)
            if value is not None:
                _ref(name, value)
        if not isinstance(self.before_credential_state, PadiemRoutingProfileCredentialState) or not isinstance(
            self.after_credential_state, PadiemRoutingProfileCredentialState
        ):
            raise _error("invalid_padiem_profile_diff", "credential states are invalid")

    def safe_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "before_route_id": self.before_route_id,
            "after_route_id": self.after_route_id,
            "before_state": self.before_state.value,
            "after_state": self.after_state.value,
            "before_model_id": self.before_model_id,
            "after_model_id": self.after_model_id,
            "before_credential_state": self.before_credential_state.value,
            "after_credential_state": self.after_credential_state.value,
        }


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileDiff:
    profile_id: str
    from_revision: int
    to_revision: int
    changes: tuple[PadiemRoutingProfileTierChange, ...]
    status: PadiemRoutingProfileStatus = PadiemRoutingProfileStatus.VALID

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _ref("profile_id", self.profile_id))
        object.__setattr__(self, "from_revision", _positive_revision("from_revision", self.from_revision))
        object.__setattr__(self, "to_revision", _positive_revision("to_revision", self.to_revision))
        if self.to_revision <= self.from_revision:
            raise _error("invalid_padiem_profile_diff", "to_revision must follow from_revision")
        if not isinstance(self.status, PadiemRoutingProfileStatus):
            raise _error("invalid_padiem_profile_diff", "status is invalid")
        object.__setattr__(self, "changes", _tuple_of(self.changes, PadiemRoutingProfileTierChange, "changes", 3))

    def safe_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "from_revision": self.from_revision,
            "to_revision": self.to_revision,
            "changes": [item.safe_dict() for item in self.changes],
            "status": self.status.value,
        }


def build_padiem_routing_profile_diff(
    before: PadiemRoutingProfileRevision,
    after: PadiemRoutingProfileRevision,
) -> PadiemRoutingProfileDiff:
    if before.profile_id != after.profile_id:
        raise _error("padiem_profile_mismatch", "profile revisions must have the same profile_id")
    old = {item.tier: item for item in before.selections}
    new = {item.tier: item for item in after.selections}
    changes = tuple(
        PadiemRoutingProfileTierChange(
            tier=tier,
            before_route_id=old[tier].route_id,
            after_route_id=new[tier].route_id,
            before_state=old[tier].route_state,
            after_state=new[tier].route_state,
            before_model_id=old[tier].model_id,
            after_model_id=new[tier].model_id,
            before_credential_state=old[tier].credential_state,
            after_credential_state=new[tier].credential_state,
        )
        for tier in ProductTierLabel
        if old[tier] != new[tier]
    )
    return PadiemRoutingProfileDiff(
        profile_id=before.profile_id,
        from_revision=before.revision,
        to_revision=after.revision,
        changes=changes,
    )


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileStagedChange:
    stage_ref: str
    profile_id: str
    base_revision: int
    proposed_revision: int
    selections: tuple[PadiemRoutingProfileTierSelection, ...]
    diff: PadiemRoutingProfileDiff
    operator_grant: PadiemRoutingProfileOperatorGrant
    staged_at: datetime
    expires_at: datetime
    status: PadiemRoutingProfileStatus = PadiemRoutingProfileStatus.STAGED

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_ref", _ref("stage_ref", self.stage_ref))
        object.__setattr__(self, "profile_id", _ref("profile_id", self.profile_id))
        object.__setattr__(self, "base_revision", _positive_revision("base_revision", self.base_revision))
        object.__setattr__(self, "proposed_revision", _positive_revision("proposed_revision", self.proposed_revision))
        if self.proposed_revision != self.base_revision + 1:
            raise _error("invalid_padiem_profile_revision", "proposed_revision must increment exactly by one")
        _validate_selections(_tuple_of(self.selections, PadiemRoutingProfileTierSelection, "selections", 3))
        if not isinstance(self.diff, PadiemRoutingProfileDiff) or self.diff.profile_id != self.profile_id:
            raise _error("invalid_padiem_profile_diff", "staged diff does not match profile")
        if (
            self.diff.from_revision != self.base_revision
            or self.diff.to_revision != self.proposed_revision
        ):
            raise _error("invalid_padiem_profile_diff", "staged diff revisions do not match change")
        if not isinstance(self.operator_grant, PadiemRoutingProfileOperatorGrant):
            raise _error("invalid_padiem_profile_operator", "operator_grant is required")
        object.__setattr__(self, "staged_at", _aware("staged_at", self.staged_at))
        object.__setattr__(self, "expires_at", _aware("expires_at", self.expires_at))
        if self.expires_at <= self.staged_at:
            raise _error("invalid_padiem_profile_stage", "expires_at must follow staged_at")
        if self.status not in {
            PadiemRoutingProfileStatus.STAGED,
            PadiemRoutingProfileStatus.VALID,
            PadiemRoutingProfileStatus.INVALID,
        }:
            raise _error("invalid_padiem_profile_stage", "staged change status is invalid")

    def safe_dict(self) -> dict[str, object]:
        return {
            "stage_ref": self.stage_ref,
            "profile_id": self.profile_id,
            "base_revision": self.base_revision,
            "proposed_revision": self.proposed_revision,
            "selections": [item.safe_dict() for item in self.selections],
            "diff": self.diff.safe_dict(),
            "operator_grant": self.operator_grant.safe_dict(),
            "staged_at": self.staged_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status.value,
        }


def validate_padiem_routing_profile_stage(
    change: PadiemRoutingProfileStagedChange,
    *,
    current_revision: int,
    now: datetime,
) -> PadiemRoutingProfileStagedChange:
    if not isinstance(change, PadiemRoutingProfileStagedChange):
        raise _error("invalid_padiem_profile_stage", "staged change is required")
    if change.base_revision != _positive_revision("current_revision", current_revision):
        raise _error("padiem_profile_revision_conflict", PadiemRoutingProfileStatus.REVISION_CONFLICT.value)
    checked = _aware("now", now)
    if checked >= change.expires_at:
        raise _error("padiem_profile_stage_expired", PadiemRoutingProfileStatus.INVALID.value)
    if not change.operator_grant.is_active(now=checked) or not change.operator_grant.allows(
        PadiemRoutingProfileOperatorAction.STAGE
    ):
        raise _error("padiem_profile_operator_not_authorized", PadiemRoutingProfileStatus.OPERATOR_NOT_AUTHORIZED.value)
    _validate_selections(change.selections)
    return replace(change, status=PadiemRoutingProfileStatus.VALID)


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileApplyReceipt:
    receipt_ref: str
    profile_id: str
    from_revision: int
    applied_revision: int | None
    status: PadiemRoutingProfileStatus
    audit_ref: str
    confirmation_ref: str
    rollback_anchor_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_ref", _ref("receipt_ref", self.receipt_ref))
        object.__setattr__(self, "profile_id", _ref("profile_id", self.profile_id))
        object.__setattr__(self, "from_revision", _positive_revision("from_revision", self.from_revision))
        if self.applied_revision is not None:
            object.__setattr__(self, "applied_revision", _positive_revision("applied_revision", self.applied_revision))
        if not isinstance(self.status, PadiemRoutingProfileStatus):
            raise _error("invalid_padiem_profile_receipt", "status is invalid")
        object.__setattr__(self, "audit_ref", _ref("audit_ref", self.audit_ref))
        object.__setattr__(self, "confirmation_ref", _ref("confirmation_ref", self.confirmation_ref))
        if self.rollback_anchor_ref is not None:
            object.__setattr__(self, "rollback_anchor_ref", _ref("rollback_anchor_ref", self.rollback_anchor_ref))
        if self.status is PadiemRoutingProfileStatus.APPLIED and self.applied_revision is None:
            raise _error("invalid_padiem_profile_receipt", "applied receipt requires applied_revision")

    def safe_dict(self) -> dict[str, object]:
        return {
            "receipt_ref": self.receipt_ref,
            "profile_id": self.profile_id,
            "from_revision": self.from_revision,
            "applied_revision": self.applied_revision,
            "status": self.status.value,
            "audit_ref": self.audit_ref,
            "confirmation_ref": self.confirmation_ref,
            "rollback_anchor_ref": self.rollback_anchor_ref,
        }


def apply_padiem_routing_profile_stage(
    change: PadiemRoutingProfileStagedChange,
    *,
    current_revision: int,
    now: datetime,
    apply_operator_grant: PadiemRoutingProfileOperatorGrant,
    receipt_ref: str,
    audit_ref: str,
    confirmation_ref: str,
    rollback_anchor_ref: str,
) -> PadiemRoutingProfileApplyReceipt:
    valid = validate_padiem_routing_profile_stage(change, current_revision=current_revision, now=now)
    if valid.status is not PadiemRoutingProfileStatus.VALID:
        raise _error("padiem_profile_stage_invalid", PadiemRoutingProfileStatus.REJECTED.value)
    if not isinstance(apply_operator_grant, PadiemRoutingProfileOperatorGrant):
        raise _error("padiem_profile_operator_not_authorized", PadiemRoutingProfileStatus.OPERATOR_NOT_AUTHORIZED.value)
    if not apply_operator_grant.is_active(now=now) or not apply_operator_grant.allows(
        PadiemRoutingProfileOperatorAction.APPLY
    ):
        raise _error("padiem_profile_operator_not_authorized", PadiemRoutingProfileStatus.OPERATOR_NOT_AUTHORIZED.value)
    return PadiemRoutingProfileApplyReceipt(
        receipt_ref=receipt_ref,
        profile_id=valid.profile_id,
        from_revision=valid.base_revision,
        applied_revision=valid.proposed_revision,
        status=PadiemRoutingProfileStatus.APPLIED,
        audit_ref=audit_ref,
        confirmation_ref=confirmation_ref,
        rollback_anchor_ref=rollback_anchor_ref,
    )


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileRollbackAnchor:
    anchor_ref: str
    profile_id: str
    source_revision: int
    target_revision: int
    target_selections: tuple[PadiemRoutingProfileTierSelection, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchor_ref", _ref("anchor_ref", self.anchor_ref))
        object.__setattr__(self, "profile_id", _ref("profile_id", self.profile_id))
        object.__setattr__(self, "source_revision", _positive_revision("source_revision", self.source_revision))
        object.__setattr__(self, "target_revision", _positive_revision("target_revision", self.target_revision))
        if self.target_revision >= self.source_revision:
            raise _error("invalid_padiem_profile_rollback", "target_revision must precede source_revision")
        _validate_selections(_tuple_of(self.target_selections, PadiemRoutingProfileTierSelection, "target_selections", 3))
        object.__setattr__(self, "created_at", _aware("created_at", self.created_at))

    def safe_dict(self) -> dict[str, object]:
        return {
            "anchor_ref": self.anchor_ref,
            "profile_id": self.profile_id,
            "source_revision": self.source_revision,
            "target_revision": self.target_revision,
            "created_at": self.created_at.isoformat(),
            "history_retained": True,
        }


def rollback_padiem_routing_profile(
    current: PadiemRoutingProfileRevision,
    anchor: PadiemRoutingProfileRollbackAnchor,
    operator_grant: PadiemRoutingProfileOperatorGrant,
    *,
    now: datetime,
) -> PadiemRoutingProfileRevision:
    if current.profile_id != anchor.profile_id or current.revision != anchor.source_revision:
        raise _error("padiem_profile_revision_conflict", PadiemRoutingProfileStatus.REVISION_CONFLICT.value)
    checked = _aware("now", now)
    if not operator_grant.is_active(now=checked) or not operator_grant.allows(
        PadiemRoutingProfileOperatorAction.ROLLBACK
    ):
        raise _error("padiem_profile_operator_not_authorized", PadiemRoutingProfileStatus.OPERATOR_NOT_AUTHORIZED.value)
    return PadiemRoutingProfileRevision(
        profile_id=current.profile_id,
        revision=current.revision + 1,
        policy_version=PRODUCT_TIER_POLICY_VERSION,
        selections=anchor.target_selections,
        created_at=checked,
    )


@dataclass(frozen=True, slots=True)
class PadiemRoutingProfileAuditPayload:
    """Secret-free audit projection containing refs, status, and reason only."""

    event_ref: str
    profile_id: str
    status: PadiemRoutingProfileStatus
    actor_ref: str
    revision: int
    correlation_ref: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_ref", "profile_id", "actor_ref", "correlation_ref"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        object.__setattr__(self, "revision", _positive_revision("revision", self.revision))
        if not isinstance(self.status, PadiemRoutingProfileStatus):
            raise _error("invalid_padiem_profile_audit", "status is invalid")
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", _code("reason_code", self.reason_code))

    def safe_dict(self) -> dict[str, object]:
        return {
            "event_ref": self.event_ref,
            "profile_id": self.profile_id,
            "status": self.status.value,
            "actor_ref": self.actor_ref,
            "revision": self.revision,
            "correlation_ref": self.correlation_ref,
            "reason_code": self.reason_code,
        }
