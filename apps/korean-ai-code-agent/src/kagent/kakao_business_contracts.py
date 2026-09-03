from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from .contracts import ContractError
from .security import redact_secrets

MAX_KAKAO_TEXT_CHARS = 20_000
MAX_KAKAO_VARIABLES = 64
MAX_KAKAO_BUTTONS = 10
MAX_KAKAO_LINKS = 10

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TEMPLATE_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _optional_ref(value: str | None, field_name: str) -> str | None:
    return None if value is None else _safe_ref(value, field_name)


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be lowercase SHA-256")
    return value.strip().lower()


def _bounded_text(value: str, field_name: str, limit: int = MAX_KAKAO_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = redact_secrets(value.strip())
    if not normalized or len(normalized) > limit:
        raise ContractError(f"{field_name} must contain 1..{limit} characters")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _unique_refs(values: tuple[str, ...], field_name: str, limit: int) -> tuple[str, ...]:
    normalized = tuple(_safe_ref(v, field_name) for v in values)
    if len(normalized) > limit or len(normalized) != len(set(normalized)):
        raise ContractError(f"{field_name} must be unique and bounded")
    return normalized


class KakaoBusinessProduct(str, Enum):
    ALIMTALK = "alimtalk"
    BRAND_MESSAGE = "brand_message"
    CHANNEL_MESSAGE = "channel_message"
    CS_TALK = "cs_talk"


class KakaoMessagePurpose(str, Enum):
    INFORMATIONAL = "informational"
    ADVERTISING = "advertising"
    CUSTOMER_SUPPORT = "customer_support"


class KakaoTemplateReviewState(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class KakaoBusinessBinding:
    binding_ref: str
    workspace_ref: str
    business_account_ref: str
    channel_ref: str
    dealer_ref: str
    enabled_products: tuple[KakaoBusinessProduct, ...]
    allowed_recipient_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("binding_ref", "workspace_ref", "business_account_ref", "channel_ref", "dealer_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        products: list[KakaoBusinessProduct] = []
        for value in self.enabled_products:
            try:
                products.append(value if isinstance(value, KakaoBusinessProduct) else KakaoBusinessProduct(value))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Kakao business product") from exc
        if not products or len(products) != len(set(products)):
            raise ContractError("enabled_products must be non-empty and unique")
        object.__setattr__(self, "enabled_products", tuple(products))
        recipients = _unique_refs(self.allowed_recipient_refs, "recipient_ref", 10_000)
        if not recipients:
            raise ContractError("Kakao business binding requires explicit recipients")
        object.__setattr__(self, "allowed_recipient_refs", recipients)

    def authorizes(self, *, binding_ref: str, workspace_ref: str, product: KakaoBusinessProduct, recipient_ref: str) -> bool:
        return (
            _safe_ref(binding_ref, "binding_ref") == self.binding_ref
            and _safe_ref(workspace_ref, "workspace_ref") == self.workspace_ref
            and product in self.enabled_products
            and _safe_ref(recipient_ref, "recipient_ref") in self.allowed_recipient_refs
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-kakao-business-binding.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "business_account_ref": self.business_account_ref,
            "channel_ref": self.channel_ref,
            "dealer_ref": self.dealer_ref,
            "enabled_products": [p.value for p in self.enabled_products],
            "recipient_count": len(self.allowed_recipient_refs),
            "personal_kakaotalk_session_supported": False,
            "address_book_scraping_supported": False,
            "raw_credential_present": False,
        }


@dataclass(frozen=True, slots=True)
class KakaoTemplateApproval:
    template_ref: str
    template_revision_ref: str
    review_state: KakaoTemplateReviewState
    approved_variable_keys: tuple[str, ...]
    reviewed_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_ref", _safe_ref(self.template_ref, "template_ref"))
        object.__setattr__(self, "template_revision_ref", _safe_ref(self.template_revision_ref, "template_revision_ref"))
        if not isinstance(self.review_state, KakaoTemplateReviewState):
            try:
                object.__setattr__(self, "review_state", KakaoTemplateReviewState(self.review_state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Kakao template review state") from exc
        keys: list[str] = []
        for key in self.approved_variable_keys:
            if not isinstance(key, str) or not _TEMPLATE_KEY_RE.fullmatch(key):
                raise ContractError("Kakao template variable key is invalid")
            keys.append(key)
        if len(keys) > MAX_KAKAO_VARIABLES or len(keys) != len(set(keys)):
            raise ContractError("Kakao template variable keys must be unique and bounded")
        object.__setattr__(self, "approved_variable_keys", tuple(keys))
        object.__setattr__(self, "reviewed_at", _aware(self.reviewed_at, "reviewed_at"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))

    @property
    def approved(self) -> bool:
        return self.review_state is KakaoTemplateReviewState.APPROVED


class KakaoAdvertisingEligibilityKind(str, Enum):
    CHANNEL_FRIEND = "channel_friend"
    MARKETING_CONSENT = "marketing_consent"


@dataclass(frozen=True, slots=True)
class KakaoAdvertisingEligibility:
    recipient_ref: str
    kind: KakaoAdvertisingEligibilityKind
    evidence_ref: str
    observed_at: datetime
    active: bool = True
    consent_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipient_ref", _safe_ref(self.recipient_ref, "recipient_ref"))
        if not isinstance(self.kind, KakaoAdvertisingEligibilityKind):
            try:
                object.__setattr__(self, "kind", KakaoAdvertisingEligibilityKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Kakao advertising eligibility kind") from exc
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if not isinstance(self.active, bool):
            raise ContractError("advertising eligibility active must be bool")
        object.__setattr__(self, "consent_ref", _optional_ref(self.consent_ref, "consent_ref"))
        if self.kind is KakaoAdvertisingEligibilityKind.MARKETING_CONSENT and self.consent_ref is None:
            raise ContractError("marketing-consent eligibility requires consent_ref")
        if self.kind is KakaoAdvertisingEligibilityKind.CHANNEL_FRIEND and self.consent_ref is not None:
            raise ContractError("channel-friend eligibility does not carry marketing consent authority")

    def active_at(self, now: datetime) -> bool:
        current = _aware(now, "now")
        return self.active and self.observed_at <= current


@dataclass(frozen=True, slots=True)
class KakaoCsSession:
    session_ref: str
    recipient_ref: str
    user_initiated: bool
    opened_at: datetime
    evidence_ref: str
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_ref", _safe_ref(self.session_ref, "session_ref"))
        object.__setattr__(self, "recipient_ref", _safe_ref(self.recipient_ref, "recipient_ref"))
        if not isinstance(self.user_initiated, bool):
            raise ContractError("user_initiated must be bool")
        object.__setattr__(self, "opened_at", _aware(self.opened_at, "opened_at"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        if self.closed_at is not None:
            closed = _aware(self.closed_at, "closed_at")
            if closed < self.opened_at:
                raise ContractError("CS session cannot close before opening")
            object.__setattr__(self, "closed_at", closed)

    def active_at(self, now: datetime) -> bool:
        current = _aware(now, "now")
        return self.user_initiated and self.opened_at <= current and (self.closed_at is None or current < self.closed_at)


@dataclass(frozen=True, slots=True)
class KakaoComplianceProjection:
    sender_name_present: bool
    sender_contact_present: bool
    opt_out_present: bool
    advertisement_label_present: bool
    has_promotional_content: bool
    scheduled_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "sender_name_present",
            "sender_contact_present",
            "opt_out_present",
            "advertisement_label_present",
            "has_promotional_content",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ContractError(f"{name} must be bool")
        object.__setattr__(self, "scheduled_at", _aware(self.scheduled_at, "scheduled_at"))

    def advertising_window_allowed(self) -> bool:
        # Current Kakao channel/message-ad guidance restricts advertising sends
        # from 21:00 to 08:00 Korea time. Convert from UTC without relying on
        # host tzdata: Korea Standard Time is UTC+09:00.
        hour = (self.scheduled_at.hour + 9) % 24
        return 8 <= hour < 21

    def advertising_requirements_met(self) -> bool:
        return (
            self.advertisement_label_present
            and self.sender_name_present
            and self.sender_contact_present
            and self.opt_out_present
            and self.advertising_window_allowed()
        )


@dataclass(frozen=True, slots=True)
class KakaoOutboundMaterial:
    binding_ref: str
    workspace_ref: str
    product: KakaoBusinessProduct
    purpose: KakaoMessagePurpose
    recipient_ref: str
    text_sha256: str
    template_ref: str | None = None
    template_revision_ref: str | None = None
    variable_keys: tuple[str, ...] = ()
    variables_sha256: str | None = None
    buttons_sha256: str | None = None
    links_sha256: str | None = None
    attachment_sha256: str | None = None
    cs_session_ref: str | None = None
    workflow_ref: str = "kakao-business"

    def __post_init__(self) -> None:
        for name in ("binding_ref", "workspace_ref", "recipient_ref", "workflow_ref"):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        if not isinstance(self.product, KakaoBusinessProduct):
            try:
                object.__setattr__(self, "product", KakaoBusinessProduct(self.product))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Kakao product") from exc
        if not isinstance(self.purpose, KakaoMessagePurpose):
            try:
                object.__setattr__(self, "purpose", KakaoMessagePurpose(self.purpose))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Kakao message purpose") from exc
        object.__setattr__(self, "text_sha256", _sha256(self.text_sha256, "text_sha256"))
        object.__setattr__(self, "template_ref", _optional_ref(self.template_ref, "template_ref"))
        object.__setattr__(self, "template_revision_ref", _optional_ref(self.template_revision_ref, "template_revision_ref"))
        keys: list[str] = []
        for key in self.variable_keys:
            if not isinstance(key, str) or not _TEMPLATE_KEY_RE.fullmatch(key):
                raise ContractError("Kakao variable key is invalid")
            keys.append(key)
        if len(keys) > MAX_KAKAO_VARIABLES or len(keys) != len(set(keys)):
            raise ContractError("Kakao variable keys must be unique and bounded")
        object.__setattr__(self, "variable_keys", tuple(keys))
        for name in ("variables_sha256", "buttons_sha256", "links_sha256", "attachment_sha256"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _sha256(value, name))
        object.__setattr__(self, "cs_session_ref", _optional_ref(self.cs_session_ref, "cs_session_ref"))

        if self.product is KakaoBusinessProduct.ALIMTALK:
            if self.purpose is not KakaoMessagePurpose.INFORMATIONAL:
                raise ContractError("AlimTalk is informational-only in Padiem")
            if self.template_ref is None or self.template_revision_ref is None:
                raise ContractError("AlimTalk requires exact approved template identity")
            if self.cs_session_ref is not None:
                raise ContractError("AlimTalk cannot carry CS session identity")
        elif self.product in {KakaoBusinessProduct.BRAND_MESSAGE, KakaoBusinessProduct.CHANNEL_MESSAGE}:
            if self.purpose is not KakaoMessagePurpose.ADVERTISING:
                raise ContractError("Brand/Channel Message must be advertising purpose")
            if self.cs_session_ref is not None:
                raise ContractError("advertising message cannot carry CS session")
        elif self.product is KakaoBusinessProduct.CS_TALK:
            if self.purpose is not KakaoMessagePurpose.CUSTOMER_SUPPORT or self.cs_session_ref is None:
                raise ContractError("CS Talk requires customer-support purpose and exact session")
            if self.template_ref is not None or self.template_revision_ref is not None:
                raise ContractError("CS Talk does not reuse AlimTalk template authority")

    @property
    def target_ref(self) -> str:
        return f"kakao:{self.workspace_ref}:{self.product.value}:recipient:{self.recipient_ref}"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "product": self.product.value,
            "purpose": self.purpose.value,
            "recipient_ref": self.recipient_ref,
            "text_sha256": self.text_sha256,
            "template_ref": self.template_ref,
            "template_revision_ref": self.template_revision_ref,
            "variable_keys": list(self.variable_keys),
            "variables_sha256": self.variables_sha256,
            "buttons_sha256": self.buttons_sha256,
            "links_sha256": self.links_sha256,
            "attachment_sha256": self.attachment_sha256,
            "cs_session_ref": self.cs_session_ref,
            "workflow_ref": self.workflow_ref,
            "recipient_count": 1,
            "bulk_send": False,
        }

    @property
    def material_fingerprint(self) -> str:
        raw = json.dumps(self.canonical_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @property
    def version_ref(self) -> str:
        return f"kakao-material:{self.material_fingerprint}"


@dataclass(frozen=True, slots=True)
class KakaoOutboundApproval:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _safe_ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "material_fingerprint", _sha256(self.material_fingerprint, "material_fingerprint"))
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))


class KakaoOutboundPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    PRODUCT_DISABLED = "product_disabled"
    PURPOSE_MISMATCH = "purpose_mismatch"
    TEMPLATE_NOT_APPROVED = "template_not_approved"
    TEMPLATE_MISMATCH = "template_mismatch"
    VARIABLE_KEYS_MISMATCH = "variable_keys_mismatch"
    CONSENT_REQUIRED = "consent_required"
    COMPLIANCE_REQUIRED = "compliance_required"
    QUIET_HOURS = "quiet_hours"
    CS_SESSION_REQUIRED = "cs_session_required"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    VERSION_BINDING_MISMATCH = "version_binding_mismatch"


def kakao_outbound_preflight(
    *,
    scope: KakaoBusinessBinding,
    material: KakaoOutboundMaterial,
    approval: KakaoOutboundApproval,
    intent: ConnectorWriteIntent,
    actor_ref: str,
    now: datetime,
    template: KakaoTemplateApproval | None = None,
    advertising_eligibility: KakaoAdvertisingEligibility | None = None,
    compliance: KakaoComplianceProjection | None = None,
    cs_session: KakaoCsSession | None = None,
) -> KakaoOutboundPreflightDecision:
    if not all(
        (
            isinstance(scope, KakaoBusinessBinding),
            isinstance(material, KakaoOutboundMaterial),
            isinstance(approval, KakaoOutboundApproval),
            isinstance(intent, ConnectorWriteIntent),
        )
    ):
        raise ContractError("invalid Kakao outbound preflight contract")

    current = _aware(now, "now")
    if not scope.authorizes(
        binding_ref=material.binding_ref,
        workspace_ref=material.workspace_ref,
        product=material.product,
        recipient_ref=material.recipient_ref,
    ):
        return KakaoOutboundPreflightDecision.OUT_OF_SCOPE

    if material.product is KakaoBusinessProduct.ALIMTALK:
        if material.purpose is not KakaoMessagePurpose.INFORMATIONAL:
            return KakaoOutboundPreflightDecision.PURPOSE_MISMATCH
        if template is None or not isinstance(template, KakaoTemplateApproval) or not template.approved:
            return KakaoOutboundPreflightDecision.TEMPLATE_NOT_APPROVED
        if (
            template.template_ref != material.template_ref
            or template.template_revision_ref != material.template_revision_ref
        ):
            return KakaoOutboundPreflightDecision.TEMPLATE_MISMATCH
        if tuple(sorted(template.approved_variable_keys)) != tuple(sorted(material.variable_keys)):
            return KakaoOutboundPreflightDecision.VARIABLE_KEYS_MISMATCH
        if compliance is None or not isinstance(compliance, KakaoComplianceProjection):
            return KakaoOutboundPreflightDecision.COMPLIANCE_REQUIRED
        if compliance.has_promotional_content:
            return KakaoOutboundPreflightDecision.PURPOSE_MISMATCH

    elif material.product in {KakaoBusinessProduct.BRAND_MESSAGE, KakaoBusinessProduct.CHANNEL_MESSAGE}:
        if material.purpose is not KakaoMessagePurpose.ADVERTISING:
            return KakaoOutboundPreflightDecision.PURPOSE_MISMATCH
        if advertising_eligibility is None or not isinstance(advertising_eligibility, KakaoAdvertisingEligibility):
            return KakaoOutboundPreflightDecision.CONSENT_REQUIRED
        if (
            advertising_eligibility.recipient_ref != material.recipient_ref
            or not advertising_eligibility.active_at(current)
        ):
            return KakaoOutboundPreflightDecision.CONSENT_REQUIRED
        if (
            material.product is KakaoBusinessProduct.CHANNEL_MESSAGE
            and advertising_eligibility.kind is not KakaoAdvertisingEligibilityKind.CHANNEL_FRIEND
        ):
            return KakaoOutboundPreflightDecision.CONSENT_REQUIRED
        if compliance is None or not isinstance(compliance, KakaoComplianceProjection):
            return KakaoOutboundPreflightDecision.COMPLIANCE_REQUIRED
        if not compliance.advertisement_label_present or not compliance.sender_name_present or not compliance.sender_contact_present or not compliance.opt_out_present:
            return KakaoOutboundPreflightDecision.COMPLIANCE_REQUIRED
        if not compliance.advertising_window_allowed():
            return KakaoOutboundPreflightDecision.QUIET_HOURS

    elif material.product is KakaoBusinessProduct.CS_TALK:
        if material.purpose is not KakaoMessagePurpose.CUSTOMER_SUPPORT:
            return KakaoOutboundPreflightDecision.PURPOSE_MISMATCH
        if cs_session is None or not isinstance(cs_session, KakaoCsSession):
            return KakaoOutboundPreflightDecision.CS_SESSION_REQUIRED
        if (
            cs_session.session_ref != material.cs_session_ref
            or cs_session.recipient_ref != material.recipient_ref
            or not cs_session.active_at(current)
        ):
            return KakaoOutboundPreflightDecision.CS_SESSION_REQUIRED

    if intent.connector_id != "kakao-business" or intent.tool_name != f"kakao.{material.product.value}.send":
        return KakaoOutboundPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return KakaoOutboundPreflightDecision.TARGET_MISMATCH
    if intent.actor_ref != _safe_ref(actor_ref, "actor_ref"):
        return KakaoOutboundPreflightDecision.OUT_OF_SCOPE
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return KakaoOutboundPreflightDecision.APPROVAL_MISMATCH
    if approval.material_fingerprint != material.material_fingerprint or intent.payload_fingerprint != material.material_fingerprint:
        return KakaoOutboundPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return KakaoOutboundPreflightDecision.VERSION_BINDING_MISMATCH
    return KakaoOutboundPreflightDecision.ALLOW


class KakaoDeliveryState(str, Enum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class KakaoDeliveryEvidence:
    request_ref: str
    provider_status_ref: str
    state: KakaoDeliveryState
    observed_at: datetime
    evidence_ref: str
    failure_reason_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_ref", _safe_ref(self.request_ref, "request_ref"))
        object.__setattr__(self, "provider_status_ref", _safe_ref(self.provider_status_ref, "provider_status_ref"))
        if not isinstance(self.state, KakaoDeliveryState):
            try:
                object.__setattr__(self, "state", KakaoDeliveryState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Kakao delivery state") from exc
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "evidence_ref", _safe_ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "failure_reason_ref", _optional_ref(self.failure_reason_ref, "failure_reason_ref"))
        if self.state is KakaoDeliveryState.FAILED and self.failure_reason_ref is None:
            raise ContractError("failed Kakao delivery requires failure reason evidence")


@dataclass(frozen=True, slots=True)
class KakaoOutboundReceipt:
    write_receipt: ConnectorWriteReceipt
    delivery: KakaoDeliveryEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.write_receipt, ConnectorWriteReceipt):
            raise ContractError("write_receipt must be ConnectorWriteReceipt")
        if not isinstance(self.delivery, KakaoDeliveryEvidence):
            raise ContractError("delivery must be KakaoDeliveryEvidence")
        if self.write_receipt.connector_id != "kakao-business":
            raise ContractError("Kakao receipt requires kakao-business connector")
        if self.write_receipt.provider_operation_ref != self.delivery.request_ref:
            raise ContractError("Kakao delivery evidence must correlate exact provider request")

    def matches(self, *, material: KakaoOutboundMaterial, intent: ConnectorWriteIntent) -> bool:
        return (
            self.write_receipt.binding_ref == material.binding_ref == intent.binding_ref
            and self.write_receipt.idempotency_key == intent.idempotency_key
            and self.write_receipt.target_ref == material.target_ref == intent.target_ref
            and self.write_receipt.evidence_ref == intent.evidence_ref
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-kakao-business-receipt.v1",
            "write_receipt": self.write_receipt.safe_dict(),
            "delivery": {
                "request_ref": self.delivery.request_ref,
                "provider_status_ref": self.delivery.provider_status_ref,
                "state": self.delivery.state.value,
                "observed_at": self.delivery.observed_at.isoformat().replace("+00:00", "Z"),
                "evidence_ref": self.delivery.evidence_ref,
                "failure_reason_ref": self.delivery.failure_reason_ref,
            },
            "provider_acceptance_equals_final_delivery": False,
            "model_text_counts_as_delivery": False,
        }


OFFICIAL_KAKAO_BUSINESS_ONLY = True
PERSONAL_KAKAOTALK_SESSION_AUTOMATION_SUPPORTED = False
ADDRESS_BOOK_SCRAPING_SUPPORTED = False
ALIMTALK_APPROVED_TEMPLATE_REQUIRED = True
MIXED_CONTENT_DEFAULTS_ADVERTISING = True
ADVERTISING_QUIET_HOURS_START_KST = 21
ADVERTISING_QUIET_HOURS_END_KST = 8
BULK_UNAPPROVED_SEND_SUPPORTED = False
RAW_KAKAO_CREDENTIAL_IN_B54 = False
REAL_KAKAO_BUSINESS_CONFIGURED = False
REAL_KAKAO_SEND_CONFIGURED = False
PRODUCTION_MUTATION_SUPPORTED = False
