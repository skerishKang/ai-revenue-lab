"""Trusted server-only B66 Saved Quote Skill provisioning contracts (#3302).

This module intentionally exposes no browser route and performs no account lookup.
The trusted host must provide:
- an active operator grant projected from server-side authority;
- a server-resolved target account/workspace;
- an already-approved Saved Quote Skill artifact validated by #3301.

The service then calls the injected durable #3301 store. Browser/client payloads
cannot manufacture ownership merely by supplying user/tenant/workspace strings,
because the public service entry points require trusted value-object types.

This is a bounded operator command, not a second identity or tenant authority.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from padiem_control_plane.contracts import CanonicalSubjectRef

from .b66_saved_quote_skill_store import (
    ApprovedSavedQuoteSkillArtifact,
    SavedQuoteSkillStore,
)

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_USER_RE = re.compile(r"^usr_[0-9a-zA-Z._:-]{1,76}$")
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_TENANT_RE = re.compile(r"^tenant_[0-9a-f]{32}$")


class B66ProvisioningError(RuntimeError):
    pass


class B66ProvisioningAction(str, Enum):
    ASSIGN = "assign"
    DISABLE = "disable"
    PROVISION_ASSET = "provision_asset"
    PROVISION_COMPANY_PROFILE = "provision_company_profile"


def _aware(name: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise B66ProvisioningError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ref(name: str, value: object) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise B66ProvisioningError(f"{name} must be a bounded reference")
    return value


@dataclass(frozen=True, slots=True)
class TrustedB66ProvisioningGrant:
    """Server-trusted operator capability projection.

    The authority that authenticates staff/operators lives outside this module.
    This value object only carries its bounded result and expiry window.
    """

    grant_ref: str
    operator_subject: CanonicalSubjectRef
    authority_ref: str
    allowed_actions: tuple[B66ProvisioningAction, ...]
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_ref", _ref("grant_ref", self.grant_ref))
        object.__setattr__(self, "authority_ref", _ref("authority_ref", self.authority_ref))
        if not isinstance(self.operator_subject, CanonicalSubjectRef):
            raise B66ProvisioningError("operator_subject must be canonical")
        if (
            not isinstance(self.allowed_actions, tuple)
            or not self.allowed_actions
            or len(self.allowed_actions) > len(B66ProvisioningAction)
            or any(not isinstance(item, B66ProvisioningAction) for item in self.allowed_actions)
            or len(set(self.allowed_actions)) != len(self.allowed_actions)
        ):
            raise B66ProvisioningError("allowed_actions must be bounded and unique")
        object.__setattr__(self, "issued_at", _aware("issued_at", self.issued_at))
        object.__setattr__(self, "expires_at", _aware("expires_at", self.expires_at))
        if self.expires_at <= self.issued_at:
            raise B66ProvisioningError("expires_at must follow issued_at")

    def is_active(self, *, now: datetime) -> bool:
        checked = _aware("now", now)
        return self.issued_at <= checked < self.expires_at

    def allows(self, action: B66ProvisioningAction) -> bool:
        return action in self.allowed_actions


@dataclass(frozen=True, slots=True)
class ResolvedB66ProvisioningTarget:
    """Server-resolved product ownership target.

    No constructor helper accepts a generic request payload. The host is expected
    to build this only after looking up the Padiem account and canonical tenant.
    """

    user_id: str
    workspace_id: str
    tenant_id: str
    canonical_subject_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not _USER_RE.fullmatch(self.user_id):
            raise B66ProvisioningError("target user_id is invalid")
        if (
            not isinstance(self.workspace_id, str)
            or not _WORKSPACE_RE.fullmatch(self.workspace_id)
        ):
            raise B66ProvisioningError("target workspace_id is invalid")
        if not isinstance(self.tenant_id, str) or not _TENANT_RE.fullmatch(self.tenant_id):
            raise B66ProvisioningError("target tenant_id is invalid")
        object.__setattr__(
            self,
            "canonical_subject_id",
            _ref("canonical_subject_id", self.canonical_subject_id),
        )
        if self.tenant_id == self.canonical_subject_id:
            raise B66ProvisioningError("tenant and canonical subject must differ")


@dataclass(frozen=True, slots=True)
class B66ProvisioningReceipt:
    receipt_ref: str
    action: B66ProvisioningAction
    grant_ref: str
    operator_subject_id: str
    target_tenant_id: str
    target_workspace_id: str
    target_user_id: str
    saved_skill_id: str
    skill_id: str | None
    skill_fingerprint: str | None
    occurred_at: datetime

    def safe_dict(self) -> dict[str, object]:
        return {
            "receipt_ref": self.receipt_ref,
            "action": self.action.value,
            "grant_ref": self.grant_ref,
            "operator_subject_id": self.operator_subject_id,
            "target_tenant_id": self.target_tenant_id,
            "target_workspace_id": self.target_workspace_id,
            "target_user_id": self.target_user_id,
            "saved_skill_id": self.saved_skill_id,
            "skill_id": self.skill_id,
            "skill_fingerprint": self.skill_fingerprint,
            "occurred_at": self.occurred_at.isoformat(),
        }


def _receipt_ref() -> str:
    return "b66prov_" + uuid.uuid4().hex


class B66SavedQuoteSkillProvisioner:
    """Bounded trusted-host command over the #3301 durable store."""

    def __init__(self, store: SavedQuoteSkillStore):
        if store is None:
            raise ValueError("Saved Quote Skill store is required")
        self._store = store

    @staticmethod
    def _authorize(
        *,
        grant: TrustedB66ProvisioningGrant,
        action: B66ProvisioningAction,
        now: datetime,
    ) -> datetime:
        if not isinstance(grant, TrustedB66ProvisioningGrant):
            raise B66ProvisioningError("trusted operator grant is required")
        checked = _aware("now", now)
        if not grant.is_active(now=checked) or not grant.allows(action):
            raise B66ProvisioningError("operator is not authorized")
        return checked

    @staticmethod
    def _target(target: ResolvedB66ProvisioningTarget) -> ResolvedB66ProvisioningTarget:
        if not isinstance(target, ResolvedB66ProvisioningTarget):
            raise B66ProvisioningError("server-resolved target is required")
        return target

    async def assign(
        self,
        *,
        grant: TrustedB66ProvisioningGrant,
        target: ResolvedB66ProvisioningTarget,
        artifact: ApprovedSavedQuoteSkillArtifact,
        now: datetime,
    ) -> tuple[dict[str, Any], B66ProvisioningReceipt]:
        checked = self._authorize(
            grant=grant,
            action=B66ProvisioningAction.ASSIGN,
            now=now,
        )
        resolved = self._target(target)
        if not isinstance(artifact, ApprovedSavedQuoteSkillArtifact):
            raise B66ProvisioningError("approved Saved Quote Skill artifact is required")

        stored = await self._store.put_approved_skill(
            user_id=resolved.user_id,
            workspace_id=resolved.workspace_id,
            artifact=artifact,
        )
        saved_skill_id = stored.get("saved_skill_id")
        if not isinstance(saved_skill_id, str) or not saved_skill_id:
            raise B66ProvisioningError("durable assignment did not return a saved skill id")
        receipt = B66ProvisioningReceipt(
            receipt_ref=_receipt_ref(),
            action=B66ProvisioningAction.ASSIGN,
            grant_ref=grant.grant_ref,
            operator_subject_id=grant.operator_subject.subject_id,
            target_tenant_id=resolved.tenant_id,
            target_workspace_id=resolved.workspace_id,
            target_user_id=resolved.user_id,
            saved_skill_id=saved_skill_id,
            skill_id=artifact.skill_id,
            skill_fingerprint=artifact.fingerprint,
            occurred_at=checked,
        )
        return stored, receipt

    async def disable(
        self,
        *,
        grant: TrustedB66ProvisioningGrant,
        target: ResolvedB66ProvisioningTarget,
        saved_skill_id: str,
        now: datetime,
    ) -> B66ProvisioningReceipt | None:
        checked = self._authorize(
            grant=grant,
            action=B66ProvisioningAction.DISABLE,
            now=now,
        )
        resolved = self._target(target)
        if not isinstance(saved_skill_id, str) or not saved_skill_id:
            raise B66ProvisioningError("saved_skill_id is required")
        disabled = await self._store.disable_skill(
            user_id=resolved.user_id,
            workspace_id=resolved.workspace_id,
            saved_skill_id=saved_skill_id,
        )
        if not disabled:
            return None
        return B66ProvisioningReceipt(
            receipt_ref=_receipt_ref(),
            action=B66ProvisioningAction.DISABLE,
            grant_ref=grant.grant_ref,
            operator_subject_id=grant.operator_subject.subject_id,
            target_tenant_id=resolved.tenant_id,
            target_workspace_id=resolved.workspace_id,
            target_user_id=resolved.user_id,
            saved_skill_id=saved_skill_id,
            skill_id=None,
            skill_fingerprint=None,
            occurred_at=checked,
        )
