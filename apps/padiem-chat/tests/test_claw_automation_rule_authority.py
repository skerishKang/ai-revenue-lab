from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import unittest

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
)
from kagent.contracts import ContractError
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

from app.claw_automation_rule_authority import (
    B54_AUTOMATION_PRODUCT_ID,
    create_canonical_automation_rule,
)

NOW = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)
TENANT = "tenant_0123456789abcdef0123456789abcdef"
SUBJECT = "sub_0123456789abcdef0123456789abcdef"


def session(
    *,
    tenant_id: str | None = TENANT,
    state: AuthSessionState = AuthSessionState.ACTIVE,
    expires_at: datetime | None = None,
) -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="sess_canonical_rule",
        product_id=B54_AUTOMATION_PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
        issued_at=NOW - timedelta(hours=1),
        expires_at=expires_at or NOW + timedelta(hours=1),
        state=state,
        tenant_id=tenant_id,
    )


def create(auth_session: AuthSessionSnapshot):
    return create_canonical_automation_rule(
        auth_session=auth_session,
        now=NOW,
        rule_id="rule_canonical",
        name="canonical rule",
        schedule=ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC"),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
        owner_ref="owner:opaque",
    )


class CanonicalRuleCreationTests(unittest.TestCase):
    def test_active_session_derives_tenant_and_subject(self) -> None:
        rule = create(session())
        self.assertEqual(rule.workspace_id, TENANT)
        self.assertEqual(rule.canonical_subject_id, SUBJECT)
        self.assertEqual(rule.owner_ref, "owner:opaque")

    def test_missing_tenant_refuses_creation(self) -> None:
        with self.assertRaises(ContractError):
            create(session(tenant_id=None))

    def test_expired_or_revoked_session_refuses_creation(self) -> None:
        with self.assertRaises(ContractError):
            create(session(expires_at=NOW - timedelta(seconds=1)))
        with self.assertRaises(ContractError):
            create(session(state=AuthSessionState.REVOKED))

    def test_creation_signature_has_no_caller_tenant_or_subject(self) -> None:
        parameters = inspect.signature(create_canonical_automation_rule).parameters
        self.assertNotIn("workspace_id", parameters)
        self.assertNotIn("tenant_id", parameters)
        self.assertNotIn("canonical_subject_id", parameters)
        self.assertIn("owner_ref", parameters)

    def test_owner_ref_cannot_replace_subject(self) -> None:
        rule = create(session())
        self.assertNotEqual(rule.owner_ref, rule.canonical_subject_id)
        self.assertEqual(rule.canonical_subject_id, SUBJECT)


if __name__ == "__main__":
    unittest.main()
