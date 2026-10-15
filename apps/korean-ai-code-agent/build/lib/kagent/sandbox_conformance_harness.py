"""Provider-neutral sandbox conformance harness for Cloud M1 (#1405 ACT-B).

Provides deterministic verification of sandbox provider capabilities, lease requests,
evidence contracts, and lifecycle invariants without network calls or real cloud provider credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
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
from .sandbox import (
    SandboxLeaseError,
    SandboxLeasePort,
    supports_lease_reclamation,
    supports_workload_cancellation,
)
from .sandbox_conformance import (
    IsolationPrimitive,
    SandboxAppliedLimits,
    SandboxArtifactManifest,
    SandboxArtifactRef,
    SandboxProviderAssessment,
    SandboxProviderCapabilities,
    SandboxProviderConformanceGate,
    SandboxSecurityPolicy,
    RESOURCE_LIMITS_REPORTED_CONTROL,
    RESOURCE_LIMITS_WITHIN_POLICY_CONTROL,
    VerifiedDiffEvidence,
    REAL_SANDBOX_PROVIDER_SELECTED,
    REAL_SANDBOX_PROVIDER_CALLS,
    PRODUCTION_SANDBOX_CLAIM,
)
from .security import redact_secrets

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RECLAMATION_PROBE_LABEL = "sandbox-conformance-reclamation"


def reclamation_probe_run_id(run_id: str) -> str:
    """The probe run identity the reclamation exercise reserves under.

    Appending a suffix to the caller's id would overrun the canonical 128-character
    identifier contract for any run already at that bound, so the exercise would fail
    on id shape instead of on provider behaviour. A digest keeps the result fixed
    length, canonical-safe and deterministic, and always distinct from the run it
    mirrors. It reuses the contract's grammar; it does not define another one.
    """
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    return f"{_RECLAMATION_PROBE_LABEL}-{digest}"


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
    applied_limits: SandboxAppliedLimits | None = None,
    policy: SandboxSecurityPolicy | None = None,
) -> SandboxProviderAssessment:
    """Canonical acceptance entry point; delegates the decision to the gate.

    ``applied_limits`` is required in substance: omitting it (or passing no numbers
    through any path) fails closed inside ``require_accepted``, so this helper can
    never accept a candidate on declarations alone. It raises the same
    ``ContractError`` as every other Cloud M1 refusal rather than a distinct error
    shape for the limits case.
    """
    gate = SandboxProviderConformanceGate(policy=policy)
    return gate.require_accepted(capabilities, applied_limits=applied_limits)


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
        *,
        applied_limits: SandboxAppliedLimits | None = None,
    ) -> SandboxProviderConformanceReport:
        """Runs the complete suite of Cloud M1 conformance controls against candidate capabilities.

        ``applied_limits`` carries the numbers a provider says it actually enforced.
        They are required: omitting them fails acceptance through
        ``resource_limits_reported`` rather than falling back on the four
        ``*_limit_enforced`` booleans, because a claim that limits exist is not
        evidence that any particular limit was applied.
        """
        assessment = self.gate.assess(capabilities, applied_limits=applied_limits)
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

        if applied_limits is None:
            # Acceptance requires the numbers, not the claim. The gate has already
            # recorded this in missing_controls; the case below mirrors that single
            # decision so the report has one meaning per entry point, not two rules.
            results.append(
                SandboxProviderConformanceResult(
                    case_id=f"case_{RESOURCE_LIMITS_REPORTED_CONTROL}",
                    control_name=RESOURCE_LIMITS_REPORTED_CONTROL,
                    status=ConformanceStatus.FAILED,
                    message="provider reported no CPU/memory/disk/process limit values",
                )
            )
        else:
            try:
                self.policy.require_within_bounds(applied_limits)
            except ContractError as exc:
                results.append(
                    SandboxProviderConformanceResult(
                        case_id=f"case_{RESOURCE_LIMITS_WITHIN_POLICY_CONTROL}",
                        control_name=RESOURCE_LIMITS_WITHIN_POLICY_CONTROL,
                        status=ConformanceStatus.FAILED,
                        message=str(exc),
                    )
                )
            else:
                results.append(
                    SandboxProviderConformanceResult(
                        case_id=f"case_{RESOURCE_LIMITS_WITHIN_POLICY_CONTROL}",
                        control_name=RESOURCE_LIMITS_WITHIN_POLICY_CONTROL,
                        status=ConformanceStatus.PASSED,
                        message="Reported limits are within the Cloud M1 policy ceiling",
                    )
                )

        # One authority decides acceptance. Recomputing it from the per-case results
        # here would leave two rules that can drift; the case list is evidence detail
        # and test_gate_and_harness_acceptance_cannot_diverge pins that they agree.
        overall = assessment.accepted_for_cloud_m1
        return SandboxProviderConformanceReport(
            provider_id=capabilities.provider_id,
            isolation_primitive=capabilities.isolation_primitive,
            overall_conforming=overall,
            results=tuple(results),
            policy_version=assessment.policy_version,
        )

    def evaluate_cancellation(
        self,
        provider: SandboxLeasePort,
        request: SandboxLeaseRequest,
    ) -> bool:
        """Exercise cancellation instead of trusting a declared capability boolean.

        ``cancellation_kills_workload`` is a provider's own assertion. This drives
        the operation: the capability must exist at all, a cancel must terminate the
        lease, wrong-run / unknown-lease / double-cancel must each fail closed, a
        cancelled lease must refuse renew and release, and the run must still be able
        to allocate again under the existing one-active-lease rule.

        A missing capability returns False rather than raising, so a provider that
        cannot cancel fails Cloud M1 conformance instead of being scored on the
        strength of its claim.
        """
        if not supports_workload_cancellation(provider):
            return False
        cancellation = provider.cancel  # type: ignore[attr-defined]
        try:
            lease = provider.allocate(request)

            # Another run must not be able to cancel this lease.
            try:
                cancellation(lease.lease_id, run_id="run_someone_else")
                return False
            except SandboxLeaseError:
                pass

            # An unknown lease must not report a cancellation.
            try:
                cancellation("lease_does_not_exist", run_id=request.run_id)
                return False
            except SandboxLeaseError:
                pass

            cancelled = cancellation(lease.lease_id, run_id=request.run_id)
            if not isinstance(cancelled, SandboxLease) or cancelled.state is not SandboxLeaseState.RELEASED:
                return False

            # Double cancel fails closed, and nothing may revive the lease afterwards.
            follow_ups = (
                lambda: cancellation(lease.lease_id, run_id=request.run_id),
                lambda: provider.renew(lease.lease_id, run_id=request.run_id, ttl_seconds=900),
                lambda: provider.release(lease.lease_id, run_id=request.run_id),
            )
            for attempt in follow_ups:
                try:
                    attempt()
                    return False
                except SandboxLeaseError:
                    pass

            # The run owns no active lease now, so the one-active-lease rule must
            # let it allocate again rather than treat cancellation as a lock.
            provider.allocate(request)
            return True
        except (SandboxLeaseError, ContractError):
            return False

    def evaluate_reclamation(
        self,
        provider: SandboxLeasePort,
        request: SandboxLeaseRequest,
    ) -> bool:
        """Exercise TTL reclamation instead of trusting a declared ``ttl_enforced``.

        A provider claiming it enforces lease lifetimes has to survive being asked:
        the capability must exist, a lease must refuse reclamation before its TTL, for
        another run, as an unknown id, and twice; an accepted reclamation must really
        end the reservation, drop it from the provider's own inventory, refuse every
        later operation, and still let the run allocate again.

        The inventory is checked rather than swept: a conformance exercise that ran a
        full sweep would reclaim leases belonging to whoever else was using the
        provider, which is not its evidence to consume.

        The probe run is a bounded digest-derived identity rather than an appended
        suffix, so a run id already at the canonical maximum still exercises
        reclamation instead of failing on identifier shape — and this exercise cannot
        be confused by the lease the cancellation step deliberately leaves active.
        """
        if not supports_lease_reclamation(provider):
            return False
        probe = replace(request, run_id=reclamation_probe_run_id(request.run_id))
        try:
            lease = provider.allocate(probe)
            if lease.lease_id not in {
                entry.lease_id for entry in provider.active_leases()  # type: ignore[attr-defined]
            }:
                return False

            # Another run may not reclaim it, and a lease that has not reached its
            # TTL may not be reclaimed at all.
            refusals = (
                lambda: provider.expire(  # type: ignore[attr-defined]
                    lease.lease_id, run_id="run_someone_else", now=lease.expires_at
                ),
                lambda: provider.expire(  # type: ignore[attr-defined]
                    lease.lease_id,
                    run_id=probe.run_id,
                    now=lease.expires_at - timedelta(seconds=1),
                ),
                lambda: provider.expire(  # type: ignore[attr-defined]
                    "lease_does_not_exist", run_id=probe.run_id, now=lease.expires_at
                ),
            )
            for refusal in refusals:
                try:
                    refusal()
                    return False
                except SandboxLeaseError:
                    pass

            expired = provider.expire(  # type: ignore[attr-defined]
                lease.lease_id, run_id=probe.run_id, now=lease.expires_at
            )
            if not isinstance(expired, SandboxLease) or expired.state is not SandboxLeaseState.EXPIRED:
                return False

            # The provider must stop holding the reservation it just reclaimed.
            if lease.lease_id in {
                entry.lease_id for entry in provider.active_leases()  # type: ignore[attr-defined]
            }:
                return False

            follow_ups = [
                lambda: provider.expire(  # type: ignore[attr-defined]
                    lease.lease_id, run_id=probe.run_id, now=lease.expires_at
                ),
                lambda: provider.renew(lease.lease_id, run_id=probe.run_id, ttl_seconds=900),
                lambda: provider.release(lease.lease_id, run_id=probe.run_id),
            ]
            if supports_workload_cancellation(provider):
                follow_ups.append(
                    lambda: provider.cancel(lease.lease_id, run_id=probe.run_id)  # type: ignore[attr-defined]
                )
            for attempt in follow_ups:
                try:
                    attempt()
                    return False
                except SandboxLeaseError:
                    pass

            # Reading it back must not make the reservation live again.
            if provider.get(lease.lease_id).state is not SandboxLeaseState.EXPIRED:
                return False

            # Reclamation is not a lock: the run may reserve again.
            revived = provider.allocate(probe)
            if revived.state is not SandboxLeaseState.RESERVED:
                return False
            released = provider.release(revived.lease_id, run_id=probe.run_id)
            return released.state is SandboxLeaseState.RELEASED
        except (SandboxLeaseError, ContractError):
            return False

    def evaluate_lease_lifecycle(
        self,
        provider: SandboxLeasePort,
        request: SandboxLeaseRequest,
    ) -> bool:
        """Verifies single active lease per run, release, cancellation, reclamation, and terminal non-resurrection.

        Typed to the port, not to the fake, so a real provider can be evaluated
        here once one exists (#1405).
        """
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

        # 5. Cancellation is exercised, not declared (#1405).
        if not self.evaluate_cancellation(provider, request):
            return False

        # 6. TTL reclamation is exercised, not declared (#2803).
        return self.evaluate_reclamation(provider, request)

    def evaluate_artifact_manifest(
        self,
        manifest: SandboxArtifactManifest,
        *,
        raw_terminal_output: str | None = None,
    ) -> bool:
        """Verifies artifact counts, bounds, and proven terminal sanitization.

        ``raw_terminal_output`` is the byte-for-byte text the manifest's sanitized
        count was derived from, and it is required: a run that produced no output at
        all passes ``""`` and is still checked. Passing ``None`` means no evidence was
        offered, which fails closed — otherwise ``terminal_output_sanitized=True``
        would be a self-asserted boolean the acceptance path awards a pass for.
        """
        if raw_terminal_output is None:
            return False
        try:
            manifest.require_sanitized_output(raw_terminal_output, self.policy)
            return True
        except ContractError:
            return False


__all__ = [
    "ConformanceStatus",
    "SandboxAppliedLimits",
    "SandboxProviderConformanceCase",
    "SandboxProviderConformanceResult",
    "SandboxProviderConformanceReport",
    "SandboxProviderConformanceHarness",
    "validate_provider_capabilities_against_cloud_m1_policy",
    "validate_lease_request_against_cloud_m1_policy",
    "validate_verified_diff_evidence",
]
