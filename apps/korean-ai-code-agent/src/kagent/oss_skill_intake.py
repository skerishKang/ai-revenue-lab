"""#2823 bounded open-source Skill intake and provenance gate.

This module records whether an external package or repository may be adopted
by a later product composition. It is deliberately not a Skill Registry and it
does not register, install, dispatch, or execute anything.

The gate is provider-free and dependency-free. A candidate is accepted only
when its immutable identity, license, dependency, behavior, and evidence
reviews are explicit. A safe receipt exposes bounded review metadata, never
the source record or its evidence payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError, exact_commit_revision
from .core import redact_secrets

__all__ = [
    "AuditStatus",
    "AUTO_RUNTIME_REGISTRATION",
    "DependencyAudit",
    "EvidenceRef",
    "LegalUseStatus",
    "OSSDecision",
    "OSS_GATE_IS_SKILL_REGISTRY",
    "OSSIntakeGate",
    "OSSIntakeReceipt",
    "OSSIntakeRecord",
    "OSSReviewMetadata",
    "OSSSourceKind",
    "PinningStrategy",
    "BehaviorAudit",
    "CredentialEnvironmentAudit",
    "StrategyRecord",
    "PRODUCTION_MUTATION",
    "PROVIDER_CALLS",
]


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PACKAGE_VERSION_RE = re.compile(
    r"^v?(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:[-+][0-9A-Za-z.-]+)?$"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PRIVATE_PATH_RE = re.compile(r"(?:^[A-Za-z]:[\\/])|(?:^\\\\)|(?:^file://)", re.IGNORECASE)

MAX_REASON_CHARS = 512
MAX_LIMITATION_CHARS = 512
MAX_EVIDENCE_REFS = 32

OSS_GATE_IS_SKILL_REGISTRY = False
AUTO_RUNTIME_REGISTRATION = False
PROVIDER_CALLS = False
PRODUCTION_MUTATION = False


class OSSSourceKind(str, Enum):
    PACKAGE = "package"
    REPOSITORY = "repository"
    SKILL_REPOSITORY = "skill_repository"


class OSSDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class LegalUseStatus(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class AuditStatus(str, Enum):
    REVIEWED = "reviewed"
    UNKNOWN = "unknown"
    DENIED = "denied"


class PinningStrategy(str, Enum):
    IMMUTABLE = "immutable"
    FLOATING = "floating"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Bounded reference to review evidence; raw evidence is never stored here."""

    ref: str
    kind: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", _safe_reference(self.ref, "evidence.ref"))
        object.__setattr__(self, "kind", _safe_id(self.kind, "evidence.kind"))


@dataclass(frozen=True, slots=True)
class BehaviorAudit:
    """Review of one capability surface of an external candidate."""

    status: AuditStatus
    declared: bool
    hidden: bool
    evidence: EvidenceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(AuditStatus, self.status, "behavior.status"))
        object.__setattr__(self, "declared", _strict_bool(self.declared, "behavior.declared"))
        object.__setattr__(self, "hidden", _strict_bool(self.hidden, "behavior.hidden"))
        if not isinstance(self.evidence, EvidenceRef):
            raise ContractError("behavior.evidence must be an EvidenceRef")

    @property
    def passes_review(self) -> bool:
        return self.status is AuditStatus.REVIEWED and not self.hidden


@dataclass(frozen=True, slots=True)
class CredentialEnvironmentAudit:
    """Explicit environment/credential read review.

    Environment reads may be admitted only when declared. Credential reads are
    never accepted by this gate, even when a candidate claims they are declared.
    A later authority must create a separate, narrower contract for that case.
    """

    status: AuditStatus
    environment_reads_declared: bool
    credential_reads_declared: bool
    reads_credentials: bool
    hidden: bool
    evidence: EvidenceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(AuditStatus, self.status, "credential_environment_reads.status"))
        for name in (
            "environment_reads_declared",
            "credential_reads_declared",
            "reads_credentials",
            "hidden",
        ):
            object.__setattr__(self, name, _strict_bool(getattr(self, name), f"credential_environment_reads.{name}"))
        if not isinstance(self.evidence, EvidenceRef):
            raise ContractError("credential_environment_reads.evidence must be an EvidenceRef")

    @property
    def passes_review(self) -> bool:
        return (
            self.status is AuditStatus.REVIEWED
            and self.environment_reads_declared
            and self.credential_reads_declared
            and not self.reads_credentials
            and not self.hidden
        )


