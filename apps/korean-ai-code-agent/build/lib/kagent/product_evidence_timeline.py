from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class ProductEvidenceEventKind(str, Enum):
    OBJECT_VERSION_CREATED = "object_version_created"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    COMMUNICATION_SENT = "communication_sent"
    COMMUNICATION_RECEIVED = "communication_received"
    DELIVERY_EXCEPTION_OBSERVED = "delivery_exception_observed"
    PILOT_METRIC_OBSERVED = "pilot_metric_observed"
    CLOUD_DISPATCH_ENQUEUED = "cloud_dispatch_enqueued"
    CLOUD_DISPATCH_ACKNOWLEDGED = "cloud_dispatch_acknowledged"
    CANCELLATION_REQUESTED = "cancellation_requested"
    VERIFIED_DIFF_RECORDED = "verified_diff_recorded"
    DRAFT_PR_PLANNED = "draft_pr_planned"
    DRAFT_PR_SUBMITTED = "draft_pr_submitted"


def _id(value: str, field_name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or not _SAFE_ID_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain raw credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sha256(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ProductEvidenceEvent:
    event_id: str
    timeline_id: str
    sequence: int
    kind: ProductEvidenceEventKind
    workspace_id: str
    workflow_id: str
    subject_kind: str
    subject_id: str
    subject_version: int | None
    occurred_at: datetime
    evidence_refs: tuple[str, ...] = ()
    actor_ref: str | None = None
    reason_code: str | None = None
    previous_event_sha256: str | None = None
    event_sha256: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "timeline_id",
            "workspace_id",
            "workflow_id",
            "subject_kind",
            "subject_id",
        ):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or not 1 <= self.sequence <= 10_000_000:
            raise ContractError("sequence must be between 1 and 10000000")
        if not isinstance(self.kind, ProductEvidenceEventKind):
            raise ContractError("kind must be ProductEvidenceEventKind")
        if self.subject_version is not None and (
            isinstance(self.subject_version, bool)
            or not isinstance(self.subject_version, int)
            or not 1 <= self.subject_version <= 1_000_000
        ):
            raise ContractError("subject_version must be positive or None")
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > 32:
            raise ContractError("evidence_refs must be a bounded tuple")
        evidence_refs = tuple(_id(item, "evidence_ref") for item in self.evidence_refs)
        if len(set(evidence_refs)) != len(evidence_refs):
            raise ContractError("evidence_refs must be unique")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        if self.actor_ref is not None:
            object.__setattr__(self, "actor_ref", _id(self.actor_ref, "actor_ref"))
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", _id(self.reason_code, "reason_code"))
        if self.sequence == 1:
            if self.previous_event_sha256 is not None:
                raise ContractError("first event cannot have previous_event_sha256")
        else:
            if self.previous_event_sha256 is None:
                raise ContractError("non-first event requires previous_event_sha256")
            object.__setattr__(
                self,
                "previous_event_sha256",
                _sha256(self.previous_event_sha256, "previous_event_sha256"),
            )
        calculated = self.calculate_sha256()
        if self.event_sha256:
            supplied = _sha256(self.event_sha256, "event_sha256")
            if supplied != calculated:
                raise ContractError("event_sha256 does not match event content")
        object.__setattr__(self, "event_sha256", calculated)

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timeline_id": self.timeline_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "workspace_id": self.workspace_id,
            "workflow_id": self.workflow_id,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "occurred_at": self.occurred_at.isoformat(),
            "evidence_refs": list(self.evidence_refs),
            "actor_ref": self.actor_ref,
            "reason_code": self.reason_code,
            "previous_event_sha256": self.previous_event_sha256,
        }

    def calculate_sha256(self) -> str:
        encoded = json.dumps(
            self._hash_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            **self._hash_payload(),
            "contract_version": "claw-product-evidence-event.v1",
            "event_sha256": self.event_sha256,
            "raw_payload_stored": False,
            "communication_body_stored": False,
            "raw_diff_stored": False,
            "task_prompt_stored": False,
            "tool_arguments_stored": False,
            "hidden_reasoning_stored": False,
            "control_plane_authoritative_audit": False,
        }


