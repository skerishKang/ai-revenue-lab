from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .sandbox_conformance import IsolationPrimitive
from .sandbox_provider_evidence import (
    ProviderControlEvidence,
    SandboxProviderEvidencePack,
    capability_control_names,
)
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class ProviderEvidenceStatus(str, Enum):
    VERIFIED = "verified"
    UNPROVEN = "unproven"
    NOT_SUPPORTED = "not_supported"


class ProviderEvidenceBasis(str, Enum):
    OFFICIAL_DOCUMENTATION = "official_documentation"
    DETERMINISTIC_HARNESS = "deterministic_harness"
    LIVE_PROVIDER_PROBE = "live_provider_probe"
    TRUSTED_PROVIDER_ATTESTATION = "trusted_provider_attestation"


_ACCEPTANCE_BASES = frozenset(
    {
        ProviderEvidenceBasis.LIVE_PROVIDER_PROBE,
        ProviderEvidenceBasis.TRUSTED_PROVIDER_ATTESTATION,
    }
)


@dataclass(frozen=True, slots=True)
class ReviewedProviderControlEvidence:
    control: str
    status: ProviderEvidenceStatus
    basis: ProviderEvidenceBasis
    evidence_ref: str
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.control not in capability_control_names():
            raise ContractError("unknown sandbox provider capability control")
        if not isinstance(self.status, ProviderEvidenceStatus):
            try:
                object.__setattr__(self, "status", ProviderEvidenceStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid provider evidence status") from exc
        if not isinstance(self.basis, ProviderEvidenceBasis):
            try:
                object.__setattr__(self, "basis", ProviderEvidenceBasis(self.basis))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid provider evidence basis") from exc
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        observed = _aware(self.observed_at, "observed_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= observed:
            raise ContractError("provider evidence expires_at must follow observed_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "expires_at", expires)

    def current_at(self, now: datetime) -> bool:
        now = _aware(now, "now")
        return self.observed_at <= now < self.expires_at

    def acceptance_grade_at(self, now: datetime) -> bool:
        return (
            self.status is ProviderEvidenceStatus.VERIFIED
            and self.basis in _ACCEPTANCE_BASES
            and self.current_at(now)
        )

    def blocker_code(self, now: datetime) -> str | None:
        now = _aware(now, "now")
        if not self.current_at(now):
            return "stale_or_future"
        if self.status is ProviderEvidenceStatus.UNPROVEN:
            return "unproven"
        if self.status is ProviderEvidenceStatus.NOT_SUPPORTED:
            return "not_supported"
        if self.basis not in _ACCEPTANCE_BASES:
            return "insufficient_evidence_basis"
        return None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "status": self.status.value,
            "basis": self.basis.value,
            "evidence_ref": self.evidence_ref,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "acceptance_grade_without_time_check": (
                self.status is ProviderEvidenceStatus.VERIFIED and self.basis in _ACCEPTANCE_BASES
            ),
            "raw_provider_payload": False,
            "credential_value": None,
            "provider_endpoint": None,
        }


@dataclass(frozen=True, slots=True)
class SandboxProviderEvidenceReview:
    provider_candidate_ref: str
    isolation_primitive: IsolationPrimitive
    controls: tuple[ReviewedProviderControlEvidence, ...]
    review_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_candidate_ref", _ref(self.provider_candidate_ref, "provider_candidate_ref"))
        object.__setattr__(self, "review_ref", _ref(self.review_ref, "review_ref"))
        if not isinstance(self.isolation_primitive, IsolationPrimitive):
            try:
                object.__setattr__(self, "isolation_primitive", IsolationPrimitive(self.isolation_primitive))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid isolation primitive") from exc
        if not isinstance(self.controls, tuple) or not all(
            isinstance(item, ReviewedProviderControlEvidence) for item in self.controls
        ):
            raise ContractError("controls must be a tuple of ReviewedProviderControlEvidence")
        names = tuple(item.control for item in self.controls)
        if len(names) != len(set(names)):
            raise ContractError("reviewed provider controls must be unique")
        expected = set(capability_control_names())
        actual = set(names)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ContractError(
                f"provider evidence review must cover every capability; missing={missing}, extra={extra}"
            )

    def acceptance_blockers(self, now: datetime) -> tuple[str, ...]:
        now = _aware(now, "now")
        blockers: list[str] = []
        for item in self.controls:
            code = item.blocker_code(now)
            if code is not None:
                blockers.append(f"{item.control}:{code}")
        if self.isolation_primitive is IsolationPrimitive.UNKNOWN:
            blockers.append("known_isolation_primitive:unproven")
        return tuple(blockers)

    def research_gaps(self, now: datetime) -> tuple[str, ...]:
        now = _aware(now, "now")
        gaps: list[str] = []
        for item in self.controls:
            if not item.current_at(now):
                gaps.append(f"{item.control}:stale_or_future")
            elif item.status is not ProviderEvidenceStatus.VERIFIED:
                gaps.append(f"{item.control}:{item.status.value}")
        if self.isolation_primitive is IsolationPrimitive.UNKNOWN:
            gaps.append("known_isolation_primitive:unproven")
        return tuple(gaps)

    def eligible_for_acceptance(self, now: datetime) -> bool:
        return not self.acceptance_blockers(now)

    def promote_to_v1(self, now: datetime) -> SandboxProviderEvidencePack:
        blockers = self.acceptance_blockers(now)
        if blockers:
            raise ContractError(
                "provider evidence is not acceptance-grade: " + ", ".join(blockers)
            )
        return SandboxProviderEvidencePack(
            provider_candidate_ref=self.provider_candidate_ref,
            isolation_primitive=self.isolation_primitive,
            controls=tuple(
                ProviderControlEvidence(
                    control=item.control,
                    observed=True,
                    evidence_ref=item.evidence_ref,
                )
                for item in self.controls
            ),
        )

    def safe_dict(self, now: datetime) -> dict[str, Any]:
        now = _aware(now, "now")
        blockers = self.acceptance_blockers(now)
        return {
            "contract_version": "claw-cloud-provider-evidence-review.v2",
            "provider_candidate_ref": self.provider_candidate_ref,
            "isolation_primitive": self.isolation_primitive.value,
            "review_ref": self.review_ref,
            "controls": [item.safe_dict() for item in self.controls],
            "research_gaps": list(self.research_gaps(now)),
            "acceptance_blockers": list(blockers),
            "acceptance_grade": not blockers,
            "provider_selected": False,
            "security_certification": False,
            "deployment_approval": False,
            "production_ready_claim": False,
            "raw_provider_payload": False,
            "credential_fields": False,
            "provider_endpoint_fields": False,
        }


DOCUMENTATION_ONLY_SELECTION_SUPPORTED = False
DETERMINISTIC_HARNESS_ONLY_SELECTION_SUPPORTED = False
PROVIDER_SELECTION_FROM_RESEARCH_REVIEW_SUPPORTED = False
PRODUCTION_APPROVAL_FROM_PROVIDER_REVIEW_SUPPORTED = False
