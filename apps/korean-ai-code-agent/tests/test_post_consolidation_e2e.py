from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import unittest

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from kagent.cloud_execution_plan import (
    FIXED_CLOUD_M1_STAGE_ORDER,
    CloudM1ExecutionPlan,
    CloudM1Stage,
)
from kagent.cloud_stage_receipts import (
    CloudExecutionTerminal,
    CloudM1StageReceipt,
    CloudM1StageReceiptLedger,
    CloudStageOutcome,
)
from kagent.cloud_teardown import CloudM1TeardownReceipt, TrustedTeardownObservation
from kagent.github_draft_pr import (
    DeterministicFakeGitHubDraftPullRequestPort,
    DraftPrApprovalBinding,
    DraftPullRequestPlan,
)
from kagent.github_pr_outbox import GitHubDraftPrOutboxState, InMemoryGitHubDraftPrOutbox
from kagent.ops_contracts import (
    ApprovalDecision,
    ApprovalProjection,
    CommercialRequest,
    LineItem,
    Money,
    PaymentTerms,
    PurchaseOrderStatus,
    Supplier,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteStatus,
)
from kagent.ops_customer_acceptance import (
    CustomerQuoteDecisionOutcome,
    InMemoryCustomerQuoteDecisionLedger,
    TrustedCustomerQuoteDecision,
)
from kagent.ops_customer_quote import CustomerQuotePricingPolicy, build_customer_quote_draft
from kagent.ops_customer_quote_send import (
    ApprovalGatedCustomerQuoteSender,
    CustomerQuoteSendBinding,
    CustomerQuoteSendChannel,
    CustomerQuoteSendRequest,
    DeterministicFakeCustomerQuoteOutboundPort,
)
from kagent.ops_order_economics import (
    CustomerPaymentTerms,
    build_sales_order_receivable,
    project_order_economics,
)
from kagent.ops_workflow import DeterministicFakeOpsOutboundPort, QuoteToOrderCoordinator
from kagent.sandbox_conformance import VerifiedDiffEvidence


NOW = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def approved_projection(pending: ApprovalProjection, *, actor_ref: str = "owner:1") -> ApprovalProjection:
    return ApprovalProjection(
        approval_id=pending.approval_id,
        workspace_id=pending.workspace_id,
        action=pending.action,
        target_kind=pending.target_kind,
        target_id=pending.target_id,
        target_version=pending.target_version,
        action_fingerprint=pending.action_fingerprint,
        decision=ApprovalDecision.APPROVED,
        actor_ref=actor_ref,
        decided_at=NOW,
    )


def canonical_decision(*, decision_id: str, pause_id: str, at: datetime) -> VerifiedApprovalDecision:
    return VerifiedApprovalDecision(
        decision_id=decision_id,
        pause_id=pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="trusted_control_plane",
        evidence_ref=f"evidence:{decision_id}",
        decided_at=at,
    )


