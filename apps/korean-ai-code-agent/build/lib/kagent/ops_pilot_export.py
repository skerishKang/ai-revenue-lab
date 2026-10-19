from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .ops_pilot import CaseStudyConsent, PilotMetricSummary
from .security import redact_secrets


_SAFE_ALIAS_RE = re.compile(r"^[A-Za-z0-9가-힣][A-Za-z0-9가-힣 _.-]{0,119}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_DEFAULT_EXCLUDED_METRICS = frozenset({"workflow_cost_minor"})


def _alias(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ALIAS_RE.fullmatch(value.strip()):
        raise ContractError("workspace_alias must be bounded anonymized display text")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError("workspace_alias must not contain credential material")
    return value


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class PilotExportPurpose(str, Enum):
    INTERNAL_ANALYSIS = "internal_analysis"
    EXTERNAL_CASE_STUDY = "external_case_study"


@dataclass(frozen=True, slots=True)
class PilotPrivacyExportPolicy:
    minimum_measured_count: int = 5
    excluded_metric_keys: frozenset[str] = _DEFAULT_EXCLUDED_METRICS

    def __post_init__(self) -> None:
        if isinstance(self.minimum_measured_count, bool) or not isinstance(self.minimum_measured_count, int) or not 3 <= self.minimum_measured_count <= 1000:
            raise ContractError("minimum_measured_count must be between 3 and 1000")
        if not isinstance(self.excluded_metric_keys, frozenset):
            raise ContractError("excluded_metric_keys must be a frozenset")
        normalized = frozenset(_ref(value, "excluded_metric_key") for value in self.excluded_metric_keys)
        object.__setattr__(self, "excluded_metric_keys", normalized)


@dataclass(frozen=True, slots=True)
class PrivacySafePilotMetric:
    metric_key: str
    definition_version: int
    baseline_measured_count: int
    current_measured_count: int
    baseline_average: str
    current_average: str
    absolute_change: str
    percent_change: str | None
    direction: str

    @classmethod
    def from_summary(cls, summary: PilotMetricSummary) -> "PrivacySafePilotMetric":
        if not isinstance(summary, PilotMetricSummary):
            raise ContractError("summary must be PilotMetricSummary")
        if not summary.measured_comparison_available:
            raise ContractError("privacy-safe export requires measured baseline/current comparison")
        assert summary.baseline_average is not None
        assert summary.current_average is not None
        assert summary.absolute_change is not None
        return cls(
            metric_key=_ref(summary.metric_key, "metric_key"),
            definition_version=summary.definition_version,
            baseline_measured_count=summary.baseline_measured_count,
            current_measured_count=summary.current_measured_count,
            baseline_average=format(summary.baseline_average, "f"),
            current_average=format(summary.current_average, "f"),
            absolute_change=format(summary.absolute_change, "f"),
            percent_change=None if summary.percent_change is None else format(summary.percent_change, "f"),
            direction=summary.direction.value,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "definition_version": self.definition_version,
            "baseline_measured_count": self.baseline_measured_count,
            "current_measured_count": self.current_measured_count,
            "baseline_average": self.baseline_average,
            "current_average": self.current_average,
            "absolute_change": self.absolute_change,
            "percent_change": self.percent_change,
            "direction": self.direction,
            "evidence_refs_exported": False,
            "workflow_refs_exported": False,
            "raw_observations_exported": False,
        }


@dataclass(frozen=True, slots=True)
class PrivacySafePilotExport:
    export_id: str
    workspace_alias: str
    purpose: PilotExportPurpose
    generated_at: datetime
    minimum_measured_count: int
    metrics: tuple[PrivacySafePilotMetric, ...]
    suppressed_metric_keys: tuple[str, ...]
    consent_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "export_id", _ref(self.export_id, "export_id"))
        object.__setattr__(self, "workspace_alias", _alias(self.workspace_alias))
        if not isinstance(self.purpose, PilotExportPurpose):
            try:
                object.__setattr__(self, "purpose", PilotExportPurpose(self.purpose))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid pilot export purpose") from exc
        object.__setattr__(self, "generated_at", _aware(self.generated_at, "generated_at"))
        if isinstance(self.minimum_measured_count, bool) or not isinstance(self.minimum_measured_count, int) or self.minimum_measured_count < 3:
            raise ContractError("minimum_measured_count must be at least 3")
        if not isinstance(self.metrics, tuple) or not self.metrics or not all(isinstance(item, PrivacySafePilotMetric) for item in self.metrics):
            raise ContractError("privacy-safe export requires at least one aggregate metric")
        if not isinstance(self.suppressed_metric_keys, tuple):
            raise ContractError("suppressed_metric_keys must be a tuple")
        if self.consent_ref is not None:
            object.__setattr__(self, "consent_ref", _ref(self.consent_ref, "consent_ref"))
        if self.purpose is PilotExportPurpose.EXTERNAL_CASE_STUDY and self.consent_ref is None:
            raise ContractError("external case-study export requires consent_ref")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-pilot-privacy-export.v1",
            "export_id": self.export_id,
            "workspace_alias": self.workspace_alias,
            "purpose": self.purpose.value,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "minimum_measured_count": self.minimum_measured_count,
            "metrics": [item.safe_dict() for item in self.metrics],
            "suppressed_metric_keys": list(self.suppressed_metric_keys),
            "consent_ref": self.consent_ref,
            "workspace_id_exported": False,
            "workflow_refs_exported": False,
            "event_ids_exported": False,
            "evidence_refs_exported": False,
            "counterparty_data_exported": False,
            "raw_messages_exported": False,
            "raw_monetary_events_exported": False,
            "publish_permission_implied": self.purpose is PilotExportPurpose.EXTERNAL_CASE_STUDY,
        }


