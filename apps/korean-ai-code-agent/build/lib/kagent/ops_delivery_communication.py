from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from .contracts import ContractError
from .ops_communications import (
    CommunicationChannel,
    CommunicationConnectorPort,
    CommunicationDeliveryReceipt,
    CommunicationSendRequest,
    UnconfiguredCommunicationConnector,
)
from .ops_contracts import BusinessObjectKind, EvidenceOrigin, WorkflowEvidenceRecord
from .ops_delivery_tracking import (
    DeliveryExceptionKind,
    DeliveryExceptionProjection,
    DeliveryFollowupDraft,
    DeliveryTrackingCoordinator,
)
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} has invalid reference syntax")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain raw credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def followup_message_sha256(message: str) -> str:
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > 4000:
        raise ContractError("message must be bounded and non-empty")
    return hashlib.sha256(message.strip().encode("utf-8")).hexdigest()


def delivery_followup_fingerprint(
    *,
    workspace_id: str,
    delivery_id: str,
    delivery_version: int,
    supplier_id: str,
    recipient_ref: str,
    channel: CommunicationChannel,
    message_sha256: str,
) -> str:
    if not isinstance(channel, CommunicationChannel):
        raise ContractError("channel must be CommunicationChannel")
    if isinstance(delivery_version, bool) or not isinstance(delivery_version, int) or delivery_version < 1:
        raise ContractError("delivery_version must be positive")
    digest = message_sha256.strip().lower() if isinstance(message_sha256, str) else ""
    if not _SHA256_RE.fullmatch(digest):
        raise ContractError("message_sha256 must be a SHA-256 digest")
    payload = {
        "action": "send_delivery_followup",
        "workspace_id": _ref(workspace_id, "workspace_id"),
        "delivery_id": _ref(delivery_id, "delivery_id"),
        "delivery_version": delivery_version,
        "supplier_id": _ref(supplier_id, "supplier_id"),
        "recipient_ref": _ref(recipient_ref, "recipient_ref"),
        "channel": channel.value,
        "message_sha256": digest,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DeliveryFollowupApprovalBinding:
    binding_id: str
    pause_id: str
    workspace_id: str
    delivery_id: str
    delivery_version: int
    supplier_id: str
    recipient_ref: str
    channel: CommunicationChannel
    message_sha256: str
    action_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "pause_id",
            "workspace_id",
            "delivery_id",
            "supplier_id",
            "recipient_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.delivery_version, bool) or not isinstance(self.delivery_version, int) or self.delivery_version < 1:
            raise ContractError("delivery_version must be positive")
        if not isinstance(self.channel, CommunicationChannel):
            raise ContractError("channel must be CommunicationChannel")
        message_digest = self.message_sha256.strip().lower() if isinstance(self.message_sha256, str) else ""
        action_digest = self.action_fingerprint.strip().lower() if isinstance(self.action_fingerprint, str) else ""
        if not _SHA256_RE.fullmatch(message_digest) or not _SHA256_RE.fullmatch(action_digest):
            raise ContractError("binding hashes must be SHA-256 digests")
        expected = delivery_followup_fingerprint(
            workspace_id=self.workspace_id,
            delivery_id=self.delivery_id,
            delivery_version=self.delivery_version,
            supplier_id=self.supplier_id,
            recipient_ref=self.recipient_ref,
            channel=self.channel,
            message_sha256=message_digest,
        )
        if action_digest != expected:
            raise ContractError("action_fingerprint does not match delivery followup binding")
        object.__setattr__(self, "message_sha256", message_digest)
        object.__setattr__(self, "action_fingerprint", action_digest)

    @classmethod
    def bind(
        cls,
        *,
        binding_id: str,
        pause_id: str,
        workspace_id: str,
        projection: DeliveryExceptionProjection,
        draft: DeliveryFollowupDraft,
        recipient_ref: str,
        channel: CommunicationChannel,
    ) -> "DeliveryFollowupApprovalBinding":
        _require_projection_draft_match(projection, draft)
        message_digest = followup_message_sha256(draft.message)
        fingerprint = delivery_followup_fingerprint(
            workspace_id=workspace_id,
            delivery_id=projection.delivery_id,
            delivery_version=projection.delivery_version,
            supplier_id=projection.supplier_id,
            recipient_ref=recipient_ref,
            channel=channel,
            message_sha256=message_digest,
        )
        return cls(
            binding_id=binding_id,
            pause_id=pause_id,
            workspace_id=workspace_id,
            delivery_id=projection.delivery_id,
            delivery_version=projection.delivery_version,
            supplier_id=projection.supplier_id,
            recipient_ref=recipient_ref,
            channel=channel,
            message_sha256=message_digest,
            action_fingerprint=fingerprint,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "pause_id": self.pause_id,
            "workspace_id": self.workspace_id,
            "delivery_id": self.delivery_id,
            "delivery_version": self.delivery_version,
            "supplier_id": self.supplier_id,
            "recipient_ref": self.recipient_ref,
            "channel": self.channel.value,
            "message_sha256": self.message_sha256,
            "action_fingerprint": self.action_fingerprint,
            "approval_authority": "p01_verified_decision",
        }


def _require_projection_draft_match(
    projection: DeliveryExceptionProjection,
    draft: DeliveryFollowupDraft,
) -> None:
    if not isinstance(projection, DeliveryExceptionProjection):
        raise ContractError("projection must be DeliveryExceptionProjection")
    if not isinstance(draft, DeliveryFollowupDraft):
        raise ContractError("draft must be DeliveryFollowupDraft")
    if not projection.actionable or projection.kind is DeliveryExceptionKind.NONE:
        raise ContractError("delivery followup requires an actionable exception")
    if not draft.requires_approval:
        raise ContractError("delivery followup must require approval")
    if (
        draft.delivery_id != projection.delivery_id
        or draft.delivery_version != projection.delivery_version
        or draft.supplier_id != projection.supplier_id
        or draft.exception_kind is not projection.kind
    ):
        raise ContractError("delivery followup draft does not match projected exception")


class DeliveryFollowupCommunicationBridge:
    def __init__(
        self,
        coordinator: DeliveryTrackingCoordinator,
        connector: CommunicationConnectorPort | None = None,
    ) -> None:
        if not isinstance(coordinator, DeliveryTrackingCoordinator):
            raise ContractError("coordinator must be DeliveryTrackingCoordinator")
        self.coordinator = coordinator
        self.connector = connector or UnconfiguredCommunicationConnector()

    def build_send_request(
        self,
        *,
        request_id: str,
        projection: DeliveryExceptionProjection,
        draft: DeliveryFollowupDraft,
        binding: DeliveryFollowupApprovalBinding,
        decision: VerifiedApprovalDecision,
        subject: str = "납기 확인 요청",
    ) -> CommunicationSendRequest:
        _require_projection_draft_match(projection, draft)
        if not isinstance(binding, DeliveryFollowupApprovalBinding):
            raise ContractError("binding must be DeliveryFollowupApprovalBinding")
        if not isinstance(decision, VerifiedApprovalDecision):
            raise ContractError("decision must be canonical VerifiedApprovalDecision")
        if decision.outcome is not ApprovalOutcome.APPROVED:
            raise ContractError("delivery followup requires an approved canonical decision")
        if decision.pause_id != binding.pause_id:
            raise ContractError("approval decision does not belong to delivery followup binding")
        if binding.delivery_id != projection.delivery_id or binding.delivery_version != projection.delivery_version:
            raise ContractError("approval binding delivery version mismatch")
        if binding.supplier_id != projection.supplier_id:
            raise ContractError("approval binding supplier mismatch")
        if binding.message_sha256 != followup_message_sha256(draft.message):
            raise ContractError("approved followup message changed after approval binding")

        latest = self.coordinator.latest(
            workspace_id=binding.workspace_id,
            delivery_id=projection.delivery_id,
        )
        if latest.version != projection.delivery_version:
            raise ContractError("delivery followup approval is stale because delivery has a newer version")
        if latest.supplier_id != projection.supplier_id:
            raise ContractError("delivery supplier changed after approval binding")

        return CommunicationSendRequest(
            request_id=request_id,
            workspace_id=binding.workspace_id,
            channel=binding.channel,
            recipient_ref=binding.recipient_ref,
            subject=subject,
            body=draft.message,
            target_kind=BusinessObjectKind.DELIVERY_COMMITMENT,
            target_id=projection.delivery_id,
            target_version=projection.delivery_version,
            action_fingerprint=binding.action_fingerprint,
            approval_id=decision.decision_id,
        )

    def send_approved(self, request: CommunicationSendRequest) -> CommunicationDeliveryReceipt:
        if not isinstance(request, CommunicationSendRequest):
            raise ContractError("request must be CommunicationSendRequest")
        if request.target_kind is not BusinessObjectKind.DELIVERY_COMMITMENT:
            raise ContractError("delivery bridge only sends delivery commitment communications")
        return self.connector.send(request)

    @staticmethod
    def receipt_evidence(
        *,
        evidence_id: str,
        workflow_id: str,
        request: CommunicationSendRequest,
        receipt: CommunicationDeliveryReceipt,
        recorded_at: datetime,
    ) -> WorkflowEvidenceRecord:
        if not isinstance(request, CommunicationSendRequest):
            raise ContractError("request must be CommunicationSendRequest")
        if not isinstance(receipt, CommunicationDeliveryReceipt):
            raise ContractError("receipt must be CommunicationDeliveryReceipt")
        if request.request_id != receipt.request_id:
            raise ContractError("communication receipt does not match request")
        recorded_at = _aware(recorded_at, "recorded_at")
        return WorkflowEvidenceRecord(
            evidence_id=evidence_id,
            workspace_id=request.workspace_id,
            workflow_id=workflow_id,
            object_kind=BusinessObjectKind.DELIVERY_COMMITMENT,
            object_id=request.target_id,
            object_version=request.target_version,
            origin=EvidenceOrigin.CONNECTOR_RESULT,
            source_ref=receipt.external_message_ref,
            summary="Approved delivery follow-up was accepted by the configured business communication connector.",
            recorded_at=recorded_at,
            authoritative=True,
            metadata=(
                ("request_id", request.request_id),
                ("connector_id", receipt.connector_id),
                ("action_fingerprint", request.action_fingerprint),
            ),
        )


REAL_DELIVERY_FOLLOWUP_SEND_CONFIGURED = False