class PostConsolidationOpsE2ETests(unittest.TestCase):
    def test_quote_to_order_customer_acceptance_and_economics_compose(self) -> None:
        ops_outbound = DeterministicFakeOpsOutboundPort(clock=lambda: NOW)
        coordinator = QuoteToOrderCoordinator(outbound=ops_outbound, clock=lambda: NOW)
        request = CommercialRequest(
            request_id="request:e2e:1",
            workspace_id="workspace:e2e",
            customer_id="customer:e2e",
            version=1,
            title="모터 공급 요청",
            line_items=(LineItem("line:1", "모터", Decimal("2"), "EA"),),
            requested_delivery_date=date(2026, 9, 30),
        )
        coordinator.register_request(request)

        suppliers = (
            Supplier(
                supplier_id="supplier:a",
                workspace_id=request.workspace_id,
                name="Supplier A",
                payment_terms=PaymentTerms("terms:a", "30 days", due_days=30),
            ),
            Supplier(
                supplier_id="supplier:b",
                workspace_id=request.workspace_id,
                name="Supplier B",
                payment_terms=PaymentTerms("terms:b", "30 days", due_days=30),
            ),
        )

        quotes: list[SupplierQuote] = []
        for index, (supplier, unit_minor) in enumerate(zip(suppliers, (1000, 900), strict=True), start=1):
            rfq = coordinator.draft_supplier_rfq(
                request=request,
                supplier=supplier,
                rfq_id=f"rfq:{index}",
                message="견적 부탁드립니다.",
            )
            pending = coordinator.project_rfq_approval(
                rfq=rfq,
                approval_id=f"approval:rfq:{index}",
            )
            coordinator.record_approval_projection(approved_projection(pending))
            coordinator.send_rfq(
                workspace_id=request.workspace_id,
                rfq_id=rfq.rfq_id,
                approval_id=pending.approval_id,
            )
            quote = SupplierQuote(
                quote_id=f"quote:{index}",
                workspace_id=request.workspace_id,
                rfq_id=rfq.rfq_id,
                supplier_id=supplier.supplier_id,
                version=1,
                lines=(SupplierQuoteLine("line:1", Decimal("2"), Money(unit_minor, "KRW")),),
                status=SupplierQuoteStatus.RECEIVED,
                received_at=NOW + timedelta(minutes=index),
                promised_delivery_date=date(2026, 9, 20 + index),
                payment_terms=supplier.payment_terms,
            )
            coordinator.capture_supplier_quote(quote)
            quotes.append(quote)

        comparison = coordinator.build_comparison(
            workspace_id=request.workspace_id,
            commercial_request_id=request.request_id,
            comparison_id="comparison:e2e",
            quote_ids=tuple(quote.quote_id for quote in quotes),
        )
        self.assertEqual(comparison.recommended_supplier_id, "supplier:b")
        selected_quote = quotes[1]

        purchase_order = coordinator.draft_purchase_order(
            workspace_id=request.workspace_id,
            commercial_request_id=request.request_id,
            quote_id=selected_quote.quote_id,
            po_id="po:e2e",
        )
        self.assertEqual(purchase_order.status, PurchaseOrderStatus.APPROVAL_REQUIRED)
        po_pending = coordinator.project_purchase_order_approval(
            purchase_order=purchase_order,
            approval_id="approval:po:e2e",
        )
        coordinator.record_approval_projection(approved_projection(po_pending))
        issued_po = coordinator.issue_purchase_order(
            workspace_id=request.workspace_id,
            po_id=purchase_order.po_id,
            approval_id=po_pending.approval_id,
        )
        self.assertEqual(issued_po.status, PurchaseOrderStatus.ISSUED)

        customer_quote = build_customer_quote_draft(
            customer_quote_id="customer-quote:e2e",
            request=request,
            supplier_quote=selected_quote,
            policy=CustomerQuotePricingPolicy("pricing:standard", 1000),
        )
        customer_send = CustomerQuoteSendRequest(
            request_id="customer-send:e2e",
            quote=customer_quote,
            recipient_ref="customer-contact:e2e",
            channel=CustomerQuoteSendChannel.EMAIL,
            subject="견적서를 보내드립니다",
            body="검토 부탁드립니다.",
        )
        send_binding = CustomerQuoteSendBinding.bind(
            binding_id="binding:customer-send:e2e",
            pause_id="pause:customer-send:e2e",
            quote=customer_quote,
            recipient_ref=customer_send.recipient_ref,
            channel=customer_send.channel,
            subject=customer_send.subject,
            body=customer_send.body,
        )
        customer_port = DeterministicFakeCustomerQuoteOutboundPort(
            delivered_at=NOW + timedelta(minutes=10)
        )
        delivery_receipt = ApprovalGatedCustomerQuoteSender(customer_port).send(
            request=customer_send,
            binding=send_binding,
            decision=canonical_decision(
                decision_id="decision:customer-send:e2e",
                pause_id=send_binding.pause_id,
                at=NOW + timedelta(minutes=9),
            ),
        )

        customer_decision = TrustedCustomerQuoteDecision(
            decision_id="customer-acceptance:e2e",
            workspace_id=request.workspace_id,
            customer_id=request.customer_id,
            customer_quote_id=customer_quote.customer_quote_id,
            quote_version=customer_quote.version,
            pricing_fingerprint=customer_quote.pricing_fingerprint,
            outcome=CustomerQuoteDecisionOutcome.ACCEPTED,
            authority_ref="trusted:customer-confirmation",
            evidence_ref="evidence:customer-confirmation:e2e",
            decided_at=NOW + timedelta(minutes=15),
        )
        sales_order = InMemoryCustomerQuoteDecisionLedger().build_sales_order(
            quote=customer_quote,
            delivery_receipt=delivery_receipt,
            decision=customer_decision,
        )
        receivable = build_sales_order_receivable(
            sales_order=sales_order,
            payment_terms=CustomerPaymentTerms("customer-terms:30d", 30),
        )
        economics = project_order_economics(
            sales_order=sales_order,
            purchase_order=issued_po,
        )

        self.assertEqual([kind for kind, _, _ in ops_outbound.sent], ["rfq", "rfq", "po"])
        self.assertEqual(len(customer_port.sent), 1)
        self.assertEqual(sales_order.supplier_quote_id, selected_quote.quote_id)
        self.assertEqual(receivable.amount, sales_order.sale_total)
        self.assertEqual(economics.purchase_total, selected_quote.total)
        self.assertGreater(economics.gross_profit.amount_minor, 0)
        self.assertFalse(economics.safe_dict()["payment_authority"])