@dataclass(frozen=True, slots=True)
class DependencyAudit:
    status: AuditStatus
    dependencies_declared: bool
    evidence: EvidenceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(AuditStatus, self.status, "transitive_dependency_status.status"))
        object.__setattr__(
            self,
            "dependencies_declared",
            _strict_bool(self.dependencies_declared, "transitive_dependency_status.dependencies_declared"),
        )
        if not isinstance(self.evidence, EvidenceRef):
            raise ContractError("transitive_dependency_status.evidence must be an EvidenceRef")

    @property
    def passes_review(self) -> bool:
        return self.status is AuditStatus.REVIEWED and self.dependencies_declared


@dataclass(frozen=True, slots=True)
class StrategyRecord:
    name: str
    evidence: EvidenceRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _safe_id(self.name, "strategy.name"))
        if not isinstance(self.evidence, EvidenceRef):
            raise ContractError("strategy.evidence must be an EvidenceRef")


@dataclass(frozen=True, slots=True)
class OSSReviewMetadata:
    reviewed_at: datetime
    reviewer_ref: str
    review_ref: EvidenceRef

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reviewed_at, datetime)
            or self.reviewed_at.tzinfo is None
            or self.reviewed_at.utcoffset() is None
        ):
            raise ContractError("reviewed_at must be a timezone-aware datetime")
        object.__setattr__(self, "reviewed_at", self.reviewed_at.astimezone(timezone.utc))
        object.__setattr__(self, "reviewer_ref", _safe_id(self.reviewer_ref, "reviewer_ref"))
        if not isinstance(self.review_ref, EvidenceRef):
            raise ContractError("review_ref must be an EvidenceRef")


@dataclass(frozen=True, slots=True)
class OSSIntakeRecord:
    candidate_id: str
    source_kind: OSSSourceKind
    repository_or_package: str
    immutable_version_or_commit: str
    license_id: str
    license_source: EvidenceRef
    commercial_use_status: LegalUseStatus
    redistribution_status: LegalUseStatus
    transitive_dependency_status: DependencyAudit
    network_behavior: BehaviorAudit
    filesystem_behavior: BehaviorAudit
    shell_behavior: BehaviorAudit
    subprocess_behavior: BehaviorAudit
    credential_environment_reads: CredentialEnvironmentAudit
    update_strategy: StrategyRecord
    pinning_strategy: StrategyRecord
    known_format_limitations: tuple[str, ...]
    test_evidence: tuple[EvidenceRef, ...]
    adversarial_evidence: tuple[EvidenceRef, ...]
    decision: OSSDecision
    decision_reason: str
    review: OSSReviewMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _safe_id(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "source_kind", _enum(OSSSourceKind, self.source_kind, "source_kind"))
        object.__setattr__(
            self,
            "repository_or_package",
            _safe_reference(self.repository_or_package, "repository_or_package"),
        )
        object.__setattr__(
            self,
            "immutable_version_or_commit",
            _validate_immutable_pin(self.immutable_version_or_commit, self.source_kind),
        )
        object.__setattr__(self, "license_id", _safe_id(self.license_id, "license_id"))
        if self.license_id.casefold() in {"unknown", "unlicensed", "missing"}:
            raise ContractError("license_id must identify an explicitly reviewed license")
        if not isinstance(self.license_source, EvidenceRef):
            raise ContractError("license_source must be an EvidenceRef")
        object.__setattr__(self, "commercial_use_status", _enum(LegalUseStatus, self.commercial_use_status, "commercial_use_status"))
        object.__setattr__(self, "redistribution_status", _enum(LegalUseStatus, self.redistribution_status, "redistribution_status"))
        for name, expected in (
            ("transitive_dependency_status", DependencyAudit),
            ("network_behavior", BehaviorAudit),
            ("filesystem_behavior", BehaviorAudit),
            ("shell_behavior", BehaviorAudit),
            ("subprocess_behavior", BehaviorAudit),
            ("credential_environment_reads", CredentialEnvironmentAudit),
            ("update_strategy", StrategyRecord),
            ("pinning_strategy", StrategyRecord),
        ):
            if not isinstance(getattr(self, name), expected):
                raise ContractError(f"{name} has an invalid typed contract")
        if self.pinning_strategy.name != PinningStrategy.IMMUTABLE.value:
            raise ContractError("pinning_strategy must be immutable")
        object.__setattr__(self, "known_format_limitations", _limitations(self.known_format_limitations))
        object.__setattr__(self, "test_evidence", _evidence_tuple(self.test_evidence, "test_evidence", required=True))
        object.__setattr__(self, "adversarial_evidence", _evidence_tuple(self.adversarial_evidence, "adversarial_evidence", required=True))
        object.__setattr__(self, "decision", _enum(OSSDecision, self.decision, "decision"))
        object.__setattr__(self, "decision_reason", _bounded_reason(self.decision_reason, "decision_reason"))
        if not isinstance(self.review, OSSReviewMetadata):
            raise ContractError("review must be OSSReviewMetadata")

    @property
    def reviewed_at(self) -> datetime:
        return self.review.reviewed_at

    def policy_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.commercial_use_status is not LegalUseStatus.ALLOWED:
            failures.append("commercial_use_not_allowed_or_unknown")
        if self.redistribution_status is not LegalUseStatus.ALLOWED:
            failures.append("redistribution_not_allowed_or_unknown")
        if not self.transitive_dependency_status.passes_review:
            failures.append("transitive_dependency_audit_required")
        for name, audit in (
            ("network_behavior", self.network_behavior),
            ("filesystem_behavior", self.filesystem_behavior),
            ("shell_behavior", self.shell_behavior),
            ("subprocess_behavior", self.subprocess_behavior),
        ):
            if not audit.passes_review:
                failures.append(f"{name}_review_required")
        if not self.credential_environment_reads.passes_review:
            failures.append("credential_or_environment_read_review_required")
        if not self.test_evidence or not self.adversarial_evidence:
            failures.append("test_and_adversarial_evidence_required")
        return tuple(failures)


