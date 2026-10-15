from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable

from .contracts import ContractError


class PilotPhase(str, Enum):
    BASELINE = "baseline"
    SHADOW = "shadow"
    LIVE = "approval_gated_live"
    FINANCE_AUGMENTATION = "finance_augmentation"


class MetricUnit(str, Enum):
    MINUTES = "minutes"
    COUNT = "count"
    PERCENT = "percent"
    CURRENCY_MINOR = "currency_minor"
    SCORE = "score"


class MetricDirection(str, Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"
    NEUTRAL = "neutral"


class EvidenceQuality(str, Enum):
    MEASURED = "measured"
    ESTIMATED = "estimated"


def _ref(value: str, field_name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
        raise ContractError(f"{field_name} must be a bounded non-empty reference")
    return value


def _text(value: str, field_name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit:
        raise ContractError(f"{field_name} must be bounded and non-empty")
    return value


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ContractError(f"{field_name} must not use binary float")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ContractError(f"{field_name} must be decimal-compatible") from exc
    if not result.is_finite():
        raise ContractError(f"{field_name} must be finite")
    return result


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    metric_key: str
    version: int
    label: str
    unit: MetricUnit
    direction: MetricDirection
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_key", _ref(self.metric_key, "metric_key", limit=96))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ContractError("version must be a positive integer")
        object.__setattr__(self, "label", _text(self.label, "label", limit=160))
        object.__setattr__(self, "description", _text(self.description, "description", limit=1000))
        if not isinstance(self.unit, MetricUnit):
            raise ContractError("unit must be MetricUnit")
        if not isinstance(self.direction, MetricDirection):
            raise ContractError("direction must be MetricDirection")


@dataclass(frozen=True, slots=True)
class PilotObservation:
    observation_id: str
    workspace_id: str
    phase: PilotPhase
    metric_key: str
    metric_definition_version: int
    value: Decimal
    observed_at: datetime
    evidence_ref: str
    quality: EvidenceQuality = EvidenceQuality.MEASURED
    workflow_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _ref(self.observation_id, "observation_id"))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "metric_key", _ref(self.metric_key, "metric_key", limit=96))
        if not isinstance(self.phase, PilotPhase):
            raise ContractError("phase must be PilotPhase")
        if isinstance(self.metric_definition_version, bool) or not isinstance(self.metric_definition_version, int) or self.metric_definition_version < 1:
            raise ContractError("metric_definition_version must be positive")
        object.__setattr__(self, "value", _decimal(self.value, "value"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref", limit=512))
        if not isinstance(self.quality, EvidenceQuality):
            raise ContractError("quality must be EvidenceQuality")
        if self.workflow_ref is not None:
            object.__setattr__(self, "workflow_ref", _ref(self.workflow_ref, "workflow_ref"))


@dataclass(frozen=True, slots=True)
class PilotMetricSummary:
    metric_key: str
    definition_version: int
    baseline_measured_count: int
    current_measured_count: int
    estimated_count: int
    baseline_average: Decimal | None
    current_average: Decimal | None
    absolute_change: Decimal | None
    percent_change: Decimal | None
    direction: MetricDirection
    evidence_refs: tuple[str, ...]

    @property
    def measured_comparison_available(self) -> bool:
        return self.baseline_average is not None and self.current_average is not None

    def safe_dict(self) -> dict[str, object]:
        def render(value: Decimal | None) -> str | None:
            return None if value is None else format(value, "f")

        return {
            "metric_key": self.metric_key,
            "definition_version": self.definition_version,
            "baseline_measured_count": self.baseline_measured_count,
            "current_measured_count": self.current_measured_count,
            "estimated_count": self.estimated_count,
            "baseline_average": render(self.baseline_average),
            "current_average": render(self.current_average),
            "absolute_change": render(self.absolute_change),
            "percent_change": render(self.percent_change),
            "direction": self.direction.value,
            "measured_comparison_available": self.measured_comparison_available,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class CaseStudyConsent:
    workspace_id: str
    consent_ref: str
    approved: bool
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "consent_ref", _ref(self.consent_ref, "consent_ref"))
        if self.approved:
            if self.approved_at is None:
                raise ContractError("approved case-study consent requires approved_at")
            object.__setattr__(self, "approved_at", _aware(self.approved_at, "approved_at"))
        elif self.approved_at is not None:
            raise ContractError("unapproved consent cannot carry approved_at")


@dataclass(frozen=True, slots=True)
class PublicCaseStudyProjection:
    workspace_alias: str
    generated_at: datetime
    measured_metrics: tuple[dict[str, object], ...]
    consent_ref: str
    anonymized: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_alias", _text(self.workspace_alias, "workspace_alias", limit=120))
        object.__setattr__(self, "generated_at", _aware(self.generated_at, "generated_at"))
        if not isinstance(self.measured_metrics, tuple):
            raise ContractError("measured_metrics must be a tuple")
        object.__setattr__(self, "consent_ref", _ref(self.consent_ref, "consent_ref"))
        if not self.anonymized:
            raise ContractError("public pilot projection must be anonymized")


class PilotKpiEngine:
    """Evidence-first pilot metrics. It never invents ROI or merges estimates into measured KPI deltas."""

    def __init__(self, definitions: Iterable[MetricDefinition]) -> None:
        definitions = tuple(definitions)
        self._definitions: dict[tuple[str, int], MetricDefinition] = {}
        for definition in definitions:
            if not isinstance(definition, MetricDefinition):
                raise ContractError("definitions must contain MetricDefinition")
            key = (definition.metric_key, definition.version)
            if key in self._definitions:
                raise ContractError("duplicate metric definition")
            self._definitions[key] = definition
        if not self._definitions:
            raise ContractError("at least one metric definition is required")
        self._observations: dict[str, PilotObservation] = {}

    def add(self, observation: PilotObservation) -> None:
        if not isinstance(observation, PilotObservation):
            raise ContractError("observation must be PilotObservation")
        if observation.observation_id in self._observations:
            raise ContractError("duplicate observation_id")
        if (observation.metric_key, observation.metric_definition_version) not in self._definitions:
            raise ContractError("unknown metric definition/version")
        self._observations[observation.observation_id] = observation

    def observations(self, *, workspace_id: str, metric_key: str) -> tuple[PilotObservation, ...]:
        workspace_id = _ref(workspace_id, "workspace_id")
        metric_key = _ref(metric_key, "metric_key", limit=96)
        return tuple(
            sorted(
                (
                    item
                    for item in self._observations.values()
                    if item.workspace_id == workspace_id and item.metric_key == metric_key
                ),
                key=lambda item: (item.observed_at, item.observation_id),
            )
        )

    @staticmethod
    def _average(values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        return sum(values, Decimal(0)) / Decimal(len(values))

    def summarize(
        self,
        *,
        workspace_id: str,
        metric_key: str,
        current_phases: tuple[PilotPhase, ...] = (PilotPhase.SHADOW, PilotPhase.LIVE, PilotPhase.FINANCE_AUGMENTATION),
    ) -> PilotMetricSummary:
        rows = self.observations(workspace_id=workspace_id, metric_key=metric_key)
        if not rows:
            raise ContractError("no observations for metric")
        versions = {row.metric_definition_version for row in rows}
        if len(versions) != 1:
            raise ContractError("metric definition changed; compare versioned cohorts separately")
        version = next(iter(versions))
        definition = self._definitions[(metric_key, version)]
        baseline_values = [
            row.value
            for row in rows
            if row.phase is PilotPhase.BASELINE and row.quality is EvidenceQuality.MEASURED
        ]
        current_values = [
            row.value
            for row in rows
            if row.phase in current_phases and row.quality is EvidenceQuality.MEASURED
        ]
        estimated_count = sum(1 for row in rows if row.quality is EvidenceQuality.ESTIMATED)
        baseline_average = self._average(baseline_values)
        current_average = self._average(current_values)
        absolute_change: Decimal | None = None
        percent_change: Decimal | None = None
        if baseline_average is not None and current_average is not None:
            absolute_change = current_average - baseline_average
            if baseline_average != 0:
                percent_change = (absolute_change / baseline_average) * Decimal(100)
        evidence_refs = tuple(dict.fromkeys(row.evidence_ref for row in rows if row.quality is EvidenceQuality.MEASURED))
        return PilotMetricSummary(
            metric_key=metric_key,
            definition_version=version,
            baseline_measured_count=len(baseline_values),
            current_measured_count=len(current_values),
            estimated_count=estimated_count,
            baseline_average=baseline_average,
            current_average=current_average,
            absolute_change=absolute_change,
            percent_change=percent_change,
            direction=definition.direction,
            evidence_refs=evidence_refs,
        )

    def build_public_case_study(
        self,
        *,
        workspace_id: str,
        workspace_alias: str,
        metric_keys: tuple[str, ...],
        consent: CaseStudyConsent,
        generated_at: datetime,
    ) -> PublicCaseStudyProjection:
        workspace_id = _ref(workspace_id, "workspace_id")
        if consent.workspace_id != workspace_id or not consent.approved:
            raise ContractError("explicit matching case-study consent is required")
        if not isinstance(metric_keys, tuple) or not metric_keys:
            raise ContractError("metric_keys must be a non-empty tuple")
        rendered: list[dict[str, object]] = []
        for metric_key in metric_keys:
            summary = self.summarize(workspace_id=workspace_id, metric_key=metric_key)
            if not summary.measured_comparison_available:
                continue
            safe = summary.safe_dict()
            safe.pop("evidence_refs", None)
            rendered.append(safe)
        if not rendered:
            raise ContractError("no measured baseline/current KPI comparison is available")
        return PublicCaseStudyProjection(
            workspace_alias=workspace_alias,
            generated_at=generated_at,
            measured_metrics=tuple(rendered),
            consent_ref=consent.consent_ref,
        )


def default_pilot_metric_definitions() -> tuple[MetricDefinition, ...]:
    return (
        MetricDefinition("request_to_rfq_minutes", 1, "요청→RFQ 시간", MetricUnit.MINUTES, MetricDirection.LOWER_IS_BETTER, "요청 접수부터 공급사 RFQ 준비 완료까지의 분"),
        MetricDefinition("request_to_po_minutes", 1, "요청→발주 시간", MetricUnit.MINUTES, MetricDirection.LOWER_IS_BETTER, "요청 접수부터 발주서 발행 준비 완료까지의 분"),
        MetricDefinition("manual_reentry_count", 1, "수동 재입력 횟수", MetricUnit.COUNT, MetricDirection.LOWER_IS_BETTER, "한 workflow에서 사람이 동일 데이터를 다시 입력한 횟수"),
        MetricDefinition("supplier_response_minutes", 1, "공급사 응답 시간", MetricUnit.MINUTES, MetricDirection.LOWER_IS_BETTER, "RFQ 전송부터 유효 견적 회신까지의 분"),
        MetricDefinition("extraction_correction_rate", 1, "추출 수정률", MetricUnit.PERCENT, MetricDirection.LOWER_IS_BETTER, "자동 구조화 필드 중 사람이 수정한 비율"),
        MetricDefinition("automation_retry_count", 1, "자동화 재시도 횟수", MetricUnit.COUNT, MetricDirection.LOWER_IS_BETTER, "한 workflow에서 자동화 실패 후 재시도한 횟수"),
        MetricDefinition("owner_intervention_count", 1, "대표 개입 횟수", MetricUnit.COUNT, MetricDirection.LOWER_IS_BETTER, "정책상 승인 외 추가 수동 개입 횟수"),
        MetricDefinition("workflow_cost_minor", 1, "완료 workflow 비용", MetricUnit.CURRENCY_MINOR, MetricDirection.LOWER_IS_BETTER, "완료 workflow에 귀속된 계산 가능한 직접 실행 비용의 minor unit"),
    )