class PostConsolidationCloudE2ETests(unittest.TestCase):
    def test_verified_diff_draft_pr_outbox_and_verified_teardown_compose(self) -> None:
        cloud_plan = CloudM1ExecutionPlan(
            plan_id="cloud-plan:e2e",
            run_id="run:e2e",
            workspace_id="workspace:e2e",
            repository_ref="skerishKang/example",
            input_revision=REV,
            verification_command_ids=("verify_unit",),
            artifact_policy_ref="artifact-policy:m1",
            draft_pr_requested=True,
        )
        stage_ledger = CloudM1StageReceiptLedger(cloud_plan)

        diff_evidence = VerifiedDiffEvidence(
            run_id=cloud_plan.run_id,
            lease_id="lease:e2e",
            repository_ref=cloud_plan.repository_ref,
            input_revision=cloud_plan.input_revision,
            changed_files=("src/app.py",),
            unified_diff_sha256=hashlib.sha256(b"bounded diff").hexdigest(),
            verification_command_id=cloud_plan.verification_command_ids[0],
            verification_exit_code=0,
            verification_output_sha256=hashlib.sha256(b"tests passed").hexdigest(),
            terminal_reason="completed",
            final_revision_ref="workspace-final:e2e",
        )
        draft_pr_plan = DraftPullRequestPlan.from_verified_diff(
            plan_id="draft-pr-plan:e2e",
            evidence=diff_evidence,
            title="fix: bounded e2e change",
            body="Verified by the deterministic Cloud M1 compatibility gate.",
        )
        self.assertEqual(draft_pr_plan.repository, cloud_plan.repository_ref)
        self.assertEqual(draft_pr_plan.base_revision, cloud_plan.input_revision)

        binding = DraftPrApprovalBinding.bind(
            binding_id="binding:draft-pr:e2e",
            pause_id="pause:draft-pr:e2e",
            plan=draft_pr_plan,
        )
        github_port = DeterministicFakeGitHubDraftPullRequestPort()
        outbox = InMemoryGitHubDraftPrOutbox(github_port)

        for index, stage in enumerate(FIXED_CLOUD_M1_STAGE_ORDER):
            observed_at = NOW + timedelta(seconds=index)
            if stage is CloudM1Stage.OPTIONAL_DRAFT_PR:
                record = outbox.submit(
                    outbox_id="outbox:draft-pr:e2e",
                    plan=draft_pr_plan,
                    binding=binding,
                    decision=canonical_decision(
                        decision_id="decision:draft-pr:e2e",
                        pause_id=binding.pause_id,
                        at=observed_at,
                    ),
                    now=observed_at,
                )
                self.assertEqual(record.state, GitHubDraftPrOutboxState.CREATED)
                stage_receipt = CloudM1StageReceipt(
                    event_id="event:optional-draft-pr:e2e",
                    plan_id=cloud_plan.plan_id,
                    plan_fingerprint=cloud_plan.fingerprint,
                    stage=stage,
                    outcome=CloudStageOutcome.SUCCEEDED,
                    observed_at=observed_at,
                    evidence_ref=record.receipt_ref or "evidence:draft-pr:e2e",
                    summary_code="draft_pr_created",
                )
            elif stage is CloudM1Stage.TEARDOWN:
                teardown_observation = TrustedTeardownObservation(
                    observation_id="teardown-observation:e2e",
                    plan_id=cloud_plan.plan_id,
                    run_id=cloud_plan.run_id,
                    sandbox_lease_ref="sandbox:e2e",
                    computer_ref="computer:e2e",
                    observed_at=observed_at,
                    process_tree_killed=True,
                    active_child_process_count=0,
                    workspace_destroyed=True,
                    sandbox_terminal=True,
                    computer_terminal=True,
                    preview_shares_terminal=True,
                    human_control_terminal=True,
                    artifacts_finalized=True,
                    authority_ref="provider-attestation:e2e",
                )
                teardown = CloudM1TeardownReceipt.from_observation(
                    receipt_id="teardown-receipt:e2e",
                    plan=cloud_plan,
                    observation=teardown_observation,
                )
                self.assertTrue(teardown.clean)
                stage_receipt = teardown.as_stage_receipt(event_id="event:teardown:e2e")
            else:
                stage_receipt = CloudM1StageReceipt(
                    event_id=f"event:{index}:{stage.value}",
                    plan_id=cloud_plan.plan_id,
                    plan_fingerprint=cloud_plan.fingerprint,
                    stage=stage,
                    outcome=CloudStageOutcome.SUCCEEDED,
                    observed_at=observed_at,
                    evidence_ref=f"evidence:{index}:{stage.value}",
                    summary_code="stage_succeeded",
                )
            projection = stage_ledger.append(stage_receipt)

        self.assertEqual(projection.terminal, CloudExecutionTerminal.COMPLETED)
        self.assertIsNone(projection.next_stage)
        self.assertEqual(len(github_port.created), 1)
        self.assertTrue(github_port.created[0].draft)
        self.assertFalse(outbox.get("outbox:draft-pr:e2e").safe_dict()["auto_merge"])
        self.assertFalse(stage_ledger.safe_receipts()[-1]["raw_runtime_payload"])


if __name__ == "__main__":
    unittest.main()
