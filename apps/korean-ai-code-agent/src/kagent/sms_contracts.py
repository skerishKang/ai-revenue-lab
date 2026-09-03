from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from .contracts import ContractError
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_PHONE_LIKE_RE = re.compile(r"^\+?[0-9][0-9() .\-]{6,30}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ALLOWED_RECIPIENTS = 10_000
MAX_RUN_SENDS = 100
MAX_WORKSPACE_HOURLY_SENDS = 1000
MIN_RECIPIENT_COOLDOWN_SECONDS = 30


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    value = value.strip()
    if not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _recipient_ref(value: str) -> str:
    value = _ref(value, "recipient_ref")
    if _PHONE_LIKE_RE.fullmatch(value):
        raise ContractError("recipient_ref must be opaque and must not be a phone number")
    return value


def _sha(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise ContractError(f"{field_name} must be lowercase SHA-256")
    return value.strip().lower()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class SmsPurpose(str, Enum):
    TRANSACTIONAL = "transactional"
    ADVERTISING = "advertising"


class SmsProviderSelectionState(str, Enum):
    CANDIDATE = "candidate"
    NON_PRODUCTION_SELECTED = "non_production_selected"
    PRODUCTION_SELECTED = "production_selected"


@dataclass(frozen=True, slots=True)
class SmsProviderProfile:
    provider_ref: str
    account_ref: str
    selection_state: SmsProviderSelectionState = SmsProviderSelectionState.CANDIDATE

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_ref", _ref(self.provider_ref, "provider_ref"))
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref"))
        if not isinstance(self.selection_state, SmsProviderSelectionState):
            try:
                object.__setattr__(self, "selection_state", SmsProviderSelectionState(self.selection_state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid SMS provider selection state") from exc

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider_ref": self.provider_ref,
            "account_ref": self.account_ref,
            "selection_state": self.selection_state.value,
            "raw_provider_secret_present": False,
        }


@dataclass(frozen=True, slots=True)
class SmsSenderProfile:
    sender_ref: str
    provider_ref: str
    registration_evidence_ref: str
    provider_registered: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "sender_ref", _ref(self.sender_ref, "sender_ref"))
        object.__setattr__(self, "provider_ref", _ref(self.provider_ref, "provider_ref"))
        object.__setattr__(self, "registration_evidence_ref", _ref(self.registration_evidence_ref, "registration_evidence_ref"))
        if not isinstance(self.provider_registered, bool):
            raise ContractError("provider_registered must be bool")


@dataclass(frozen=True, slots=True)
class SmsBinding:
    binding_ref: str
    workspace_ref: str
    provider: SmsProviderProfile
    senders: tuple[SmsSenderProfile, ...]
    allowed_recipient_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_ref", _ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "workspace_ref", _ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.provider, SmsProviderProfile):
            raise ContractError("provider must be SmsProviderProfile")
        if not self.senders or not all(isinstance(v, SmsSenderProfile) for v in self.senders):
            raise ContractError("SMS binding requires trusted sender profiles")
        sender_refs = [v.sender_ref for v in self.senders]
        if len(sender_refs) != len(set(sender_refs)):
            raise ContractError("SMS sender profiles must be unique")
        if any(v.provider_ref != self.provider.provider_ref for v in self.senders):
            raise ContractError("sender provider must match binding provider")
        recipients = tuple(_recipient_ref(v) for v in self.allowed_recipient_refs)
        if not recipients or len(recipients) > MAX_ALLOWED_RECIPIENTS or len(recipients) != len(set(recipients)):
            raise ContractError("SMS recipients must be non-empty, unique and bounded")
        object.__setattr__(self, "allowed_recipient_refs", recipients)

    def sender(self, sender_ref: str) -> SmsSenderProfile | None:
        sender_ref = _ref(sender_ref, "sender_ref")
        for sender in self.senders:
            if sender.sender_ref == sender_ref:
                return sender
        return None

    def authorizes(self, *, binding_ref: str, workspace_ref: str, sender_ref: str, recipient_ref: str) -> bool:
        sender = self.sender(sender_ref)
        return (
            _ref(binding_ref, "binding_ref") == self.binding_ref
            and _ref(workspace_ref, "workspace_ref") == self.workspace_ref
            and sender is not None
            and sender.provider_registered
            and _recipient_ref(recipient_ref) in self.allowed_recipient_refs
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-sms-binding.v1",
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "provider": self.provider.safe_dict(),
            "sender_count": len(self.senders),
            "recipient_count": len(self.allowed_recipient_refs),
            "phone_numbers_present": False,
            "address_book_scraping": False,
        }


@dataclass(frozen=True, slots=True)
class SmsAdvertisingConsent:
    recipient_ref: str
    consent_ref: str
    consent_evidence_ref: str
    consented_at: datetime
    active: bool
    night_consent_ref: str | None = None
    night_consented_at: datetime | None = None
    opt_out_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipient_ref", _recipient_ref(self.recipient_ref))
        object.__setattr__(self, "consent_ref", _ref(self.consent_ref, "consent_ref"))
        object.__setattr__(self, "consent_evidence_ref", _ref(self.consent_evidence_ref, "consent_evidence_ref"))
        object.__setattr__(self, "consented_at", _aware(self.consented_at, "consented_at"))
        if not isinstance(self.active, bool):
            raise ContractError("active must be bool")
        if self.night_consent_ref is not None:
            object.__setattr__(self, "night_consent_ref", _ref(self.night_consent_ref, "night_consent_ref"))
            if self.night_consented_at is None:
                raise ContractError("night consent ref requires night consent timestamp")
        if self.night_consented_at is not None:
            object.__setattr__(self, "night_consented_at", _aware(self.night_consented_at, "night_consented_at"))
            if self.night_consent_ref is None:
                raise ContractError("night consent timestamp requires night consent ref")
        if self.opt_out_ref is not None:
            object.__setattr__(self, "opt_out_ref", _ref(self.opt_out_ref, "opt_out_ref"))

    def active_at(self, now: datetime) -> bool:
        return self.active and self.consented_at <= _aware(now, "now")

    def night_active_at(self, now: datetime) -> bool:
        current = _aware(now, "now")
        return (
            self.active_at(current)
            and self.night_consent_ref is not None
            and self.night_consented_at is not None
            and self.night_consented_at <= current
        )


@dataclass(frozen=True, slots=True)
class SmsComplianceProjection:
    scheduled_at: datetime
    sender_identity_present: bool
    advertisement_label_present: bool
    free_opt_out_present: bool
    has_promotional_content: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheduled_at", _aware(self.scheduled_at, "scheduled_at"))
        for name in ("sender_identity_present", "advertisement_label_present", "free_opt_out_present", "has_promotional_content"):
            if not isinstance(getattr(self, name), bool):
                raise ContractError(f"{name} must be bool")

    def is_night_kst(self) -> bool:
        hour = (self.scheduled_at.hour + 9) % 24
        return hour >= 21 or hour < 8

    def advertising_fields_present(self) -> bool:
        return self.sender_identity_present and self.advertisement_label_present and self.free_opt_out_present


@dataclass(frozen=True, slots=True)
class SmsRateBudget:
    budget_ref: str
    workspace_ref: str
    provider_ref: str
    run_ref: str
    run_send_count: int
    workspace_hour_send_count: int
    recipient_last_sent_at: datetime | None
    observed_at: datetime
    max_run_sends: int = MAX_RUN_SENDS
    max_workspace_hourly_sends: int = MAX_WORKSPACE_HOURLY_SENDS
    recipient_cooldown_seconds: int = MIN_RECIPIENT_COOLDOWN_SECONDS

    def __post_init__(self) -> None:
        for name in ("budget_ref", "workspace_ref", "provider_ref", "run_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        if self.recipient_last_sent_at is not None:
            object.__setattr__(self, "recipient_last_sent_at", _aware(self.recipient_last_sent_at, "recipient_last_sent_at"))
        for name in ("run_send_count", "workspace_hour_send_count", "max_run_sends", "max_workspace_hourly_sends", "recipient_cooldown_seconds"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ContractError(f"{name} must be a non-negative integer")
        if self.max_run_sends < 1 or self.max_workspace_hourly_sends < 1 or self.recipient_cooldown_seconds < MIN_RECIPIENT_COOLDOWN_SECONDS:
            raise ContractError("SMS rate-budget limits are too weak")

    def allows(self, *, workspace_ref: str, provider_ref: str, now: datetime) -> bool:
        current = _aware(now, "now")
        if _ref(workspace_ref, "workspace_ref") != self.workspace_ref or _ref(provider_ref, "provider_ref") != self.provider_ref:
            return False
        if self.observed_at > current:
            return False
        if self.run_send_count >= self.max_run_sends or self.workspace_hour_send_count >= self.max_workspace_hourly_sends:
            return False
        if self.recipient_last_sent_at is not None and current - self.recipient_last_sent_at < timedelta(seconds=self.recipient_cooldown_seconds):
            return False
        return True


@dataclass(frozen=True, slots=True)
class SmsOutboundMaterial:
    binding_ref: str
    workspace_ref: str
    provider_ref: str
    sender_ref: str
    recipient_ref: str
    purpose: SmsPurpose
    text_sha256: str
    scheduled_at: datetime
    workflow_ref: str
    template_ref: str | None = None
    template_revision_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("binding_ref", "workspace_ref", "provider_ref", "sender_ref", "workflow_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "recipient_ref", _recipient_ref(self.recipient_ref))
        if not isinstance(self.purpose, SmsPurpose):
            try:
                object.__setattr__(self, "purpose", SmsPurpose(self.purpose))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid SMS purpose") from exc
        object.__setattr__(self, "text_sha256", _sha(self.text_sha256, "text_sha256"))
        object.__setattr__(self, "scheduled_at", _aware(self.scheduled_at, "scheduled_at"))
        if self.template_ref is not None:
            object.__setattr__(self, "template_ref", _ref(self.template_ref, "template_ref"))
        if self.template_revision_ref is not None:
            object.__setattr__(self, "template_revision_ref", _ref(self.template_revision_ref, "template_revision_ref"))
        if (self.template_ref is None) != (self.template_revision_ref is None):
            raise ContractError("SMS template identity requires exact template and revision")

    @property
    def target_ref(self) -> str:
        return f"sms:{self.workspace_ref}:{self.sender_ref}:recipient:{self.recipient_ref}"

    @property
    def tool_name(self) -> str:
        return "sms.send_template" if self.template_ref is not None else "sms.send_text"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "provider_ref": self.provider_ref,
            "sender_ref": self.sender_ref,
            "recipient_ref": self.recipient_ref,
            "purpose": self.purpose.value,
            "text_sha256": self.text_sha256,
            "scheduled_at": self.scheduled_at.isoformat(),
            "workflow_ref": self.workflow_ref,
            "template_ref": self.template_ref,
            "template_revision_ref": self.template_revision_ref,
            "recipient_count": 1,
            "bulk_send": False,
        }

    @property
    def material_fingerprint(self) -> str:
        raw = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @property
    def version_ref(self) -> str:
        return f"sms-material:{self.material_fingerprint}"


@dataclass(frozen=True, slots=True)
class SmsOutboundApproval:
    approval_ref: str
    evidence_ref: str
    material_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_ref", _ref(self.approval_ref, "approval_ref"))
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "material_fingerprint", _sha(self.material_fingerprint, "material_fingerprint"))
        object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))


class SmsPreflightDecision(str, Enum):
    ALLOW = "allow"
    OUT_OF_SCOPE = "out_of_scope"
    SENDER_UNVERIFIED = "sender_unverified"
    PURPOSE_MISMATCH = "purpose_mismatch"
    CONSENT_REQUIRED = "consent_required"
    NIGHT_CONSENT_REQUIRED = "night_consent_required"
    COMPLIANCE_REQUIRED = "compliance_required"
    RATE_LIMIT = "rate_limit"
    WRONG_CONNECTOR_OR_TOOL = "wrong_connector_or_tool"
    TARGET_MISMATCH = "target_mismatch"
    APPROVAL_MISMATCH = "approval_mismatch"
    MATERIAL_CHANGED = "material_changed"
    VERSION_MISMATCH = "version_mismatch"


def sms_outbound_preflight(
    *,
    binding: SmsBinding,
    material: SmsOutboundMaterial,
    approval: SmsOutboundApproval,
    intent: ConnectorWriteIntent,
    rate_budget: SmsRateBudget,
    actor_ref: str,
    now: datetime,
    compliance: SmsComplianceProjection,
    advertising_consent: SmsAdvertisingConsent | None = None,
) -> SmsPreflightDecision:
    if not all((isinstance(binding, SmsBinding), isinstance(material, SmsOutboundMaterial), isinstance(approval, SmsOutboundApproval), isinstance(intent, ConnectorWriteIntent), isinstance(rate_budget, SmsRateBudget), isinstance(compliance, SmsComplianceProjection))):
        raise ContractError("invalid SMS preflight contract")
    current = _aware(now, "now")

    if not binding.authorizes(binding_ref=material.binding_ref, workspace_ref=material.workspace_ref, sender_ref=material.sender_ref, recipient_ref=material.recipient_ref):
        sender = binding.sender(material.sender_ref)
        if sender is not None and not sender.provider_registered:
            return SmsPreflightDecision.SENDER_UNVERIFIED
        return SmsPreflightDecision.OUT_OF_SCOPE
    if material.provider_ref != binding.provider.provider_ref:
        return SmsPreflightDecision.OUT_OF_SCOPE
    if compliance.scheduled_at != material.scheduled_at:
        return SmsPreflightDecision.MATERIAL_CHANGED
    if compliance.has_promotional_content and material.purpose is not SmsPurpose.ADVERTISING:
        return SmsPreflightDecision.PURPOSE_MISMATCH

    if material.purpose is SmsPurpose.ADVERTISING:
        if advertising_consent is None or advertising_consent.recipient_ref != material.recipient_ref or not advertising_consent.active_at(current):
            return SmsPreflightDecision.CONSENT_REQUIRED
        if not compliance.advertising_fields_present():
            return SmsPreflightDecision.COMPLIANCE_REQUIRED
        if compliance.is_night_kst() and not advertising_consent.night_active_at(current):
            return SmsPreflightDecision.NIGHT_CONSENT_REQUIRED

    if not rate_budget.allows(workspace_ref=material.workspace_ref, provider_ref=material.provider_ref, now=current):
        return SmsPreflightDecision.RATE_LIMIT
    if intent.connector_id != "sms" or intent.tool_name != material.tool_name:
        return SmsPreflightDecision.WRONG_CONNECTOR_OR_TOOL
    if intent.binding_ref != material.binding_ref or intent.target_ref != material.target_ref:
        return SmsPreflightDecision.TARGET_MISMATCH
    if intent.actor_ref != _ref(actor_ref, "actor_ref"):
        return SmsPreflightDecision.OUT_OF_SCOPE
    if intent.approval_ref != approval.approval_ref or intent.evidence_ref != approval.evidence_ref:
        return SmsPreflightDecision.APPROVAL_MISMATCH
    if approval.material_fingerprint != material.material_fingerprint or intent.payload_fingerprint != material.material_fingerprint:
        return SmsPreflightDecision.MATERIAL_CHANGED
    if intent.expected_version_ref != material.version_ref:
        return SmsPreflightDecision.VERSION_MISMATCH
    return SmsPreflightDecision.ALLOW


class SmsDeliveryState(str, Enum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SmsDeliveryEvidence:
    provider_message_ref: str
    provider_status_ref: str
    state: SmsDeliveryState
    observed_at: datetime
    evidence_ref: str
    failure_reason_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_message_ref", _ref(self.provider_message_ref, "provider_message_ref"))
        object.__setattr__(self, "provider_status_ref", _ref(self.provider_status_ref, "provider_status_ref"))
        if not isinstance(self.state, SmsDeliveryState):
            try:
                object.__setattr__(self, "state", SmsDeliveryState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid SMS delivery state") from exc
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        if self.failure_reason_ref is not None:
            object.__setattr__(self, "failure_reason_ref", _ref(self.failure_reason_ref, "failure_reason_ref"))
        if self.state is SmsDeliveryState.FAILED and self.failure_reason_ref is None:
            raise ContractError("failed SMS requires failure reason evidence")


@dataclass(frozen=True, slots=True)
class SmsOutboundReceipt:
    write_receipt: ConnectorWriteReceipt
    delivery: SmsDeliveryEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.write_receipt, ConnectorWriteReceipt) or not isinstance(self.delivery, SmsDeliveryEvidence):
            raise ContractError("invalid SMS receipt contract")
        if self.write_receipt.connector_id != "sms":
            raise ContractError("SMS receipt requires sms connector")
        if self.write_receipt.provider_operation_ref != self.delivery.provider_message_ref:
            raise ContractError("SMS delivery evidence must match exact provider message")

    def matches(self, *, material: SmsOutboundMaterial, intent: ConnectorWriteIntent) -> bool:
        return (
            self.write_receipt.binding_ref == material.binding_ref == intent.binding_ref
            and self.write_receipt.idempotency_key == intent.idempotency_key
            and self.write_receipt.target_ref == material.target_ref == intent.target_ref
            and self.write_receipt.evidence_ref == intent.evidence_ref
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-sms-receipt.v1",
            "write_receipt": self.write_receipt.safe_dict(),
            "delivery_state": self.delivery.state.value,
            "provider_message_ref": self.delivery.provider_message_ref,
            "provider_status_ref": self.delivery.provider_status_ref,
            "evidence_ref": self.delivery.evidence_ref,
            "failure_reason_ref": self.delivery.failure_reason_ref,
            "phone_number_present": False,
            "provider_acceptance_equals_delivery": False,
        }


PROVIDER_NEUTRAL_PORT = True
PRODUCTION_PROVIDER_SELECTED = False
TRUSTED_REGISTERED_SENDER_REQUIRED = True
ARBITRARY_MODEL_SENDER_SUPPORTED = False
PHONE_NUMBER_IN_MODEL_SAFE_STATE = False
PHONE_NUMBER_GENERATION_ENUMERATION_SUPPORTED = False
MIXED_CONTENT_DEFAULTS_ADVERTISING = True
NIGHT_ADVERTISING_CONSENT_REQUIRED_21_08_KST = True
ONE_RECIPIENT_PER_APPROVED_WRITE = True
AUTONOMOUS_BULK_SMS_SUPPORTED = False
MMS_V1_SUPPORTED = False
RAW_PROVIDER_SECRET_IN_B54 = False
REAL_SMS_PROVIDER_CONFIGURED = False
REAL_SMS_SEND_CONFIGURED = False
PRODUCTION_MUTATION_SUPPORTED = False
