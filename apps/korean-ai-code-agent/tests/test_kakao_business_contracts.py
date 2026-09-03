from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError
from kagent.kakao_business_contracts import (
    ADDRESS_BOOK_SCRAPING_SUPPORTED,
    ADVERTISING_QUIET_HOURS_END_KST,
    ADVERTISING_QUIET_HOURS_START_KST,
    ALIMTALK_APPROVED_TEMPLATE_REQUIRED,
    BULK_UNAPPROVED_SEND_SUPPORTED,
    MIXED_CONTENT_DEFAULTS_ADVERTISING,
    OFFICIAL_KAKAO_BUSINESS_ONLY,
    PERSONAL_KAKAOTALK_SESSION_AUTOMATION_SUPPORTED,
    PRODUCTION_MUTATION_SUPPORTED,
    RAW_KAKAO_CREDENTIAL_IN_B54,
    REAL_KAKAO_BUSINESS_CONFIGURED,
    REAL_KAKAO_SEND_CONFIGURED,
    KakaoAdvertisingEligibility,
    KakaoAdvertisingEligibilityKind,
    KakaoBusinessBinding,
    KakaoBusinessProduct,
    KakaoComplianceProjection,
    KakaoCsSession,
    KakaoDeliveryEvidence,
    KakaoDeliveryState,
    KakaoMessagePurpose,
    KakaoOutboundApproval,
    KakaoOutboundMaterial,
    KakaoOutboundPreflightDecision,
    KakaoOutboundReceipt,
    KakaoTemplateApproval,
    KakaoTemplateReviewState,
    kakao_outbound_preflight,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)  # 10:00 KST
QUIET = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)  # 22:00 KST
H = "a" * 64


def scope(*products: KakaoBusinessProduct) -> KakaoBusinessBinding:
    return KakaoBusinessBinding(
        binding_ref="binding-kakao",
        workspace_ref="ws-1",
        business_account_ref="biz-1",
        channel_ref="channel-1",
        dealer_ref="dealer-1",
        enabled_products=products or (KakaoBusinessProduct.ALIMTALK,),
        allowed_recipient_refs=("recipient-1", "recipient-2"),
    )


def template() -> KakaoTemplateApproval:
    return KakaoTemplateApproval(
        template_ref="tpl-order",
        template_revision_ref="rev-7",
        review_state=KakaoTemplateReviewState.APPROVED,
        approved_variable_keys=("order_id", "delivery_date"),
        reviewed_at=NOW,
        evidence_ref="evidence-template",
    )


def material(product: KakaoBusinessProduct) -> KakaoOutboundMaterial:
    if product is KakaoBusinessProduct.ALIMTALK:
        return KakaoOutboundMaterial(
            binding_ref="binding-kakao",
            workspace_ref="ws-1",
            product=product,
            purpose=KakaoMessagePurpose.INFORMATIONAL,
            recipient_ref="recipient-1",
            text_sha256=H,
            template_ref="tpl-order",
            template_revision_ref="rev-7",
            variable_keys=("order_id", "delivery_date"),
            variables_sha256=H,
        )
    if product in {KakaoBusinessProduct.BRAND_MESSAGE, KakaoBusinessProduct.CHANNEL_MESSAGE}:
        return KakaoOutboundMaterial(
            binding_ref="binding-kakao",
            workspace_ref="ws-1",
            product=product,
            purpose=KakaoMessagePurpose.ADVERTISING,
            recipient_ref="recipient-1",
            text_sha256=H,
            buttons_sha256=H,
            links_sha256=H,
        )
    return KakaoOutboundMaterial(
        binding_ref="binding-kakao",
        workspace_ref="ws-1",
        product=product,
        purpose=KakaoMessagePurpose.CUSTOMER_SUPPORT,
        recipient_ref="recipient-1",
        text_sha256=H,
        cs_session_ref="cs-1",
    )


def approval(m: KakaoOutboundMaterial) -> KakaoOutboundApproval:
    return KakaoOutboundApproval(
        approval_ref="approval-1",
        evidence_ref="evidence-1",
        material_fingerprint=m.material_fingerprint,
        approved_at=NOW,
    )


def intent(m: KakaoOutboundMaterial) -> ConnectorWriteIntent:
    return ConnectorWriteIntent(
        connector_id="kakao-business",
        binding_ref=m.binding_ref,
        actor_ref="actor-1",
        tool_name=f"kakao.{m.product.value}.send",
        target_ref=m.target_ref,
        payload_fingerprint=m.material_fingerprint,
        idempotency_key="idem-1",
        approval_ref="approval-1",
        evidence_ref="evidence-1",
        requested_at=NOW,
        expected_version_ref=m.version_ref,
    )


