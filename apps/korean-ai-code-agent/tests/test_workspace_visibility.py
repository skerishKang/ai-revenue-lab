from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.workspace_visibility import (
    CLIENT_ASSERTED_ROLE_TRUSTED,
    REAL_CONTROL_PLANE_MEMBERSHIP_CALL_CONFIGURED,
    VISIBILITY_DECISION_GRANTS_EXECUTION_AUTHORITY,
    ProductViewKind,
    TrustedWorkspaceMembershipProjection,
    WorkspaceRole,
    WorkspaceVisibilityPolicy,
)


NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)


def membership(role, *, workspace_id="ws_1", issued_at=None, expires_at=None):
    return TrustedWorkspaceMembershipProjection(
        membership_id=f"membership:{role.value}",
        workspace_id=workspace_id,
        principal_ref="principal:user_1",
        role=role,
        authority_ref="control-plane:membership",
        issued_at=issued_at or NOW - timedelta(minutes=5),
        expires_at=expires_at or NOW + timedelta(minutes=30),
    )


class WorkspaceVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.policy = WorkspaceVisibilityPolicy()

    def test_viewer_sees_run_status_only(self):
        viewer = membership(WorkspaceRole.VIEWER)
        allowed = self.policy.decide(membership=viewer, workspace_id="ws_1", view_kind=ProductViewKind.RUN_STATUS, now=NOW)
        self.assertTrue(allowed.allowed)
        for kind in (
            ProductViewKind.OPERATIONAL_ALERTS,
            ProductViewKind.APPROVAL_INBOX,
            ProductViewKind.SUPPLIER_COST,
            ProductViewKind.FINANCE,
            ProductViewKind.ORDER_ECONOMICS,
            ProductViewKind.AUDIT_REFERENCES,
        ):
            with self.subTest(kind=kind):
                self.assertFalse(self.policy.decide(membership=viewer, workspace_id="ws_1", view_kind=kind, now=NOW).allowed)

    def test_operator_gets_operational_facts_not_finance_or_supplier_cost(self):
        operator = membership(WorkspaceRole.OPERATOR)
        self.assertTrue(self.policy.decide(membership=operator, workspace_id="ws_1", view_kind=ProductViewKind.OPERATIONAL_ALERTS, now=NOW).allowed)
        for kind in (ProductViewKind.SUPPLIER_COST, ProductViewKind.FINANCE, ProductViewKind.ORDER_ECONOMICS):
            decision = self.policy.decide(membership=operator, workspace_id="ws_1", view_kind=kind, now=NOW)
            self.assertFalse(decision.allowed)
            self.assertFalse(decision.supplier_cost_visible)
            self.assertFalse(decision.finance_visible)

    def test_approver_can_view_approval_and_exact_supplier_cost_but_not_general_finance(self):
        approver = membership(WorkspaceRole.APPROVER)
        inbox = self.policy.decide(membership=approver, workspace_id="ws_1", view_kind=ProductViewKind.APPROVAL_INBOX, now=NOW)
        cost = self.policy.decide(membership=approver, workspace_id="ws_1", view_kind=ProductViewKind.SUPPLIER_COST, now=NOW)
        finance = self.policy.decide(membership=approver, workspace_id="ws_1", view_kind=ProductViewKind.FINANCE, now=NOW)
        self.assertTrue(inbox.allowed)
        self.assertTrue(inbox.approval_fields_visible)
        self.assertTrue(cost.allowed)
        self.assertTrue(cost.supplier_cost_visible)
        self.assertFalse(finance.allowed)

    def test_owner_can_view_finance_economics_and_audit_refs(self):
        owner = membership(WorkspaceRole.OWNER)
        finance = self.policy.decide(membership=owner, workspace_id="ws_1", view_kind=ProductViewKind.FINANCE, now=NOW)
        economics = self.policy.decide(membership=owner, workspace_id="ws_1", view_kind=ProductViewKind.ORDER_ECONOMICS, now=NOW)
        audit = self.policy.decide(membership=owner, workspace_id="ws_1", view_kind=ProductViewKind.AUDIT_REFERENCES, now=NOW)
        self.assertTrue(finance.allowed and finance.finance_visible)
        self.assertTrue(economics.allowed and economics.finance_visible)
        self.assertTrue(audit.allowed and audit.audit_refs_visible)

    def test_expired_future_and_cross_workspace_membership_fail_closed(self):
        expired = membership(WorkspaceRole.OWNER, expires_at=NOW - timedelta(seconds=1), issued_at=NOW - timedelta(hours=1))
        self.assertFalse(self.policy.decide(membership=expired, workspace_id="ws_1", view_kind=ProductViewKind.FINANCE, now=NOW).allowed)
        future = membership(WorkspaceRole.OWNER, issued_at=NOW + timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10))
        self.assertFalse(self.policy.decide(membership=future, workspace_id="ws_1", view_kind=ProductViewKind.FINANCE, now=NOW).allowed)
        with self.assertRaises(ContractError):
            self.policy.decide(membership=membership(WorkspaceRole.OWNER), workspace_id="ws_2", view_kind=ProductViewKind.FINANCE, now=NOW)

    def test_visibility_never_grants_write_approval_or_raw_sensitive_runtime_data(self):
        rendered = self.policy.decide(
            membership=membership(WorkspaceRole.OWNER),
            workspace_id="ws_1",
            view_kind=ProductViewKind.AUDIT_REFERENCES,
            now=NOW,
        ).safe_dict()
        self.assertFalse(rendered["execution_authority_granted"])
        self.assertFalse(rendered["write_authority_granted"])
        self.assertFalse(rendered["approval_authority_granted"])
        self.assertFalse(rendered["raw_audit_payload_visible"])
        self.assertFalse(rendered["credential_values_visible"])
        self.assertFalse(rendered["hidden_reasoning_visible"])
        self.assertFalse(CLIENT_ASSERTED_ROLE_TRUSTED)
        self.assertFalse(REAL_CONTROL_PLANE_MEMBERSHIP_CALL_CONFIGURED)
        self.assertFalse(VISIBILITY_DECISION_GRANTS_EXECUTION_AUTHORITY)


if __name__ == "__main__":
    unittest.main()
