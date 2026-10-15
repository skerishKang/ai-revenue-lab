from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib

from .contracts import ContractError
from .ops_pilot import EvidenceQuality, PilotKpiEngine, PilotObservation, PilotPhase
from .security import redact_secrets


class PilotTelemetryKind(str, Enum):
    REQUEST_INGESTED = "request_ingested"
    RFQ_READY = "rfq_ready"
    RFQ_SENT = "rfq_sent"
    SUPPLIER_QUOTE_RECEIVED = "supplier_quote_received"
    PO_READY = "po_ready"
    WORKFLOW_COMPLETED = "workflow_completed"
    MANUAL_REENTRY = "manual_reentry"
    EXTRACTION_FIELD_CONFIRMED = "extraction_field_confirmed"
    EXTRACTION_FIELD_CORRECTED = "extraction_field_corrected"
    AUTOMATION_RETRY = "automation_retry"
    OWNER_INTERVENTION = "owner_intervention"


_PAIR_KINDS = frozenset(
    {
        PilotTelemetryKind.RFQ_SENT,
        PilotTelemetryKind.SUPPLIER_QUOTE_RECEIVED,
    }
)
_SINGLETON_KINDS = frozenset(
    {
        PilotTelemetryKind.REQUEST_INGESTED,
        PilotTelemetryKind.RFQ_READY,
        PilotTelemetryKind.PO_READY,
        PilotTelemetryKind.WORKFLOW_COMPLETED,
    }
)


