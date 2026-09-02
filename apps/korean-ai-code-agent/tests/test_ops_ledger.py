from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.ops_contracts import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalProjection,
    BusinessObjectKind,
    EvidenceOrigin,
    WorkflowEvidenceRecord,
)
from kagent.ops_ledger import BusinessObjectEnvelope, InMemoryOpsLedger


NOW = datetime(2026, 9, 2, 13, 30, tzinfo=timezone.utc)


class OpsLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = InMemoryOpsLedger()
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_1",
                version=1,
                workspace_id="ws_1",
                value={"status": "approval_required", "total": 1000},
            )
        )

    def test_versions_are_append_only_and_contiguous(self):
        with self.assertRaises(ContractError):
            self.ledger.append_object(
                BusinessObjectEnvelope(
                    kind=BusinessObjectKind.PURCHASE_ORDER,
                    object_id="po_1",
                    version=1,
                    workspace_id="ws_1",
                    value={"status": "duplicate"},
                )
            )
        with self.assertRaises(ContractError):
            self.ledger.append_object(
                BusinessObjectEnvelope(
                    kind=BusinessObjectKind.PURCHASE_ORDER,
                    object_id="po_1",
                    version=3,
                    workspace_id="ws_1",
                    value={"status": "gap"},
                )
            )
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_1",
                version=2,
                workspace_id="ws_1",
                value={"status": "edited"},
            )
        )
        self.assertEqual(
            self.ledger.latest_object(
                workspace_id="ws_1",
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_1",
            ).version,
            2,
        )

    def test_evidence_must_reference_existing_exact_object_version(self):
        evidence = WorkflowEvidenceRecord(
            evidence_id="ev_1",
            workspace_id="ws_1",
            workflow_id="wf_1",
            object_kind=BusinessObjectKind.PURCHASE_ORDER,
            object_id="po_1",
            object_version=1,
            origin=EvidenceOrigin.SOURCE_DOCUMENT,
            source_ref="artifact_1",
            summary="PO draft source",
            recorded_at=NOW,
            authoritative=True,
        )
        self.ledger.add_evidence(evidence)
        self.ledger.add_evidence(evidence)
        self.assertEqual(
            self.ledger.evidence_for_object(
                workspace_id="ws_1",
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_1",
                version=1,
            ),
            (evidence,),
        )
        with self.assertRaises(ContractError):
            self.ledger.add_evidence(
                WorkflowEvidenceRecord(
                    evidence_id="ev_missing",
                    workspace_id="ws_1",
                    workflow_id="wf_1",
                    object_kind=BusinessObjectKind.PURCHASE_ORDER,
                    object_id="po_1",
                    object_version=2,
                    origin=EvidenceOrigin.USER_ACTION,
                    source_ref="user_1",
                    summary="not present yet",
                    recorded_at=NOW,
                )
            )

    def test_approval_pending_to_decided_projection_is_single_transition(self):
        pending = ApprovalProjection(
            approval_id="approval_1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=1,
            action_fingerprint="a" * 64,
        )
        self.ledger.add_approval_projection(pending)
        decided = ApprovalProjection(
            approval_id="approval_1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=1,
            action_fingerprint="a" * 64,
            decision=ApprovalDecision.APPROVED,
            actor_ref="user_1",
            decided_at=NOW,
        )
        self.ledger.add_approval_projection(decided)
        self.assertTrue(self.ledger.approval("approval_1").approved)
        with self.assertRaises(ContractError):
            self.ledger.add_approval_projection(
                ApprovalProjection(
                    approval_id="approval_1",
                    workspace_id="ws_1",
                    action=ApprovalAction.ISSUE_PURCHASE_ORDER,
                    target_kind=BusinessObjectKind.PURCHASE_ORDER,
                    target_id="po_1",
                    target_version=1,
                    action_fingerprint="a" * 64,
                    decision=ApprovalDecision.REJECTED,
                    actor_ref="user_2",
                    decided_at=NOW,
                )
            )

    def test_require_approved_action_checks_all_binding_fields(self):
        approved = ApprovalProjection(
            approval_id="approval_1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=1,
            action_fingerprint="b" * 64,
            decision=ApprovalDecision.APPROVED,
            actor_ref="user_1",
            decided_at=NOW,
        )
        self.ledger.add_approval_projection(approved)
        result = self.ledger.require_approved_action(
            approval_id="approval_1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=1,
            action_fingerprint="b" * 64,
        )
        self.assertTrue(result.approved)
        with self.assertRaises(ContractError):
            self.ledger.require_approved_action(
                approval_id="approval_1",
                workspace_id="ws_1",
                action=ApprovalAction.ISSUE_PURCHASE_ORDER,
                target_kind=BusinessObjectKind.PURCHASE_ORDER,
                target_id="po_1",
                target_version=1,
                action_fingerprint="c" * 64,
            )

    def test_newer_target_version_invalidates_old_approval(self):
        approved = ApprovalProjection(
            approval_id="approval_1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=1,
            action_fingerprint="d" * 64,
            decision=ApprovalDecision.APPROVED,
            actor_ref="user_1",
            decided_at=NOW,
        )
        self.ledger.add_approval_projection(approved)
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_1",
                version=2,
                workspace_id="ws_1",
                value={"status": "edited after approval"},
            )
        )
        with self.assertRaisesRegex(ContractError, "stale"):
            self.ledger.require_approved_action(
                approval_id="approval_1",
                workspace_id="ws_1",
                action=ApprovalAction.ISSUE_PURCHASE_ORDER,
                target_kind=BusinessObjectKind.PURCHASE_ORDER,
                target_id="po_1",
                target_version=1,
                action_fingerprint="d" * 64,
            )

    def test_cross_workspace_approval_cannot_authorize_action(self):
        self.ledger.append_object(
            BusinessObjectEnvelope(
                kind=BusinessObjectKind.PURCHASE_ORDER,
                object_id="po_1",
                version=1,
                workspace_id="ws_2",
                value={"status": "another tenant"},
            )
        )
        approved = ApprovalProjection(
            approval_id="approval_ws1",
            workspace_id="ws_1",
            action=ApprovalAction.ISSUE_PURCHASE_ORDER,
            target_kind=BusinessObjectKind.PURCHASE_ORDER,
            target_id="po_1",
            target_version=1,
            action_fingerprint="e" * 64,
            decision=ApprovalDecision.APPROVED,
            actor_ref="user_1",
            decided_at=NOW,
        )
        self.ledger.add_approval_projection(approved)
        with self.assertRaises(ContractError):
            self.ledger.require_approved_action(
                approval_id="approval_ws1",
                workspace_id="ws_2",
                action=ApprovalAction.ISSUE_PURCHASE_ORDER,
                target_kind=BusinessObjectKind.PURCHASE_ORDER,
                target_id="po_1",
                target_version=1,
                action_fingerprint="e" * 64,
            )


if __name__ == "__main__":
    unittest.main()
