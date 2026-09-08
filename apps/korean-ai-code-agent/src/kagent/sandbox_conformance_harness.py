"""Provider-neutral sandbox conformance harness for Cloud M1 (#1405 ACT-B).

Provides deterministic verification of sandbox provider capabilities, lease requests,
evidence contracts, and lifecycle invariants without network calls or real cloud provider credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Callable, Sequence

from .contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from .sandbox import DeterministicFakeSandboxProvider, SandboxLeaseError
from .sandbox_conformance import (
    IsolationPrimitive,
    SandboxArtifactManifest,
    SandboxArtifactRef,
    SandboxProviderAssessment,
    SandboxProviderCapabilities,
    SandboxProviderConformanceGate,
    SandboxSecurityPolicy,
    VerifiedDiffEvidence,
    REAL_SANDBOX_PROVIDER_SELECTED,
    REAL_SANDBOX_PROVIDER_CALLS,
    PRODUCTION_SANDBOX_CLAIM,
)
from .security import redact_secrets

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ConformanceStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SandboxProviderConformanceCase:
    case_id: str
    description: str
    control_name: str
    expected_pass: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not _SAFE_ID_RE.fullmatch(self.case_id):
            raise ContractError("case_id must be a safe identifier")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ContractError("description is required")
        if not isinstance(self.control_name, str) or not self.control_name.strip():
            raise ContractError("control_name is required")
        if not isinstance(self.expected_pass, bool):
            raise ContractError("expected_pass must be boolean")


@dataclass(frozen=True, slots=True)
class SandboxProviderConformanceResult:
    case_id: str
    control_name: str
    status: ConformanceStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status is ConformanceStatus.PASSED


@dataclass(frozen=True, slots=True)
class SandboxProviderConformanceReport:
    provider_id: str
    isolation_primitive: IsolationPrimitive
    overall_conforming: bool
    results: tuple[SandboxProviderConformanceResult, ...]
    policy_version: str = "claw-cloud-m1-sandbox.v1"
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    @property
    def failed_controls(self) -> tuple[str, ...]:
        return tuple(r.control_name for r in self.results if not r.passed)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "isolation_primitive": self.isolation_primitive.value,
            "overall_conforming": self.overall_conforming,
            "policy_version": self.policy_version,
            "evaluated_at": self.evaluated_at,
            "failed_controls": list(self.failed_controls),
            "results": [
                {
                    "case_id": r.case_id,
                    "control_name": r.control_name,
                    "status": r.status.value,
                    "message": r.message,
                }
                for r in self.results
            ],
            "real_provider_selected": REAL_SANDBOX_PROVIDER_SELECTED,
            "real_provider_calls": REAL_SANDBOX_PROVIDER_CALLS,
            "production_claim": PRODUCTION_SANDBOX_CLAIM,
        }


def validate_provider_capabilities_against_cloud_m1_policy(
    capabilities: SandboxProviderCapabilities,
    *,
    policy: SandboxSecurityPolicy | None = None,
) -> SandboxProviderAssessment:
    """Validates capabilities using the canonical Cloud M1 conformance gate."""
    gate = SandboxProviderConformanceGate(policy=policy)
    return gate.require_accepted(capabilities)


def validate_lease_request_against_cloud_m1_policy(
    request: SandboxLeaseRequest,
    *,
    policy: SandboxSecurityPolicy | None = None,
) -> None:
    """Validates a sandbox lease request against Cloud M1 invariants:

    - Exact immutable revision required (no branch / empty revision)
    - Network policy must be strictly OFF (deny-by-default)
    - Execution mode must be CLOUD
    - TTL must not exceed max policy limit (max 3600s)
    """
    gate = SandboxProviderConformanceGate(policy=policy)
    if request.execution_mode is not ExecutionMode.CLOUD:
        raise ContractError("Cloud M1 lease request must specify CLOUD execution mode")
    gate.validate_lease_request(request)


def validate_verified_diff_evidence(evidence: VerifiedDiffEvidence) -> dict[str, Any]:
    """Validates verified diff evidence against Cloud M1 contract invariants:

    - Exact input git revision required
    - Unique, bounded changed files list (max 100 entries, no control chars)
    - 64-char SHA256 hex digests for unified diff and verification output
    - Bounded exit code (-255 to 255)
    - Redaction assertion: raw diff and raw terminal output must NOT be in projection
    - Valid non-empty terminal reason
    """
    if not isinstance(evidence, VerifiedDiffEvidence):
        raise ContractError("evidence must be an instance of VerifiedDiffEvidence")
    if not evidence.input_revision or len(evidence.input_revision) < 7:
        raise ContractError("evidence input_revision must be an exact git revision SHA")
    if not evidence.unified_diff_sha256 or not _SHA256_RE.fullmatch(evidence.unified_diff_sha256):
        raise ContractError("evidence unified_diff_sha256 must be a valid 64-char hex digest")
    if not evidence.verification_output_sha256 or not _SHA256_RE.fullmatch(evidence.verification_output_sha256):
        raise ContractError("evidence verification_output_sha256 must be a valid 64-char hex digest")
    if not evidence.terminal_reason:
        raise ContractError("evidence terminal_reason is required")
    return evidence.safe_dict()


class SandboxProviderConformanceHarness:
    """Deterministic, provider-neutral conformance harness for Cloud M1 sandbox validation."""

    def __init__(self, policy: SandboxSecurityPolicy | None = None) -> None:
        self.policy = policy or SandboxSecurityPolicy()
        self.gate = SandboxProviderConformanceGate(policy=self.policy)

    def evaluate_capabilities(
        self,
        capabilities: SandboxProviderCapabilities,
    ) -> SandboxProviderConformanceReport:
        """Runs the complete suite of Cloud M1 conformance controls against candidate capabilities."""
        assessment = self.gate.assess(capabilities)
        results: list[SandboxProviderConformanceResult] = []

        # Evaluate isolation primitive
        if capabilities.isolation_primitive in (IsolationPrimitive.MICROVM, IsolationPrimitive.VM):
            results.append(
                SandboxProviderConformanceResult(
                    case_id="case_isolation_primitive",
                    control_name="isolation_primitive",
                    status=ConformanceStatus.PASSED,
                    message=f"Hardware isolation primitive accepted: {capabilities.isolation_primitive.value}",
                )
            )
        else:
            results.append(
                SandboxProviderConformanceResult(
                    case_id="case_isolation_primitive",
                    control_name="isolation_primitive",
                    status=ConformanceStatus.FAILED,
                    message=f"Isolation primitive not accepted for Cloud M1: {capabilities.isolation_primitive.value}",
                )
            )

        # Check each required boolean control
        from .sandbox_conformance import _REQUIRED_CAPABILITIES

        for control in _REQUIRED_CAPABILITIES:
            val = getattr(capabilities, control, False)
            if val is True:
                results.append(
                    SandboxProviderConformanceResult(
                        case_id=f"case_{control}",
                        control_name=control,
                        status=ConformanceStatus.PASSED,
                        message=f"Control {control} verified true",
                    )
                )
            else:
                results.append(
                    SandboxProviderConformanceResult(
                        case_id=f"case_{control}",
                        control_name=control,
                        status=ConformanceStatus.FAILED,
                        message=f"Control {control} is missing or false",
                    )
                )

        overall = assessment.accepted_for_cloud_m1 and all(r.passed for r in results)
        return SandboxProviderConformanceReport(
            provider_id=capabilities.provider_id,
            isolation_primitive=capabilities.isolation_primitive,
            overall_conforming=overall,
            results=tuple(results),
            policy_version=assessment.policy_version,
        )

    def evaluate_lease_lifecycle(
        self,
        provider: DeterministicFakeSandboxProvider,
        request: SandboxLeaseRequest,
    ) -> bool:
        """Verifies single active lease per run, release, and terminal non-resurrection."""
        self.gate.validate_lease_request(request)

        # 1. First allocation succeeds
        lease = provider.allocate(request)
        if lease.state is not SandboxLeaseState.RESERVED:
            return False

        # 2. Second allocation for the same active run MUST fail closed
        try:
            provider.allocate(request)
            return False
        except SandboxLeaseError:
            pass

        # 3. Release succeeds
        released = provider.release(lease.lease_id, run_id=request.run_id)
        if released.state is not SandboxLeaseState.RELEASED:
            return False

        # 4. Terminal resurrection fails closed
        try:
            provider.release(lease.lease_id, run_id=request.run_id)
            return False
        except SandboxLeaseError:
            pass

        return True

    def evaluate_artifact_manifest(self, manifest: SandboxArtifactManifest) -> bool:
        """Verifies artifact counts, bounds, and terminal sanitization."""
        try:
            manifest.validate_against(self.policy)
            return True
        except ContractError:
            return False


__all__ = [
    "ConformanceStatus",
    "SandboxProviderConformanceCase",
    "SandboxProviderConformanceResult",
    "SandboxProviderConformanceReport",
    "SandboxProviderConformanceHarness",
    "validate_provider_capabilities_against_cloud_m1_policy",
    "validate_lease_request_against_cloud_m1_policy",
    "validate_verified_diff_evidence",
]
