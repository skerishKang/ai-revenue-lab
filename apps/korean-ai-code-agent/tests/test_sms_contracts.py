from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError
from kagent.sms_contracts import (
    ARBITRARY_MODEL_SENDER_SUPPORTED,
    AUTONOMOUS_BULK_SMS_SUPPORTED,
    MMS_V1_SUPPORTED,
    MIXED_CONTENT_DEFAULTS_ADVERTISING,
    NIGHT_ADVERTISING_CONSENT_REQUIRED_21_08_KST,
    ONE_RECIPIENT_PER_APPROVED_WRITE,
    PHONE_NUMBER_GENERATION_ENUMERATION_SUPPORTED,
    PHONE_NUMBER_IN_MODEL_SAFE_STATE,
    PRODUCTION_MUTATION_SUPPORTED,
    PRODUCTION_PROVIDER_SELECTED,
    PROVIDER_NEUTRAL_PORT,
    RAW_PROVIDER_SECRET_IN_B54,
    REAL_SMS_PROVIDER_CONFIGURED,
    REAL_SMS_SEND_CONFIGURED,
    TRUSTED_REGISTERED_SENDER_REQUIRED,
    SmsAdvertisingConsent,
    SmsBinding,
    SmsComplianceProjection,
    SmsDeliveryEvidence,
    SmsDeliveryState,
    SmsOutboundApproval,
    SmsOutboundMaterial,
    SmsOutboundReceipt,
    SmsPreflightDecision,
    SmsProviderProfile,
    SmsProviderSelectionState,
    SmsPurpose,
    SmsRateBudget,
    SmsSenderProfile,
    sms_outbound_preflight,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)  # 10:00 KST
NIGHT = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)  # 22:00 KST
H = "a" * 64


def provider() -> SmsProviderProfile:
    return SmsProviderProfile(
        provider_ref="provider-1",
        account_ref="account-1",
        selection_state=SmsProviderSelectionState.CANDIDATE,
    )


def sender(*, registered: bool = True) -> SmsSenderProfile:
    return SmsSenderProfile(
        sender_ref="sender-1",
        provider_ref="provider-1",
        registration_evidence_ref="sender-evidence",
        provider_registered=registered,
    )


def binding(*, registered: bool = True) -> SmsBinding:
    return SmsBinding(
        binding_ref="binding-sms",
        workspace_ref="ws-1",
        provider=provider(),
        senders=(sender(registered=registered),),
        allowed_recipient_refs=("recipient-1", "recipient-2"),
    )


def material(*, purpose: SmsPurpose = SmsPurpose.TRANSACTIONAL, scheduled_at: datetime = NOW, template: bool = False) -> SmsOutboundMaterial:
    return SmsOutboundMaterial(
        binding_ref="binding-sms",
        workspace_ref="ws-1",
        provider_ref="provider-1",
        sender_ref="sender-1",
        recipient_ref="recipient-1",
        purpose=purpose,
        text_sha256=H,
        scheduled_at=scheduled_at,
        workflow_ref="workflow-1",
        template_ref="tpl-1" if template else None,
        template_revision_ref="tpl-rev-1" if template else None,
    )


def approval(m: SmsOutboundMaterial) -> SmsOutboundApproval:
    return SmsOutboundApproval(
        approval_ref="approval-1",
        evidence_ref="evidence-1",
        material_fingerprint=m.material_fingerprint,
        approved_at=NOW,
    )


def intent(m: SmsOutboundMaterial) -> ConnectorWriteIntent:
    return ConnectorWriteIntent(
        connector_id="sms",
        binding_ref=m.binding_ref,
        actor_ref="actor-1",
        tool_name=m.tool_name,
        target_ref=m.target_ref,
        payload_fingerprint=m.material_fingerprint,
        idempotency_key="idem-1",
        approval_ref="approval-1",
        evidence_ref="evidence-1",
        requested_at=NOW,
        expected_version_ref=m.version_ref,
    )