def advertising_eligibility(
    *,
    kind: KakaoAdvertisingEligibilityKind = KakaoAdvertisingEligibilityKind.MARKETING_CONSENT,
    active: bool = True,
) -> KakaoAdvertisingEligibility:
    return KakaoAdvertisingEligibility(
        recipient_ref="recipient-1",
        kind=kind,
        evidence_ref="eligibility-evidence",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        active=active,
        consent_ref="consent-1" if kind is KakaoAdvertisingEligibilityKind.MARKETING_CONSENT else None,
    )


def compliance(at: datetime = NOW, *, promotional: bool = True) -> KakaoComplianceProjection:
    return KakaoComplianceProjection(
        sender_name_present=True,
        sender_contact_present=True,
        opt_out_present=True,
        advertisement_label_present=True,
        has_promotional_content=promotional,
        scheduled_at=at,
    )


def cs_session(*, initiated: bool = True) -> KakaoCsSession:
    return KakaoCsSession(
        session_ref="cs-1",
        recipient_ref="recipient-1",
        user_initiated=initiated,
        opened_at=datetime(2026, 9, 3, 0, 30, tzinfo=UTC),
        evidence_ref="cs-evidence",
    )


def test_repository_non_authority_constants_fail_closed() -> None:
    assert OFFICIAL_KAKAO_BUSINESS_ONLY is True
    assert PERSONAL_KAKAOTALK_SESSION_AUTOMATION_SUPPORTED is False
    assert ADDRESS_BOOK_SCRAPING_SUPPORTED is False
    assert ALIMTALK_APPROVED_TEMPLATE_REQUIRED is True
    assert MIXED_CONTENT_DEFAULTS_ADVERTISING is True
    assert ADVERTISING_QUIET_HOURS_START_KST == 21
    assert ADVERTISING_QUIET_HOURS_END_KST == 8
    assert BULK_UNAPPROVED_SEND_SUPPORTED is False
    assert RAW_KAKAO_CREDENTIAL_IN_B54 is False
    assert REAL_KAKAO_BUSINESS_CONFIGURED is False
    assert REAL_KAKAO_SEND_CONFIGURED is False
    assert PRODUCTION_MUTATION_SUPPORTED is False


def test_business_binding_is_exact_and_does_not_expose_recipients() -> None:
    s = scope(KakaoBusinessProduct.ALIMTALK, KakaoBusinessProduct.BRAND_MESSAGE)
    assert s.authorizes(
        binding_ref="binding-kakao",
        workspace_ref="ws-1",
        product=KakaoBusinessProduct.ALIMTALK,
        recipient_ref="recipient-1",
    )
    assert not s.authorizes(
        binding_ref="binding-kakao",
        workspace_ref="ws-1",
        product=KakaoBusinessProduct.CS_TALK,
        recipient_ref="recipient-1",
    )
    assert not s.authorizes(
        binding_ref="binding-kakao",
        workspace_ref="ws-1",
        product=KakaoBusinessProduct.ALIMTALK,
        recipient_ref="recipient-404",
    )
    safe = s.safe_dict()
    assert safe["recipient_count"] == 2
    assert "allowed_recipient_refs" not in safe
    assert safe["raw_credential_present"] is False


def test_alimtalk_requires_information_purpose_and_exact_template() -> None:
    with pytest.raises(ContractError):
        KakaoOutboundMaterial(
            binding_ref="binding-kakao",
            workspace_ref="ws-1",
            product=KakaoBusinessProduct.ALIMTALK,
            purpose=KakaoMessagePurpose.ADVERTISING,
            recipient_ref="recipient-1",
            text_sha256=H,
            template_ref="tpl-order",
            template_revision_ref="rev-7",
        )
    with pytest.raises(ContractError):
        KakaoOutboundMaterial(
            binding_ref="binding-kakao",
            workspace_ref="ws-1",
            product=KakaoBusinessProduct.ALIMTALK,
            purpose=KakaoMessagePurpose.INFORMATIONAL,
            recipient_ref="recipient-1",
            text_sha256=H,
        )


