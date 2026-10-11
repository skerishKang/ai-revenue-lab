"""Server-derived canonical provenance for new B54 automation rules."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawNotificationPreference,
    ClawScheduleExpression,
)
from kagent.contracts import ContractError
from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.contracts import SubjectType

B54_AUTOMATION_PRODUCT_ID = "b54-padiem-claw"
_CANONICAL_TENANT_ID_RE = re.compile(r"^tenant_[0-9a-f]{32}$")
_CANONICAL_SUBJECT_ID_RE = re.compile(r"^sub_[0-9a-f]{32}$")


def _now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError("canonical_rule_session_time_invalid")
    return value.astimezone(timezone.utc)


def create_canonical_automation_rule(
    *,
    auth_session: AuthSessionSnapshot,
    now: datetime,
    rule_id: str,
    name: str,
    schedule: ClawScheduleExpression,
    target_source: ClawAutomationTarget,
    output_type: ClawAutomationOutputType,
    enabled: bool = True,
    notification_channels: tuple[ClawNotificationPreference, ...] | None = None,
    owner_ref: str | None = None,
    execution_intent: ClawAutomationExecutionIntent | None = None,
) -> ClawAutomationRule:
    if not isinstance(auth_session, AuthSessionSnapshot):
        raise ContractError("canonical_rule_session_required")
    observed_at = _now(now)
    if auth_session.product_id != B54_AUTOMATION_PRODUCT_ID:
        raise ContractError("canonical_rule_session_product_mismatch")
    if auth_session.subject.subject_type is not SubjectType.USER:
        raise ContractError("canonical_rule_subject_type_invalid")
    if not auth_session.is_active(now=observed_at):
        raise ContractError("canonical_rule_session_inactive")
    tenant_id = auth_session.tenant_id
    subject_id = auth_session.subject.subject_id
    if not isinstance(tenant_id, str) or not _CANONICAL_TENANT_ID_RE.fullmatch(tenant_id):
        raise ContractError("canonical_rule_tenant_unavailable")
    if not isinstance(subject_id, str) or not _CANONICAL_SUBJECT_ID_RE.fullmatch(subject_id):
        raise ContractError("canonical_rule_subject_unavailable")
    values: dict[str, Any] = {
        "rule_id": rule_id,
        "workspace_id": tenant_id,
        "name": name,
        "schedule": schedule,
        "target_source": target_source,
        "output_type": output_type,
        "enabled": enabled,
        "owner_ref": owner_ref,
        "execution_intent": execution_intent,
        "canonical_subject_id": subject_id,
    }
    if notification_channels is not None:
        values["notification_channels"] = notification_channels
    return ClawAutomationRule(**values)


CANONICAL_RULE_CREATION_REQUIRES_ACTIVE_SESSION = True
CANONICAL_RULE_TENANT_SERVER_DERIVED = True
CANONICAL_RULE_SUBJECT_SERVER_DERIVED = True
CALLER_MINTED_TENANT = False
CALLER_MINTED_SUBJECT = False
OWNER_REF_AS_IDENTITY_AUTHORITY = False


__all__ = [
    "B54_AUTOMATION_PRODUCT_ID",
    "create_canonical_automation_rule",
]