def compliance(*, scheduled_at: datetime = NOW, promotional: bool = False, ad_fields: bool = True) -> SmsComplianceProjection:
    return SmsComplianceProjection(
        scheduled_at=scheduled_at,
        sender_identity_present=ad_fields,
        advertisement_label_present=ad_fields,
        free_opt_out_present=ad_fields,
        has_promotional_content=promotional,
    )


def consent(*, night: bool = False, active: bool = True) -> SmsAdvertisingConsent:
    return SmsAdvertisingConsent(
        recipient_ref="recipient-1",
        consent_ref="consent-1",
        consent_evidence_ref="consent-evidence",
        consented_at=datetime(2026, 1, 1, tzinfo=UTC),
        active=active,
        night_consent_ref="night-consent-1" if night else None,
        night_consented_at=datetime(2026, 1, 1, tzinfo=UTC) if night else None,
        opt_out_ref="080-optout-1",
    )


def budget(*, run_count: int = 0, hourly_count: int = 0, last_sent: datetime | None = None) -> SmsRateBudget:
    return SmsRateBudget(
        budget_ref="budget-1",
        workspace_ref="ws-1",
        provider_ref="provider-1",
        run_ref="run-1",
        run_send_count=run_count,
        workspace_hour_send_count=hourly_count,
        recipient_last_sent_at=last_sent,
        observed_at=NOW,
    )


