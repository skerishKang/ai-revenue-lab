from __future__ import annotations

from datetime import date
import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import ApprovalAction, ApprovalDecision, BusinessObjectKind
from kagent.ops_executive_brief import (
    EXECUTIVE_BRIEF_EXECUTION_AUTHORITY,
    HIDDEN_MODEL_PRIORITY_SUPPORTED,
    BriefPriority,
    DailyExecutiveBriefProjector,
    OperationalAlert,
)
from kagent.ops_finance import CashTimingRecommendation
from kagent.ops_inbox import ExecutiveInboxCard, InboxCardKind, InboxCardStatus, InboxPriority


FP = hashlib.sha256(b"action").hexdigest()
TODAY = date(2026, 9, 3)


def card(**kwargs):
    values = dict(
        card_id="card_1",
        workspace_id="ws_1",
        kind=InboxCardKind.PURCHASE_ORDER_APPROVAL,
        status=InboxCardStatus.OPEN,
        priority=InboxPriority.HIGH,
        title="발주 승인",
        summary="발주서 검토가 필요합니다.",
        approval_id="approval_1",
        action=ApprovalAction.ISSUE_PURCHASE_ORDER,
        target_kind=BusinessObjectKind.PURCHASE_ORDER,
        target_id="po_1",
        target_version=1,
        action_fingerprint=FP,
        decision=ApprovalDecision.PENDING,
    )
    values.update(kwargs)
    return ExecutiveInboxCard(**values)


def cash(code="PROJECTED_GAP", severity="high", shortage=TODAY):
    return CashTimingRecommendation(
        code=code,
        severity=severity,
        summary="Projected cash timing signal.",
        shortage_date=shortage,
        evidence_entry_ids=("cash_entry_1",),
    )


def alert(**kwargs):
    values = dict(
        alert_id="alert_1",
        workspace_id="ws_1",
        source_kind="delivery_exception",
        source_ref="delivery:1",
        priority=BriefPriority.MEDIUM,
        title="납기 확인",
        summary="공급사 납기 확인이 필요합니다.",
        due_date=TODAY,
        actionable=True,
    )
    values.update(kwargs)
    return OperationalAlert(**values)


class ExecutiveBriefTests(unittest.TestCase):
    def setUp(self):
        self.projector = DailyExecutiveBriefProjector()

    def test_deterministic_priority_orders_cash_gap_before_high_approval_then_operational(self):
        brief = self.projector.build(
            workspace_id="ws_1",
            on_date=TODAY,
            inbox_cards=(card(),),
            cash_recommendations=((cash(), "cash_projection:1"),),
            operational_alerts=(alert(),),
        )
        self.assertEqual([item.priority for item in brief.items], [BriefPriority.CRITICAL, BriefPriority.HIGH, BriefPriority.MEDIUM])
        self.assertEqual(brief.items[0].source_ref, "cash_projection:1")

    def test_no_gap_cash_signal_is_info_and_non_actionable(self):
        item = self.projector.from_cash_recommendation(
            cash(code="NO_GAP", severity="info", shortage=None),
            workspace_id="ws_1",
            source_ref="cash_projection:ok",
        )
        self.assertEqual(item.priority, BriefPriority.INFO)
        self.assertFalse(item.actionable)

    def test_resolved_approval_is_excluded_by_default_and_can_be_explicitly_included(self):
        resolved = card(status=InboxCardStatus.RESOLVED, decision=ApprovalDecision.APPROVED)
        default = self.projector.build(workspace_id="ws_1", on_date=TODAY, inbox_cards=(resolved,))
        self.assertEqual(default.items, ())
        included = self.projector.build(
            workspace_id="ws_1",
            on_date=TODAY,
            inbox_cards=(resolved,),
            include_resolved_approvals=True,
        )
        self.assertEqual(len(included.items), 1)
        self.assertFalse(included.items[0].actionable)

    def test_stale_approval_remains_visible_but_non_actionable(self):
        stale = card(status=InboxCardStatus.STALE)
        brief = self.projector.build(workspace_id="ws_1", on_date=TODAY, inbox_cards=(stale,))
        self.assertEqual(len(brief.items), 1)
        self.assertFalse(brief.items[0].actionable)

    def test_cross_workspace_inputs_fail_closed(self):
        with self.assertRaises(ContractError):
            self.projector.build(workspace_id="ws_1", on_date=TODAY, inbox_cards=(card(workspace_id="ws_2"),))
        with self.assertRaises(ContractError):
            self.projector.build(workspace_id="ws_1", on_date=TODAY, operational_alerts=(alert(workspace_id="ws_2"),))

    def test_duplicate_source_refs_fail_closed(self):
        with self.assertRaises(ContractError):
            self.projector.build(
                workspace_id="ws_1",
                on_date=TODAY,
                operational_alerts=(alert(alert_id="a1"), alert(alert_id="a2")),
            )

    def test_safe_export_is_read_only_and_has_no_execution_authority(self):
        brief = self.projector.build(workspace_id="ws_1", on_date=TODAY, inbox_cards=(card(),))
        rendered = brief.safe_dict()
        self.assertTrue(rendered["read_only"])
        self.assertFalse(rendered["hidden_model_ranking"])
        self.assertFalse(rendered["approval_execution_authority"])
        self.assertFalse(rendered["payment_execution_authority"])
        self.assertFalse(rendered["items"][0]["execution_authority"])
        self.assertFalse(EXECUTIVE_BRIEF_EXECUTION_AUTHORITY)
        self.assertFalse(HIDDEN_MODEL_PRIORITY_SUPPORTED)

    def test_secret_like_alert_summary_fails_closed(self):
        with self.assertRaises(ContractError):
            alert(summary="token=should_not_be_here")


if __name__ == "__main__":
    unittest.main()
