"""Canonical capability evidence for Business 14 model routing.

The legacy catalog stores free-form capability tags such as ``chat``, ``image``,
``coding`` and ``long_context``. Absence of a legacy tag is not authoritative
proof that a capability is unsupported. This module normalizes capability truth
into explicit ``supported | unsupported | unknown`` states with bounded evidence
provenance, while leaving the existing catalog/routing behavior unchanged.

Important invariants:
- unknown != unsupported;
- a configured legacy tag is evidence of configured support only;
- ``free`` is pricing metadata, not an execution capability;
- Provider credentials and secret state never enter this contract;
- routing integration is a separate reviewed slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Iterable

from app.pilot.catalog import CatalogModel


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class CapabilityEvidenceError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class ModelCapability(str, Enum):
    CHAT = "chat"
    STREAMING = "streaming"
    VISION = "vision"
    FILE_DOCUMENT = "file_document"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    REASONING = "reasoning"
    CODING = "coding"
    LONG_CONTEXT = "long_context"


class CapabilitySupport(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CapabilityEvidenceKind(str, Enum):
    NONE = "none"
    CONFIGURED = "configured"
    UPSTREAM_REPORTED = "upstream_reported"
    MEASURED = "measured"


def _safe_ref(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise CapabilityEvidenceError(
            "invalid_capability_evidence",
            f"{name} must be a bounded safe reference",
        )
    return value


def _aware_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityEvidenceError(
            "invalid_capability_evidence",
            "observed_at must be a timezone-aware timestamp",
        )
    normalized = value.strip()
    candidate = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CapabilityEvidenceError(
            "invalid_capability_evidence",
            "observed_at must be a valid ISO-8601 timestamp",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CapabilityEvidenceError(
            "invalid_capability_evidence",
            "observed_at must include timezone information",
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ModelCapabilityEvidence:
    capability: ModelCapability
    support: CapabilitySupport
    evidence_kind: CapabilityEvidenceKind
    evidence_ref: str | None = None
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability, ModelCapability):
            raise CapabilityEvidenceError(
                "invalid_capability_evidence",
                "capability must be ModelCapability",
            )
        if not isinstance(self.support, CapabilitySupport):
            raise CapabilityEvidenceError(
                "invalid_capability_evidence",
                "support must be CapabilitySupport",
            )
        if not isinstance(self.evidence_kind, CapabilityEvidenceKind):
            raise CapabilityEvidenceError(
                "invalid_capability_evidence",
                "evidence_kind must be CapabilityEvidenceKind",
            )

        if self.support is CapabilitySupport.UNKNOWN:
            if self.evidence_kind is not CapabilityEvidenceKind.NONE:
                raise CapabilityEvidenceError(
                    "invalid_capability_evidence",
                    "unknown support must use evidence_kind=none",
                )
            if self.evidence_ref is not None or self.observed_at is not None:
                raise CapabilityEvidenceError(
                    "invalid_capability_evidence",
                    "unknown support must not claim evidence provenance",
                )
            return

        if self.evidence_kind is CapabilityEvidenceKind.NONE:
            raise CapabilityEvidenceError(
                "invalid_capability_evidence",
                "known support state requires evidence provenance",
            )
        if self.evidence_ref is not None:
            object.__setattr__(
                self,
                "evidence_ref",
                _safe_ref("evidence_ref", self.evidence_ref),
            )
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", _aware_timestamp(self.observed_at))
        if self.evidence_kind in {
            CapabilityEvidenceKind.UPSTREAM_REPORTED,
            CapabilityEvidenceKind.MEASURED,
        } and self.observed_at is None:
            raise CapabilityEvidenceError(
                "invalid_capability_evidence",
                "upstream/measured capability evidence requires observed_at",
            )

    def to_public_dict(self) -> dict[str, str | None]:
        return {
            "capability": self.capability.value,
            "support": self.support.value,
            "evidence_kind": self.evidence_kind.value,
            "evidence_ref": self.evidence_ref,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class ModelCapabilityProfile:
    model_id: str
    entries: tuple[ModelCapabilityEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_id", _safe_ref("model_id", self.model_id))
        if not isinstance(self.entries, tuple):
            raise CapabilityEvidenceError(
                "invalid_capability_profile",
                "entries must be a tuple",
            )
        if any(not isinstance(entry, ModelCapabilityEvidence) for entry in self.entries):
            raise CapabilityEvidenceError(
                "invalid_capability_profile",
                "entries must contain ModelCapabilityEvidence values",
            )
        capabilities = tuple(entry.capability for entry in self.entries)
        if len(capabilities) != len(set(capabilities)):
            raise CapabilityEvidenceError(
                "duplicate_capability_evidence",
                "capability profile must contain at most one entry per capability",
            )
        if set(capabilities) != set(ModelCapability):
            raise CapabilityEvidenceError(
                "incomplete_capability_profile",
                "capability profile must explicitly represent every canonical capability",
            )

    def evidence_for(self, capability: ModelCapability) -> ModelCapabilityEvidence:
        if not isinstance(capability, ModelCapability):
            raise CapabilityEvidenceError(
                "invalid_capability_requirement",
                "capability must be ModelCapability",
            )
        for entry in self.entries:
            if entry.capability is capability:
                return entry
        raise AssertionError("validated profile is missing canonical capability")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "capabilities": [entry.to_public_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class CapabilityRequirementResult:
    required: tuple[ModelCapability, ...]
    unsupported: tuple[ModelCapability, ...]
    unknown: tuple[ModelCapability, ...]

    @property
    def satisfied(self) -> bool:
        return not self.unsupported and not self.unknown

    def to_public_dict(self) -> dict[str, object]:
        return {
            "required": [item.value for item in self.required],
            "satisfied": self.satisfied,
            "unsupported": [item.value for item in self.unsupported],
            "unknown": [item.value for item in self.unknown],
        }


_LEGACY_SUPPORTED_MAP: dict[str, ModelCapability] = {
    "chat": ModelCapability.CHAT,
    "image": ModelCapability.VISION,
    "coding": ModelCapability.CODING,
    "long_context": ModelCapability.LONG_CONTEXT,
}


def capability_profile_from_catalog_model(
    model: CatalogModel,
    *,
    explicit_evidence: Iterable[ModelCapabilityEvidence] = (),
) -> ModelCapabilityProfile:
    """Build canonical capability truth from legacy tags + explicit evidence.

    Legacy tags can establish configured support for the small set whose meaning
    is already unambiguous. Missing legacy tags remain UNKNOWN. Explicit
    evidence may replace the configured/unknown state for a capability, but
    duplicate explicit evidence fails closed.
    """

    if not isinstance(model, CatalogModel):
        raise CapabilityEvidenceError(
            "invalid_capability_profile",
            "model must be CatalogModel",
        )

    explicit = tuple(explicit_evidence)
    if any(not isinstance(item, ModelCapabilityEvidence) for item in explicit):
        raise CapabilityEvidenceError(
            "invalid_capability_profile",
            "explicit_evidence must contain ModelCapabilityEvidence values",
        )
    explicit_by_capability: dict[ModelCapability, ModelCapabilityEvidence] = {}
    for item in explicit:
        if item.capability in explicit_by_capability:
            raise CapabilityEvidenceError(
                "duplicate_capability_evidence",
                "explicit capability evidence contains duplicates",
            )
        explicit_by_capability[item.capability] = item

    configured_supported = {
        capability
        for tag, capability in _LEGACY_SUPPORTED_MAP.items()
        if tag in model.capabilities
    }

    entries: list[ModelCapabilityEvidence] = []
    for capability in ModelCapability:
        if capability in explicit_by_capability:
            entries.append(explicit_by_capability[capability])
            continue
        if capability in configured_supported:
            entries.append(
                ModelCapabilityEvidence(
                    capability=capability,
                    support=CapabilitySupport.SUPPORTED,
                    evidence_kind=CapabilityEvidenceKind.CONFIGURED,
                    evidence_ref=f"catalog:{model.model_id}",
                    observed_at=None,
                )
            )
        else:
            entries.append(
                ModelCapabilityEvidence(
                    capability=capability,
                    support=CapabilitySupport.UNKNOWN,
                    evidence_kind=CapabilityEvidenceKind.NONE,
                )
            )

    return ModelCapabilityProfile(model_id=model.model_id, entries=tuple(entries))


def evaluate_capability_requirements(
    profile: ModelCapabilityProfile,
    required: Iterable[ModelCapability],
) -> CapabilityRequirementResult:
    if not isinstance(profile, ModelCapabilityProfile):
        raise CapabilityEvidenceError(
            "invalid_capability_requirement",
            "profile must be ModelCapabilityProfile",
        )
    required_tuple = tuple(required)
    if any(not isinstance(item, ModelCapability) for item in required_tuple):
        raise CapabilityEvidenceError(
            "invalid_capability_requirement",
            "required must contain ModelCapability values",
        )
    if len(set(required_tuple)) != len(required_tuple):
        raise CapabilityEvidenceError(
            "invalid_capability_requirement",
            "required capabilities must not contain duplicates",
        )

    unsupported: list[ModelCapability] = []
    unknown: list[ModelCapability] = []
    for capability in required_tuple:
        evidence = profile.evidence_for(capability)
        if evidence.support is CapabilitySupport.UNSUPPORTED:
            unsupported.append(capability)
        elif evidence.support is CapabilitySupport.UNKNOWN:
            unknown.append(capability)

    return CapabilityRequirementResult(
        required=required_tuple,
        unsupported=tuple(unsupported),
        unknown=tuple(unknown),
    )
