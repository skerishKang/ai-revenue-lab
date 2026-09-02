from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .contracts import ContractError
from .sandbox_conformance import (
    IsolationPrimitive,
    SandboxProviderAssessment,
    SandboxProviderCapabilities,
    SandboxProviderConformanceGate,
)
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def capability_control_names() -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name in SandboxProviderCapabilities.__dataclass_fields__
        if field_name not in {"provider_id", "isolation_primitive"}
    )


@dataclass(frozen=True, slots=True)
class ProviderControlEvidence:
    control: str
    observed: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        if self.control not in capability_control_names():
            raise ContractError("unknown sandbox provider capability control")
        if not isinstance(self.observed, bool):
            raise ContractError("observed must be boolean")
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {"control": self.control, "observed": self.observed, "evidence_ref": self.evidence_ref}


@dataclass(frozen=True, slots=True)
class SandboxProviderEvidencePack:
    provider_candidate_ref: str
    isolation_primitive: IsolationPrimitive
    controls: tuple[ProviderControlEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_candidate_ref", _ref(self.provider_candidate_ref, "provider_candidate_ref"))
        if not isinstance(self.isolation_primitive, IsolationPrimitive):
            try:
                object.__setattr__(self, "isolation_primitive", IsolationPrimitive(self.isolation_primitive))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid isolation primitive") from exc
        if not isinstance(self.controls, tuple) or not all(isinstance(item, ProviderControlEvidence) for item in self.controls):
            raise ContractError("controls must be a tuple of ProviderControlEvidence")
        names = tuple(item.control for item in self.controls)
        if len(names) != len(set(names)):
            raise ContractError("provider evidence controls must be unique")
        expected = set(capability_control_names())
        actual = set(names)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ContractError(f"provider evidence pack must cover every capability; missing={missing}, extra={extra}")

    def to_capabilities(self) -> SandboxProviderCapabilities:
        values = {item.control: item.observed for item in self.controls}
        return SandboxProviderCapabilities(
            provider_id=self.provider_candidate_ref,
            isolation_primitive=self.isolation_primitive,
            **values,
        )

    def assess(self, gate: SandboxProviderConformanceGate | None = None) -> SandboxProviderAssessment:
        return (gate or SandboxProviderConformanceGate()).assess(self.to_capabilities())

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-provider-evidence-pack.v1",
            "provider_candidate_ref": self.provider_candidate_ref,
            "isolation_primitive": self.isolation_primitive.value,
            "controls": [item.safe_dict() for item in self.controls],
            "full_control_coverage": True,
            "provider_selected": False,
            "production_ready_claim": False,
            "credential_fields": False,
            "provider_endpoint_fields": False,
        }


REAL_PROVIDER_EVIDENCE_COLLECTION_CONFIGURED = False
PROVIDER_SELECTION_FROM_EVIDENCE_PACK_SUPPORTED = False
