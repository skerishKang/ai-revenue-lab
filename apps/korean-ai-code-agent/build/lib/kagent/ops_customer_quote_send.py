from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Protocol

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from .contracts import ContractError
from .ops_customer_quote import CustomerQuoteDraft
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _text(value: str, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise ContractError(f"{field_name} must be bounded non-empty text")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _sha(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class CustomerQuoteSendChannel(str, Enum):
    EMAIL = "email"
    BUSINESS_MESSAGING = "business_messaging"


def customer_quote_send_fingerprint(
    *,
    quote: CustomerQuoteDraft,
    recipient_ref: str,
    channel: CustomerQuoteSendChannel,
    subject: str,
    body: str,
) -> str:
    if not isinstance(quote, CustomerQuoteDraft):
        raise ContractError("quote must be CustomerQuoteDraft")
    recipient = _ref(recipient_ref, "recipient_ref")
    if not isinstance(channel, CustomerQuoteSendChannel):
        try:
            channel = CustomerQuoteSendChannel(channel)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid customer quote send channel") from exc
    subject = _text(subject, "subject", limit=500)
    body = _text(body, "body", limit=20_000)
    payload = {
        "action": "send_customer_quote",
        "customer_quote_id": quote.customer_quote_id,
        "quote_version": quote.version,
        "commercial_request_id": quote.commercial_request_id,
        "commercial_request_version": quote.commercial_request_version,
        "supplier_quote_id": quote.supplier_quote_id,
        "supplier_quote_version": quote.supplier_quote_version,
        "pricing_fingerprint": quote.pricing_fingerprint,
        "recipient_ref": recipient,
        "channel": channel.value,
        "subject_sha256": hashlib.sha256(subject.encode("utf-8")).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CustomerQuoteSendBinding:
    binding_id: str
    pause_id: str
    customer_quote_id: str
    quote_version: int
    pricing_fingerprint: str
    recipient_ref: str
    channel: CustomerQuoteSendChannel
    subject_sha256: str
    body_sha256: str
    action_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in ("binding_id", "pause_id", "customer_quote_id", "recipient_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.quote_version, bool) or not isinstance(self.quote_version, int) or self.quote_version < 1:
            raise ContractError("quote_version must be positive")
        object.__setattr__(self, "pricing_fingerprint", _sha(self.pricing_fingerprint, "pricing_fingerprint"))
        if not isinstance(self.channel, CustomerQuoteSendChannel):
            try:
                object.__setattr__(self, "channel", CustomerQuoteSendChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid send channel") from exc
        object.__setattr__(self, "subject_sha256", _sha(self.subject_sha256, "subject_sha256"))
        object.__setattr__(self, "body_sha256", _sha(self.body_sha256, "body_sha256"))
        object.__setattr__(self, "action_fingerprint", _sha(self.action_fingerprint, "action_fingerprint"))

    @classmethod
    def bind(
        cls,
        *,
        binding_id: str,
        pause_id: str,
        quote: CustomerQuoteDraft,
        recipient_ref: str,
        channel: CustomerQuoteSendChannel,
        subject: str,
        body: str,
    ) -> "CustomerQuoteSendBinding":
        if not isinstance(quote, CustomerQuoteDraft) or quote.approval_required is not True:
            raise ContractError("customer quote must be approval-required Draft")
        recipient = _ref(recipient_ref, "recipient_ref")
        if not isinstance(channel, CustomerQuoteSendChannel):
            channel = CustomerQuoteSendChannel(channel)
        subject_text = _text(subject, "subject", limit=500)
        body_text = _text(body, "body", limit=20_000)
        action = customer_quote_send_fingerprint(
            quote=quote,
            recipient_ref=recipient,
            channel=channel,
            subject=subject_text,
            body=body_text,
        )
        return cls(
            binding_id=binding_id,
            pause_id=pause_id,
            customer_quote_id=quote.customer_quote_id,
            quote_version=quote.version,
            pricing_fingerprint=quote.pricing_fingerprint,
            recipient_ref=recipient,
            channel=channel,
            subject_sha256=hashlib.sha256(subject_text.encode("utf-8")).hexdigest(),
            body_sha256=hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
            action_fingerprint=action,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "pause_id": self.pause_id,
            "customer_quote_id": self.customer_quote_id,
            "quote_version": self.quote_version,
            "pricing_fingerprint": self.pricing_fingerprint,
            "recipient_ref": self.recipient_ref,
            "channel": self.channel.value,
            "subject_sha256": self.subject_sha256,
            "body_sha256": self.body_sha256,
            "action_fingerprint": self.action_fingerprint,
            "raw_subject_or_body_in_binding": False,
        }


@dataclass(frozen=True, slots=True)
class CustomerQuoteSendRequest:
    request_id: str
    quote: CustomerQuoteDraft
    recipient_ref: str
    channel: CustomerQuoteSendChannel
    subject: str
    body: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _ref(self.request_id, "request_id"))
        if not isinstance(self.quote, CustomerQuoteDraft):
            raise ContractError("quote must be CustomerQuoteDraft")
        object.__setattr__(self, "recipient_ref", _ref(self.recipient_ref, "recipient_ref"))
        if not isinstance(self.channel, CustomerQuoteSendChannel):
            try:
                object.__setattr__(self, "channel", CustomerQuoteSendChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid send channel") from exc
        object.__setattr__(self, "subject", _text(self.subject, "subject", limit=500))
        object.__setattr__(self, "body", _text(self.body, "body", limit=20_000))


@dataclass(frozen=True, slots=True)
class CustomerQuoteDeliveryReceipt:
    request_id: str
    customer_quote_id: str
    quote_version: int
    connector_ref: str
    external_message_ref: str
    delivered_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("request_id", "customer_quote_id", "connector_ref", "external_message_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.quote_version, bool) or not isinstance(self.quote_version, int) or self.quote_version < 1:
            raise ContractError("quote_version must be positive")
        object.__setattr__(self, "delivered_at", _aware(self.delivered_at, "delivered_at"))


class CustomerQuoteOutboundPort(Protocol):
    def send(self, request: CustomerQuoteSendRequest) -> CustomerQuoteDeliveryReceipt:
        ...


class UnconfiguredCustomerQuoteOutboundPort:
    def send(self, request: CustomerQuoteSendRequest) -> CustomerQuoteDeliveryReceipt:
        raise ContractError("customer quote outbound adapter is not configured")


class DeterministicFakeCustomerQuoteOutboundPort:
    def __init__(self, *, delivered_at: datetime) -> None:
        self.delivered_at = _aware(delivered_at, "delivered_at")
        self.sent: list[CustomerQuoteSendRequest] = []

    def send(self, request: CustomerQuoteSendRequest) -> CustomerQuoteDeliveryReceipt:
        if not isinstance(request, CustomerQuoteSendRequest):
            raise ContractError("request must be CustomerQuoteSendRequest")
        self.sent.append(request)
        digest = hashlib.sha256(
            f"{request.request_id}:{request.quote.pricing_fingerprint}:{request.recipient_ref}:{request.channel.value}".encode("utf-8")
        ).hexdigest()[:24]
        return CustomerQuoteDeliveryReceipt(
            request_id=request.request_id,
            customer_quote_id=request.quote.customer_quote_id,
            quote_version=request.quote.version,
            connector_ref="fake_customer_quote_connector",
            external_message_ref=f"fake_customer_quote:{digest}",
            delivered_at=self.delivered_at,
        )


class ApprovalGatedCustomerQuoteSender:
    def __init__(self, port: CustomerQuoteOutboundPort | None = None) -> None:
        self.port = port or UnconfiguredCustomerQuoteOutboundPort()

    def send(
        self,
        *,
        request: CustomerQuoteSendRequest,
        binding: CustomerQuoteSendBinding,
        decision: VerifiedApprovalDecision,
    ) -> CustomerQuoteDeliveryReceipt:
        if not isinstance(request, CustomerQuoteSendRequest):
            raise ContractError("request must be CustomerQuoteSendRequest")
        if not isinstance(binding, CustomerQuoteSendBinding):
            raise ContractError("binding must be CustomerQuoteSendBinding")
        if not isinstance(decision, VerifiedApprovalDecision):
            raise ContractError("decision must be canonical VerifiedApprovalDecision")
        if decision.outcome is not ApprovalOutcome.APPROVED:
            raise ContractError("customer quote send requires approved canonical decision")
        if decision.pause_id != binding.pause_id:
            raise ContractError("approval decision does not belong to customer quote binding")
        expected = CustomerQuoteSendBinding.bind(
            binding_id=binding.binding_id,
            pause_id=binding.pause_id,
            quote=request.quote,
            recipient_ref=request.recipient_ref,
            channel=request.channel,
            subject=request.subject,
            body=request.body,
        )
        if expected != binding:
            raise ContractError("customer quote send request changed after approval binding")
        receipt = self.port.send(request)
        if (
            receipt.request_id != request.request_id
            or receipt.customer_quote_id != request.quote.customer_quote_id
            or receipt.quote_version != request.quote.version
        ):
            raise ContractError("customer quote delivery receipt correlation mismatch")
        return receipt


REAL_CUSTOMER_QUOTE_SEND_CONFIGURED = False