class SmsContractTests(unittest.TestCase):
    def test_repository_non_authority_constants(self) -> None:
        self.assertTrue(PROVIDER_NEUTRAL_PORT)
        self.assertFalse(PRODUCTION_PROVIDER_SELECTED)
        self.assertTrue(TRUSTED_REGISTERED_SENDER_REQUIRED)
        self.assertFalse(ARBITRARY_MODEL_SENDER_SUPPORTED)
        self.assertFalse(PHONE_NUMBER_IN_MODEL_SAFE_STATE)
        self.assertFalse(PHONE_NUMBER_GENERATION_ENUMERATION_SUPPORTED)
        self.assertTrue(MIXED_CONTENT_DEFAULTS_ADVERTISING)
        self.assertTrue(NIGHT_ADVERTISING_CONSENT_REQUIRED_21_08_KST)
        self.assertTrue(ONE_RECIPIENT_PER_APPROVED_WRITE)
        self.assertFalse(AUTONOMOUS_BULK_SMS_SUPPORTED)
        self.assertFalse(MMS_V1_SUPPORTED)
        self.assertFalse(RAW_PROVIDER_SECRET_IN_B54)
        self.assertFalse(REAL_SMS_PROVIDER_CONFIGURED)
        self.assertFalse(REAL_SMS_SEND_CONFIGURED)
        self.assertFalse(PRODUCTION_MUTATION_SUPPORTED)

    def test_phone_numbers_cannot_be_used_as_recipient_refs(self) -> None:
        with self.assertRaises(ContractError):
            SmsBinding(
                binding_ref="binding-sms",
                workspace_ref="ws-1",
                provider=provider(),
                senders=(sender(),),
                allowed_recipient_refs=("010-1234-5678",),
            )
        with self.assertRaises(ContractError):
            SmsOutboundMaterial(
                binding_ref="binding-sms",
                workspace_ref="ws-1",
                provider_ref="provider-1",
                sender_ref="sender-1",
                recipient_ref="+821012345678",
                purpose=SmsPurpose.TRANSACTIONAL,
                text_sha256=H,
                scheduled_at=NOW,
                workflow_ref="workflow-1",
            )

    def test_binding_requires_registered_sender_and_exact_recipient(self) -> None:
        m = material()
        self.assertTrue(binding().authorizes(
            binding_ref=m.binding_ref,
            workspace_ref=m.workspace_ref,
            sender_ref=m.sender_ref,
            recipient_ref=m.recipient_ref,
        ))
        self.assertFalse(binding(registered=False).authorizes(
            binding_ref=m.binding_ref,
            workspace_ref=m.workspace_ref,
            sender_ref=m.sender_ref,
            recipient_ref=m.recipient_ref,
        ))
        safe = binding().safe_dict()
        self.assertFalse(safe["phone_numbers_present"])
        self.assertNotIn("allowed_recipient_refs", safe)

    def test_transactional_send_allows_non_promotional_content(self) -> None:
        m = material()
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=m, approval=approval(m), intent=intent(m),
                rate_budget=budget(), actor_ref="actor-1", now=NOW,
                compliance=compliance(promotional=False),
            ),
            SmsPreflightDecision.ALLOW,
        )

    def test_mixed_promotional_content_cannot_hide_as_transactional(self) -> None:
        m = material(purpose=SmsPurpose.TRANSACTIONAL)
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=m, approval=approval(m), intent=intent(m),
                rate_budget=budget(), actor_ref="actor-1", now=NOW,
                compliance=compliance(promotional=True),
            ),
            SmsPreflightDecision.PURPOSE_MISMATCH,
        )

    def test_advertising_requires_consent_and_compliance_fields(self) -> None:
        m = material(purpose=SmsPurpose.ADVERTISING)
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=m, approval=approval(m), intent=intent(m),
                rate_budget=budget(), actor_ref="actor-1", now=NOW,
                compliance=compliance(promotional=True), advertising_consent=None,
            ),
            SmsPreflightDecision.CONSENT_REQUIRED,
        )
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=m, approval=approval(m), intent=intent(m),
                rate_budget=budget(), actor_ref="actor-1", now=NOW,
                compliance=compliance(promotional=True, ad_fields=False), advertising_consent=consent(),
            ),
            SmsPreflightDecision.COMPLIANCE_REQUIRED,
        )
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=m, approval=approval(m), intent=intent(m),
                rate_budget=budget(), actor_ref="actor-1", now=NOW,
                compliance=compliance(promotional=True), advertising_consent=consent(),
            ),
            SmsPreflightDecision.ALLOW,
        )

    def test_night_advertising_requires_separate_night_consent(self) -> None:
        m = material(purpose=SmsPurpose.ADVERTISING, scheduled_at=NIGHT)
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=m, approval=approval(m), intent=intent(m),
                rate_budget=budget(), actor_ref="actor-1", now=NOW,
                compliance=compliance(scheduled_at=NIGHT, promotional=True), advertising_consent=consent(night=False),
            ),
            SmsPreflightDecision.NIGHT_CONSENT_REQUIRED,
        )
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=m, approval=approval(m), intent=intent(m),
                rate_budget=budget(), actor_ref="actor-1", now=NOW,
                compliance=compliance(scheduled_at=NIGHT, promotional=True), advertising_consent=consent(night=True),
            ),
            SmsPreflightDecision.ALLOW,
        )

    def test_rate_budget_blocks_caps_and_recipient_cooldown(self) -> None:
        m = material()
        for constrained in (
            budget(run_count=100),
            budget(hourly_count=1000),
            budget(last_sent=NOW - timedelta(seconds=5)),
        ):
            self.assertIs(
                sms_outbound_preflight(
                    binding=binding(), material=m, approval=approval(m), intent=intent(m),
                    rate_budget=constrained, actor_ref="actor-1", now=NOW,
                    compliance=compliance(),
                ),
                SmsPreflightDecision.RATE_LIMIT,
            )

    def test_template_identity_changes_material_and_tool(self) -> None:
        plain = material(template=False)
        templated = material(template=True)
        self.assertEqual(plain.tool_name, "sms.send_text")
        self.assertEqual(templated.tool_name, "sms.send_template")
        self.assertNotEqual(plain.material_fingerprint, templated.material_fingerprint)
        with self.assertRaises(ContractError):
            SmsOutboundMaterial(
                binding_ref="binding-sms", workspace_ref="ws-1", provider_ref="provider-1",
                sender_ref="sender-1", recipient_ref="recipient-1", purpose=SmsPurpose.TRANSACTIONAL,
                text_sha256=H, scheduled_at=NOW, workflow_ref="workflow-1", template_ref="tpl-only",
            )

    def test_material_change_and_wrong_connector_fail_closed(self) -> None:
        original = material()
        changed = SmsOutboundMaterial(
            binding_ref=original.binding_ref, workspace_ref=original.workspace_ref,
            provider_ref=original.provider_ref, sender_ref=original.sender_ref,
            recipient_ref=original.recipient_ref, purpose=original.purpose,
            text_sha256="b" * 64, scheduled_at=original.scheduled_at,
            workflow_ref=original.workflow_ref,
        )
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=changed, approval=approval(original), intent=intent(original),
                rate_budget=budget(), actor_ref="actor-1", now=NOW, compliance=compliance(),
            ),
            SmsPreflightDecision.MATERIAL_CHANGED,
        )
        base = intent(original)
        wrong = ConnectorWriteIntent(
            connector_id="telegram", binding_ref=base.binding_ref, actor_ref=base.actor_ref,
            tool_name=base.tool_name, target_ref=base.target_ref,
            payload_fingerprint=base.payload_fingerprint, idempotency_key=base.idempotency_key,
            approval_ref=base.approval_ref, evidence_ref=base.evidence_ref,
            requested_at=base.requested_at, expected_version_ref=base.expected_version_ref,
        )
        self.assertIs(
            sms_outbound_preflight(
                binding=binding(), material=original, approval=approval(original), intent=wrong,
                rate_budget=budget(), actor_ref="actor-1", now=NOW, compliance=compliance(),
            ),
            SmsPreflightDecision.WRONG_CONNECTOR_OR_TOOL,
        )

    def test_delivery_evidence_distinguishes_accepted_delivered_failed_unknown(self) -> None:
        self.assertEqual(
            {state.value for state in SmsDeliveryState},
            {"accepted", "delivered", "failed", "unknown"},
        )
        with self.assertRaises(ContractError):
            SmsDeliveryEvidence(
                provider_message_ref="msg-1", provider_status_ref="status-1",
                state=SmsDeliveryState.FAILED, observed_at=NOW, evidence_ref="delivery-evidence",
            )

    def test_receipt_correlates_exact_provider_message_and_hides_phone(self) -> None:
        m = material()
        i = intent(m)
        receipt = ConnectorWriteReceipt(
            receipt_ref="receipt-1", connector_id="sms", binding_ref=m.binding_ref,
            idempotency_key=i.idempotency_key, provider_operation_ref="msg-1",
            target_ref=m.target_ref, committed_at=NOW, evidence_ref=i.evidence_ref,
            version_ref=m.version_ref,
        )
        delivery = SmsDeliveryEvidence(
            provider_message_ref="msg-1", provider_status_ref="status-1",
            state=SmsDeliveryState.DELIVERED, observed_at=NOW,
            evidence_ref="delivery-evidence",
        )
        combined = SmsOutboundReceipt(write_receipt=receipt, delivery=delivery)
        self.assertTrue(combined.matches(material=m, intent=i))
        self.assertFalse(combined.safe_dict()["phone_number_present"])
        self.assertFalse(combined.safe_dict()["provider_acceptance_equals_delivery"])

        wrong = SmsDeliveryEvidence(
            provider_message_ref="msg-2", provider_status_ref="status-2",
            state=SmsDeliveryState.UNKNOWN, observed_at=NOW,
            evidence_ref="delivery-evidence-2",
        )
        with self.assertRaises(ContractError):
            SmsOutboundReceipt(write_receipt=receipt, delivery=wrong)


if __name__ == "__main__":
    unittest.main()