def build_privacy_safe_pilot_export(
    *,
    export_id: str,
    workspace_id: str,
    workspace_alias: str,
    purpose: PilotExportPurpose,
    summaries: tuple[PilotMetricSummary, ...],
    generated_at: datetime,
    policy: PilotPrivacyExportPolicy | None = None,
    consent: CaseStudyConsent | None = None,
) -> PrivacySafePilotExport:
    workspace_id = _ref(workspace_id, "workspace_id")
    workspace_alias = _alias(workspace_alias)
    if not isinstance(purpose, PilotExportPurpose):
        purpose = PilotExportPurpose(purpose)
    if not isinstance(summaries, tuple) or not summaries or not all(isinstance(item, PilotMetricSummary) for item in summaries):
        raise ContractError("summaries must be a non-empty tuple of PilotMetricSummary")
    policy = policy or PilotPrivacyExportPolicy()
    if purpose is PilotExportPurpose.EXTERNAL_CASE_STUDY:
        if not isinstance(consent, CaseStudyConsent) or consent.workspace_id != workspace_id or not consent.approved:
            raise ContractError("matching approved case-study consent is required for external export")
    elif consent is not None and not isinstance(consent, CaseStudyConsent):
        raise ContractError("consent must be CaseStudyConsent or None")

    seen: set[tuple[str, int]] = set()
    exported: list[PrivacySafePilotMetric] = []
    suppressed: list[str] = []
    for summary in summaries:
        key = (summary.metric_key, summary.definition_version)
        if key in seen:
            raise ContractError("duplicate metric summary/version in privacy export")
        seen.add(key)
        if summary.metric_key in policy.excluded_metric_keys:
            suppressed.append(summary.metric_key)
            continue
        if (
            summary.baseline_measured_count < policy.minimum_measured_count
            or summary.current_measured_count < policy.minimum_measured_count
            or not summary.measured_comparison_available
        ):
            suppressed.append(summary.metric_key)
            continue
        exported.append(PrivacySafePilotMetric.from_summary(summary))
    if not exported:
        raise ContractError("no privacy-safe aggregate metric meets export threshold")
    return PrivacySafePilotExport(
        export_id=export_id,
        workspace_alias=workspace_alias,
        purpose=purpose,
        generated_at=generated_at,
        minimum_measured_count=policy.minimum_measured_count,
        metrics=tuple(exported),
        suppressed_metric_keys=tuple(sorted(suppressed)),
        consent_ref=consent.consent_ref if purpose is PilotExportPurpose.EXTERNAL_CASE_STUDY and consent else None,
    )


RAW_PILOT_TELEMETRY_EXPORT_SUPPORTED = False
EXTERNAL_EXPORT_WITHOUT_CONSENT_SUPPORTED = False
CURRENCY_MINOR_DEFAULT_EXPORT_SUPPORTED = False