def _ref(value: str, field_name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be a bounded non-empty reference")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _minutes(start: datetime, end: datetime) -> Decimal:
    if end < start:
        raise ContractError("telemetry milestone end cannot precede start")
    delta = end - start
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    return Decimal(micros) / Decimal(60_000_000)


@dataclass(frozen=True, slots=True)
class WorkflowTelemetryEvent:
    event_id: str
    workspace_id: str
    workflow_ref: str
    phase: PilotPhase
    kind: PilotTelemetryKind
    occurred_at: datetime
    evidence_ref: str
    subject_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _ref(self.event_id, "event_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "workflow_ref", _ref(self.workflow_ref, "workflow_ref"))
        if not isinstance(self.phase, PilotPhase):
            raise ContractError("phase must be PilotPhase")
        if not isinstance(self.kind, PilotTelemetryKind):
            raise ContractError("kind must be PilotTelemetryKind")
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref", limit=512))
        if self.subject_ref is not None:
            object.__setattr__(self, "subject_ref", _ref(self.subject_ref, "subject_ref"))
        if self.kind in _PAIR_KINDS and self.subject_ref is None:
            raise ContractError(f"{self.kind.value} requires subject_ref for exact RFQ correlation")
        if self.kind in _SINGLETON_KINDS and self.subject_ref is not None:
            raise ContractError(f"{self.kind.value} is workflow-scoped and must not carry subject_ref")

    def safe_dict(self) -> dict[str, str | None]:
        return {
            "event_id": self.event_id,
            "workspace_id": self.workspace_id,
            "workflow_ref": self.workflow_ref,
            "phase": self.phase.value,
            "kind": self.kind.value,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "evidence_ref": self.evidence_ref,
            "subject_ref": self.subject_ref,
        }


@dataclass(frozen=True, slots=True)
class DerivedPilotObservation:
    observation: PilotObservation
    source_event_ids: tuple[str, ...]
    source_evidence_refs: tuple[str, ...]

    def safe_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation.observation_id,
            "metric_key": self.observation.metric_key,
            "phase": self.observation.phase.value,
            "value": format(self.observation.value, "f"),
            "workflow_ref": self.observation.workflow_ref,
            "source_event_ids": list(self.source_event_ids),
            "source_evidence_refs": list(self.source_evidence_refs),
            "quality": self.observation.quality.value,
        }


class PilotMeasurementBridge:
    """Derive measured pilot KPIs from explicit workflow telemetry.

    Absence of an event is never interpreted as a measured zero unless the
    workflow has an explicit WORKFLOW_COMPLETED marker. Cost is deliberately not
    derived because the current pilot metric has no currency dimension.
    """

    def __init__(self) -> None:
        self._events: dict[str, WorkflowTelemetryEvent] = {}

    def add(self, event: WorkflowTelemetryEvent) -> None:
        if not isinstance(event, WorkflowTelemetryEvent):
            raise ContractError("event must be WorkflowTelemetryEvent")
        existing = self._events.get(event.event_id)
        if existing is not None:
            if existing == event:
                return
            raise ContractError("telemetry event_id replay conflicts with existing event")
        self._events[event.event_id] = event

    def events_for(self, *, workspace_id: str, workflow_ref: str) -> tuple[WorkflowTelemetryEvent, ...]:
        workspace_id = _ref(workspace_id, "workspace_id")
        workflow_ref = _ref(workflow_ref, "workflow_ref")
        return tuple(
            sorted(
                (
                    event
                    for event in self._events.values()
                    if event.workspace_id == workspace_id and event.workflow_ref == workflow_ref
                ),
                key=lambda event: (event.occurred_at, event.event_id),
            )
        )

    def derive(self, *, workspace_id: str, workflow_ref: str) -> tuple[DerivedPilotObservation, ...]:
        rows = self.events_for(workspace_id=workspace_id, workflow_ref=workflow_ref)
        if not rows:
            raise ContractError("workflow has no telemetry events")
        phases = {event.phase for event in rows}
        if len(phases) != 1:
            raise ContractError("one workflow telemetry cohort cannot span multiple pilot phases")
        phase = next(iter(phases))

        singleton: dict[PilotTelemetryKind, WorkflowTelemetryEvent] = {}
        paired: dict[tuple[PilotTelemetryKind, str], WorkflowTelemetryEvent] = {}
        for event in rows:
            if event.kind in _SINGLETON_KINDS:
                if event.kind in singleton:
                    raise ContractError(f"duplicate singleton telemetry milestone: {event.kind.value}")
                singleton[event.kind] = event
            elif event.kind in _PAIR_KINDS:
                assert event.subject_ref is not None
                key = (event.kind, event.subject_ref)
                if key in paired:
                    raise ContractError(
                        f"duplicate correlated telemetry milestone: {event.kind.value}/{event.subject_ref}"
                    )
                paired[key] = event

        derived: list[DerivedPilotObservation] = []
        request = singleton.get(PilotTelemetryKind.REQUEST_INGESTED)
        rfq_ready = singleton.get(PilotTelemetryKind.RFQ_READY)
        po_ready = singleton.get(PilotTelemetryKind.PO_READY)
        completed = singleton.get(PilotTelemetryKind.WORKFLOW_COMPLETED)

        if request is not None and rfq_ready is not None:
            derived.append(
                self._duration_observation(
                    metric_key="request_to_rfq_minutes",
                    phase=phase,
                    workspace_id=workspace_id,
                    workflow_ref=workflow_ref,
                    start=request,
                    end=rfq_ready,
                    suffix="request_rfq",
                )
            )
        if request is not None and po_ready is not None:
            derived.append(
                self._duration_observation(
                    metric_key="request_to_po_minutes",
                    phase=phase,
                    workspace_id=workspace_id,
                    workflow_ref=workflow_ref,
                    start=request,
                    end=po_ready,
                    suffix="request_po",
                )
            )

        subject_refs = sorted(
            {
                subject
                for kind, subject in paired
                if kind in _PAIR_KINDS
            }
        )
        for subject_ref in subject_refs:
            sent = paired.get((PilotTelemetryKind.RFQ_SENT, subject_ref))
            received = paired.get((PilotTelemetryKind.SUPPLIER_QUOTE_RECEIVED, subject_ref))
            if sent is None or received is None:
                continue
            derived.append(
                self._duration_observation(
                    metric_key="supplier_response_minutes",
                    phase=phase,
                    workspace_id=workspace_id,
                    workflow_ref=workflow_ref,
                    start=sent,
                    end=received,
                    suffix=f"supplier_response:{subject_ref}",
                )
            )

        if completed is not None:
            derived.extend(
                self._completed_count_observations(
                    rows=rows,
                    phase=phase,
                    workspace_id=workspace_id,
                    workflow_ref=workflow_ref,
                    completed=completed,
                )
            )

        reviewed = [
            event
            for event in rows
            if event.kind
            in {
                PilotTelemetryKind.EXTRACTION_FIELD_CONFIRMED,
                PilotTelemetryKind.EXTRACTION_FIELD_CORRECTED,
            }
        ]
        if reviewed:
            corrected = sum(
                1 for event in reviewed if event.kind is PilotTelemetryKind.EXTRACTION_FIELD_CORRECTED
            )
            value = Decimal(corrected) * Decimal(100) / Decimal(len(reviewed))
            derived.append(
                self._value_observation(
                    metric_key="extraction_correction_rate",
                    phase=phase,
                    workspace_id=workspace_id,
                    workflow_ref=workflow_ref,
                    value=value,
                    source_events=tuple(reviewed),
                    observed_at=max(event.occurred_at for event in reviewed),
                    suffix="extraction_correction",
                )
            )

        return tuple(sorted(derived, key=lambda item: item.observation.observation_id))

    def capture_into(
        self,
        engine: PilotKpiEngine,
        *,
        workspace_id: str,
        workflow_ref: str,
    ) -> tuple[DerivedPilotObservation, ...]:
        if not isinstance(engine, PilotKpiEngine):
            raise ContractError("engine must be PilotKpiEngine")
        derived = self.derive(workspace_id=workspace_id, workflow_ref=workflow_ref)
        for item in derived:
            engine.add(item.observation)
        return derived

    def _completed_count_observations(
        self,
        *,
        rows: tuple[WorkflowTelemetryEvent, ...],
        phase: PilotPhase,
        workspace_id: str,
        workflow_ref: str,
        completed: WorkflowTelemetryEvent,
    ) -> tuple[DerivedPilotObservation, ...]:
        specs = (
            (PilotTelemetryKind.MANUAL_REENTRY, "manual_reentry_count"),
            (PilotTelemetryKind.AUTOMATION_RETRY, "automation_retry_count"),
            (PilotTelemetryKind.OWNER_INTERVENTION, "owner_intervention_count"),
        )
        result: list[DerivedPilotObservation] = []
        for kind, metric_key in specs:
            events = tuple(event for event in rows if event.kind is kind)
            source_events = events + (completed,)
            result.append(
                self._value_observation(
                    metric_key=metric_key,
                    phase=phase,
                    workspace_id=workspace_id,
                    workflow_ref=workflow_ref,
                    value=Decimal(len(events)),
                    source_events=source_events,
                    observed_at=completed.occurred_at,
                    suffix=metric_key,
                )
            )
        return tuple(result)

    def _duration_observation(
        self,
        *,
        metric_key: str,
        phase: PilotPhase,
        workspace_id: str,
        workflow_ref: str,
        start: WorkflowTelemetryEvent,
        end: WorkflowTelemetryEvent,
        suffix: str,
    ) -> DerivedPilotObservation:
        return self._value_observation(
            metric_key=metric_key,
            phase=phase,
            workspace_id=workspace_id,
            workflow_ref=workflow_ref,
            value=_minutes(start.occurred_at, end.occurred_at),
            source_events=(start, end),
            observed_at=end.occurred_at,
            suffix=suffix,
        )

    @staticmethod
    def _value_observation(
        *,
        metric_key: str,
        phase: PilotPhase,
        workspace_id: str,
        workflow_ref: str,
        value: Decimal,
        source_events: tuple[WorkflowTelemetryEvent, ...],
        observed_at: datetime,
        suffix: str,
    ) -> DerivedPilotObservation:
        if not source_events:
            raise ContractError("derived observation requires source telemetry")
        canonical = "|".join(
            [workspace_id, workflow_ref, metric_key, suffix]
            + [event.event_id for event in source_events]
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        observation_id = f"telemetry_{digest}"
        evidence_canonical = "|".join(event.evidence_ref for event in source_events)
        evidence_digest = hashlib.sha256(evidence_canonical.encode("utf-8")).hexdigest()[:24]
        evidence_ref = f"derived_telemetry:{evidence_digest}"
        observation = PilotObservation(
            observation_id=observation_id,
            workspace_id=workspace_id,
            phase=phase,
            metric_key=metric_key,
            metric_definition_version=1,
            value=value,
            observed_at=observed_at,
            evidence_ref=evidence_ref,
            quality=EvidenceQuality.MEASURED,
            workflow_ref=workflow_ref,
        )
        return DerivedPilotObservation(
            observation=observation,
            source_event_ids=tuple(event.event_id for event in source_events),
            source_evidence_refs=tuple(event.evidence_ref for event in source_events),
        )


WORKFLOW_COST_AUTOCAPTURE_SUPPORTED = False
ESTIMATED_TELEMETRY_OBSERVATIONS_SUPPORTED = False