class InMemoryProductEvidenceTimeline:
    """Append-only product evidence projection, not Control Plane audit authority."""

    def __init__(self, *, timeline_id: str, workspace_id: str) -> None:
        self.timeline_id = _id(timeline_id, "timeline_id")
        self.workspace_id = _id(workspace_id, "workspace_id")
        self._events: list[ProductEvidenceEvent] = []
        self._by_id: dict[str, ProductEvidenceEvent] = {}

    @property
    def next_sequence(self) -> int:
        return len(self._events) + 1

    @property
    def last_event_sha256(self) -> str | None:
        return self._events[-1].event_sha256 if self._events else None

    def append(self, event: ProductEvidenceEvent) -> ProductEvidenceEvent:
        if not isinstance(event, ProductEvidenceEvent):
            raise ContractError("event must be ProductEvidenceEvent")
        if event.timeline_id != self.timeline_id or event.workspace_id != self.workspace_id:
            raise ContractError("event belongs to another timeline or workspace")
        existing = self._by_id.get(event.event_id)
        if existing is not None:
            if existing == event:
                return existing
            raise ContractError("event_id replay conflicts with stored event")
        if event.sequence != self.next_sequence:
            raise ContractError("timeline sequence must be contiguous")
        if event.previous_event_sha256 != self.last_event_sha256:
            raise ContractError("previous_event_sha256 does not match current chain head")
        if self._events and event.occurred_at < self._events[-1].occurred_at:
            raise ContractError("event occurred_at must be monotonic")
        self._events.append(event)
        self._by_id[event.event_id] = event
        return event

    def make_event(
        self,
        *,
        event_id: str,
        kind: ProductEvidenceEventKind,
        workflow_id: str,
        subject_kind: str,
        subject_id: str,
        occurred_at: datetime,
        subject_version: int | None = None,
        evidence_refs: tuple[str, ...] = (),
        actor_ref: str | None = None,
        reason_code: str | None = None,
    ) -> ProductEvidenceEvent:
        return ProductEvidenceEvent(
            event_id=event_id,
            timeline_id=self.timeline_id,
            sequence=self.next_sequence,
            kind=kind,
            workspace_id=self.workspace_id,
            workflow_id=workflow_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            subject_version=subject_version,
            occurred_at=occurred_at,
            evidence_refs=evidence_refs,
            actor_ref=actor_ref,
            reason_code=reason_code,
            previous_event_sha256=self.last_event_sha256,
        )

    def verify_chain(self) -> bool:
        previous: str | None = None
        last_time: datetime | None = None
        for index, event in enumerate(self._events, start=1):
            if event.sequence != index:
                return False
            if event.previous_event_sha256 != previous:
                return False
            if event.calculate_sha256() != event.event_sha256:
                return False
            if last_time is not None and event.occurred_at < last_time:
                return False
            previous = event.event_sha256
            last_time = event.occurred_at
        return True

    def export_safe(self) -> dict[str, Any]:
        if not self.verify_chain():
            raise ContractError("product evidence timeline chain verification failed")
        return {
            "contract_version": "claw-product-evidence-timeline.v1",
            "timeline_id": self.timeline_id,
            "workspace_id": self.workspace_id,
            "event_count": len(self._events),
            "chain_head_sha256": self.last_event_sha256,
            "events": [event.safe_dict() for event in self._events],
            "authority": "b54_product_evidence_projection",
            "control_plane_authoritative_audit": False,
        }

    def events(self) -> tuple[ProductEvidenceEvent, ...]:
        return tuple(self._events)


REAL_AUDIT_BACKEND_CONFIGURED = False
CONTROL_PLANE_AUDIT_REPLACED = False