def test_alimtalk_preflight_allows_only_approved_exact_template_and_keys() -> None:
    m = material(KakaoBusinessProduct.ALIMTALK)
    decision = kakao_outbound_preflight(
        scope=scope(KakaoBusinessProduct.ALIMTALK),
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        template=template(),
        compliance=compliance(promotional=False),
    )
    assert decision is KakaoOutboundPreflightDecision.ALLOW

    pending = KakaoTemplateApproval(
        template_ref="tpl-order",
        template_revision_ref="rev-7",
        review_state=KakaoTemplateReviewState.PENDING,
        approved_variable_keys=("order_id", "delivery_date"),
        reviewed_at=NOW,
        evidence_ref="pending-evidence",
    )
    assert kakao_outbound_preflight(
        scope=scope(KakaoBusinessProduct.ALIMTALK),
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        template=pending,
    ) is KakaoOutboundPreflightDecision.TEMPLATE_NOT_APPROVED

    changed = KakaoTemplateApproval(
        template_ref="tpl-order",
        template_revision_ref="rev-8",
        review_state=KakaoTemplateReviewState.APPROVED,
        approved_variable_keys=("order_id", "delivery_date"),
        reviewed_at=NOW,
        evidence_ref="changed-evidence",
    )
    assert kakao_outbound_preflight(
        scope=scope(KakaoBusinessProduct.ALIMTALK),
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        template=changed,
    ) is KakaoOutboundPreflightDecision.TEMPLATE_MISMATCH


def test_alimtalk_rejects_promotional_content_even_with_approved_template() -> None:
    m = material(KakaoBusinessProduct.ALIMTALK)
    assert kakao_outbound_preflight(
        scope=scope(KakaoBusinessProduct.ALIMTALK),
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        template=template(),
        compliance=compliance(promotional=True),
    ) is KakaoOutboundPreflightDecision.PURPOSE_MISMATCH


def test_advertising_requires_active_eligibility_required_fields_and_allowed_window() -> None:
    m = material(KakaoBusinessProduct.BRAND_MESSAGE)
    s = scope(KakaoBusinessProduct.BRAND_MESSAGE)
    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(),
        compliance=compliance(NOW),
    ) is KakaoOutboundPreflightDecision.ALLOW

    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(active=False),
        compliance=compliance(NOW),
    ) is KakaoOutboundPreflightDecision.CONSENT_REQUIRED

    missing_optout = KakaoComplianceProjection(
        sender_name_present=True,
        sender_contact_present=True,
        opt_out_present=False,
        advertisement_label_present=True,
        has_promotional_content=True,
        scheduled_at=NOW,
    )
    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(),
        compliance=missing_optout,
    ) is KakaoOutboundPreflightDecision.COMPLIANCE_REQUIRED

    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(),
        compliance=compliance(QUIET),
    ) is KakaoOutboundPreflightDecision.QUIET_HOURS


def test_channel_message_requires_channel_friend_eligibility() -> None:
    m = material(KakaoBusinessProduct.CHANNEL_MESSAGE)
    s = scope(KakaoBusinessProduct.CHANNEL_MESSAGE)
    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(
            kind=KakaoAdvertisingEligibilityKind.MARKETING_CONSENT
        ),
        compliance=compliance(NOW),
    ) is KakaoOutboundPreflightDecision.CONSENT_REQUIRED

    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(
            kind=KakaoAdvertisingEligibilityKind.CHANNEL_FRIEND
        ),
        compliance=compliance(NOW),
    ) is KakaoOutboundPreflightDecision.ALLOW


def test_advertising_window_is_08_to_before_21_kst() -> None:
    assert compliance(datetime(2026, 9, 2, 23, 0, tzinfo=UTC)).advertising_window_allowed()  # 08 KST
    assert compliance(datetime(2026, 9, 3, 11, 59, tzinfo=UTC)).advertising_window_allowed()  # 20:59 KST
    assert not compliance(datetime(2026, 9, 3, 12, 0, tzinfo=UTC)).advertising_window_allowed()  # 21 KST
    assert not compliance(datetime(2026, 9, 2, 22, 59, tzinfo=UTC)).advertising_window_allowed()  # 07:59 KST


def test_cs_talk_requires_exact_user_initiated_active_session() -> None:
    m = material(KakaoBusinessProduct.CS_TALK)
    s = scope(KakaoBusinessProduct.CS_TALK)
    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        cs_session=cs_session(),
    ) is KakaoOutboundPreflightDecision.ALLOW

    assert kakao_outbound_preflight(
        scope=s,
        material=m,
        approval=approval(m),
        intent=intent(m),
        actor_ref="actor-1",
        now=NOW,
        cs_session=cs_session(initiated=False),
    ) is KakaoOutboundPreflightDecision.CS_SESSION_REQUIRED