@dataclass(frozen=True, slots=True)
class OSSIntakeReceipt:
    candidate_id: str
    immutable_version: str
    license_id: str
    decision: OSSDecision
    decision_code: str
    decision_reason: str
    network_reviewed: bool
    filesystem_reviewed: bool
    shell_reviewed: bool
    subprocess_reviewed: bool
    provenance_recorded: bool = True
    runtime_skill_registered: bool = False
    auto_runtime_registration: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _safe_id(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "immutable_version", _safe_reference(self.immutable_version, "immutable_version"))
        object.__setattr__(self, "license_id", _safe_id(self.license_id, "license_id"))
        object.__setattr__(self, "decision", _enum(OSSDecision, self.decision, "decision"))
        object.__setattr__(self, "decision_code", _safe_id(self.decision_code, "decision_code"))
        object.__setattr__(self, "decision_reason", _bounded_reason(self.decision_reason, "decision_reason"))
        for name in (
            "network_reviewed",
            "filesystem_reviewed",
            "shell_reviewed",
            "subprocess_reviewed",
            "provenance_recorded",
            "runtime_skill_registered",
            "auto_runtime_registration",
        ):
            object.__setattr__(self, name, _strict_bool(getattr(self, name), name))
        if not self.provenance_recorded:
            raise ContractError("OSS intake receipt requires recorded provenance")
        if self.runtime_skill_registered or self.auto_runtime_registration:
            raise ContractError("OSS intake never registers or activates runtime Skills")

    @property
    def adoption_allowed(self) -> bool:
        return self.decision is OSSDecision.ACCEPTED and self.provenance_recorded

    def assert_adoptable(self) -> None:
        if not self.adoption_allowed:
            raise ContractError("OSS candidate is not accepted for adoption")

    def safe_dict(self) -> dict[str, Any]:
        """Bounded public projection; source/evidence payloads are excluded."""

        return {
            "contract_version": "claw-oss-intake-receipt.v1",
            "candidate_id": self.candidate_id,
            "immutable_version": self.immutable_version,
            "license_id": self.license_id,
            "decision": self.decision.value,
            "decision_code": self.decision_code,
            "decision_reason": self.decision_reason,
            "network_reviewed": self.network_reviewed,
            "filesystem_reviewed": self.filesystem_reviewed,
            "shell_reviewed": self.shell_reviewed,
            "subprocess_reviewed": self.subprocess_reviewed,
            "provenance_recorded": self.provenance_recorded,
            "adoption_allowed": self.adoption_allowed,
            "runtime_skill_registered": False,
            "auto_runtime_registration": False,
            "raw_source_record": False,
            "raw_evidence": False,
        }


class OSSIntakeGate:
    """Evaluate OSS provenance without registering or executing a Skill."""

    def evaluate(self, record: OSSIntakeRecord) -> OSSIntakeReceipt:
        if not isinstance(record, OSSIntakeRecord):
            raise ContractError("OSS intake requires an OSSIntakeRecord")
        failures = record.policy_failures()
        if record.decision is OSSDecision.ACCEPTED and failures:
            raise ContractError(f"accepted OSS candidate fails intake gate: {','.join(failures)}")
        decision = OSSDecision.ACCEPTED if not failures and record.decision is OSSDecision.ACCEPTED else OSSDecision.REJECTED
        code = "accepted_pinned_candidate" if decision is OSSDecision.ACCEPTED else (failures[0] if failures else "explicit_rejection")
        reason = "accepted after bounded provenance and behavior review" if decision is OSSDecision.ACCEPTED else code
        return OSSIntakeReceipt(
            candidate_id=record.candidate_id,
            immutable_version=record.immutable_version_or_commit,
            license_id=record.license_id,
            decision=decision,
            decision_code=code,
            decision_reason=reason,
            network_reviewed=record.network_behavior.passes_review,
            filesystem_reviewed=record.filesystem_behavior.passes_review,
            shell_reviewed=record.shell_behavior.passes_review,
            subprocess_reviewed=record.subprocess_behavior.passes_review,
        )


def _safe_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _safe_reference(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 1_024 or _CONTROL_RE.search(normalized):
        raise ContractError(f"{field_name} is malformed")
    if (
        redact_secrets(normalized) != normalized
        or _PRIVATE_PATH_RE.search(normalized)
        or normalized.startswith("/")
    ):
        raise ContractError(f"{field_name} must not contain secrets or private filesystem paths")
    return normalized


def _bounded_reason(value: Any, field_name: str) -> str:
    normalized = _safe_reference(value, field_name)
    if len(normalized) > MAX_REASON_CHARS:
        raise ContractError(f"{field_name} exceeds {MAX_REASON_CHARS} characters")
    return normalized


def _limitations(value: Any) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ContractError("known_format_limitations must be a tuple")
    if len(value) > 32:
        raise ContractError("known_format_limitations has too many entries")
    return tuple(_bounded_reason(item, "known_format_limitation") for item in value)


def _evidence_tuple(value: Any, field_name: str, *, required: bool) -> tuple[EvidenceRef, ...]:
    if not isinstance(value, tuple) or len(value) > MAX_EVIDENCE_REFS:
        raise ContractError(f"{field_name} must be a bounded tuple")
    if required and not value:
        raise ContractError(f"{field_name} is required")
    if not all(isinstance(item, EvidenceRef) for item in value):
        raise ContractError(f"{field_name} must contain EvidenceRef values")
    return value


def _enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} has an invalid value") from exc


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field_name} must be boolean")
    return value


def _validate_immutable_pin(value: Any, source_kind: OSSSourceKind) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("immutable_version_or_commit is required")
    normalized = value.strip().lower()
    if normalized in {"main", "master", "latest", "head", "tip", "trunk"} or any(
        marker in normalized for marker in ("refs/heads/", "^", "~", ">=", "<=", "*", "||")
    ):
        raise ContractError("floating or range version references are not allowed")
    if source_kind is not OSSSourceKind.PACKAGE:
        return exact_commit_revision(normalized, "immutable_version_or_commit")
    if not _PACKAGE_VERSION_RE.fullmatch(normalized):
        raise ContractError("package candidate requires an exact immutable version")
    return normalized