def test_material_changes_invalidate_approval_and_intent() -> None:
    original = material(KakaoBusinessProduct.BRAND_MESSAGE)
    changed = KakaoOutboundMaterial(
        binding_ref=original.binding_ref,
        workspace_ref=original.workspace_ref,
        product=original.product,
        purpose=original.purpose,
        recipient_ref=original.recipient_ref,
        text_sha256="b" * 64,
        buttons_sha256=original.buttons_sha256,
        links_sha256=original.links_sha256,
    )
    assert original.material_fingerprint != changed.material_fingerprint
    assert kakao_outbound_preflight(
        scope=scope(KakaoBusinessProduct.BRAND_MESSAGE),
        material=changed,
        approval=approval(original),
        intent=intent(original),
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(),
        compliance=compliance(NOW),
    ) is KakaoOutboundPreflightDecision.MATERIAL_CHANGED


def test_wrong_connector_and_version_fail_closed() -> None:
    m = material(KakaoBusinessProduct.BRAND_MESSAGE)
    a = approval(m)
    base = intent(m)
    wrong = ConnectorWriteIntent(
        connector_id="telegram",
        binding_ref=base.binding_ref,
        actor_ref=base.actor_ref,
        tool_name=base.tool_name,
        target_ref=base.target_ref,
        payload_fingerprint=base.payload_fingerprint,
        idempotency_key=base.idempotency_key,
        approval_ref=base.approval_ref,
        evidence_ref=base.evidence_ref,
        requested_at=base.requested_at,
        expected_version_ref=base.expected_version_ref,
    )
    assert kakao_outbound_preflight(
        scope=scope(KakaoBusinessProduct.BRAND_MESSAGE),
        material=m,
        approval=a,
        intent=wrong,
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(),
        compliance=compliance(NOW),
    ) is KakaoOutboundPreflightDecision.WRONG_CONNECTOR_OR_TOOL

    wrong_version = ConnectorWriteIntent(
        connector_id=base.connector_id,
        binding_ref=base.binding_ref,
        actor_ref=base.actor_ref,
        tool_name=base.tool_name,
        target_ref=base.target_ref,
        payload_fingerprint=base.payload_fingerprint,
        idempotency_key=base.idempotency_key,
        approval_ref=base.approval_ref,
        evidence_ref=base.evidence_ref,
        requested_at=base.requested_at,
        expected_version_ref="kakao-material:" + "b" * 64,
    )
    assert kakao_outbound_preflight(
        scope=scope(KakaoBusinessProduct.BRAND_MESSAGE),
        material=m,
        approval=a,
        intent=wrong_version,
        actor_ref="actor-1",
        now=NOW,
        advertising_eligibility=advertising_eligibility(),
        compliance=compliance(NOW),
    ) is KakaoOutboundPreflightDecision.VERSION_BINDING_MISMATCH


def test_delivery_receipt_correlates_provider_request_and_write_intent() -> None:
    m = material(KakaoBusinessProduct.ALIMTALK)
    i = intent(m)
    receipt = ConnectorWriteReceipt(
        receipt_ref="receipt-1",
        connector_id="kakao-business",
        binding_ref=m.binding_ref,
        idempotency_key=i.idempotency_key,
        provider_operation_ref="request-1",
        target_ref=m.target_ref,
        committed_at=NOW,
        evidence_ref=i.evidence_ref,
        version_ref=m.version_ref,
    )
    delivery = KakaoDeliveryEvidence(
        request_ref="request-1",
        provider_status_ref="status-1",
        state=KakaoDeliveryState.DELIVERED,
        observed_at=NOW,
        evidence_ref="delivery-evidence",
    )
    combined = KakaoOutboundReceipt(write_receipt=receipt, delivery=delivery)
    assert combined.matches(material=m, intent=i)
    safe = combined.safe_dict()
    assert safe["model_text_counts_as_delivery"] is False
    assert safe["provider_acceptance_equals_final_delivery"] is False


def test_failed_delivery_requires_failure_reason_and_exact_request() -> None:
    with pytest.raises(ContractError):
        KakaoDeliveryEvidence(
            request_ref="request-1",
            provider_status_ref="status-1",
            state=KakaoDeliveryState.FAILED,
            observed_at=NOW,
            evidence_ref="delivery-evidence",
        )

    receipt = ConnectorWriteReceipt(
        receipt_ref="receipt-1",
        connector_id="kakao-business",
        binding_ref="binding-kakao",
        idempotency_key="idem-1",
        provider_operation_ref="request-1",
        target_ref="kakao:ws-1:alimtalk:recipient:recipient-1",
        committed_at=NOW,
        evidence_ref="evidence-1",
    )
    delivery = KakaoDeliveryEvidence(
        request_ref="request-2",
        provider_status_ref="status-2",
        state=KakaoDeliveryState.FAILED,
        observed_at=NOW,
        evidence_ref="delivery-evidence",
        failure_reason_ref="failure-1",
    )
    with pytest.raises(ContractError):
        KakaoOutboundReceipt(write_receipt=receipt, delivery=delivery)
