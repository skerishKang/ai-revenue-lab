from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError, ExecutionMode, SandboxLeaseRequest
from .sandbox_conformance import IsolationPrimitive, SandboxProviderConformanceGate, SandboxSecurityPolicy
from .sandbox_provider_evidence import capability_control_names
from .sandbox_provider_review import (
    ProviderEvidenceBasis,
    ProviderEvidenceStatus,
    ReviewedProviderControlEvidence,
    SandboxProviderEvidenceReview,
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


def _bounded_int(value: int, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return value


class SandboxProviderCandidate(str, Enum):
    MODAL = "modal"
    DAYTONA = "daytona"
    RUNLOOP = "runloop"
    E2B = "e2b"


class ProbeMethod(str, Enum):
    PROVIDER_API_OBSERVATION = "provider_api_observation"
    IN_SANDBOX_NEGATIVE_TEST = "in_sandbox_negative_test"
    LIFECYCLE_OBSERVATION = "lifecycle_observation"
    ADAPTER_ASSERTION = "adapter_assertion"
    ARTIFACT_VERIFICATION = "artifact_verification"


@dataclass(frozen=True, slots=True)
class ProviderLaunchSetting:
    key: str
    expected_value: bool | int | str
    source_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _ref(self.key, "key"))
        if not isinstance(self.expected_value, (bool, int, str)) or isinstance(self.expected_value, float):
            raise ContractError("expected_value must be bool, int, or string")
        if isinstance(self.expected_value, str):
            value = self.expected_value.strip()
            if not value or len(value) > 256 or redact_secrets(value) != value:
                raise ContractError("expected_value must be a bounded non-secret string")
            object.__setattr__(self, "expected_value", value)
        object.__setattr__(self, "source_ref", _ref(self.source_ref, "source_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "expected_value": self.expected_value,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class CloudM1ProviderLaunchProfile:
    candidate: SandboxProviderCandidate
    profile_ref: str
    settings: tuple[ProviderLaunchSetting, ...]
    unresolved_live_requirements: tuple[str, ...]
    max_ttl_seconds: int = 900
    network_off_enforced: bool = True
    ephemeral_workspace_enforced: bool = True
    persistent_storage_disabled: bool = True
    secret_injection_disabled: bool = True
    snapshot_reuse_disabled: bool = True
    public_ports_disabled: bool = True
    cross_run_reuse_disabled: bool = True
    explicit_teardown_required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SandboxProviderCandidate):
            try:
                object.__setattr__(self, "candidate", SandboxProviderCandidate(self.candidate))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid sandbox provider candidate") from exc
        object.__setattr__(self, "profile_ref", _ref(self.profile_ref, "profile_ref"))
        if not isinstance(self.settings, tuple) or not all(isinstance(item, ProviderLaunchSetting) for item in self.settings):
            raise ContractError("settings must be a tuple of ProviderLaunchSetting")
        keys = tuple(item.key for item in self.settings)
        if len(keys) != len(set(keys)):
            raise ContractError("provider launch settings must be unique")
        if not isinstance(self.unresolved_live_requirements, tuple):
            raise ContractError("unresolved_live_requirements must be a tuple")
        normalized_requirements = tuple(_ref(item, "unresolved_live_requirement") for item in self.unresolved_live_requirements)
        if len(normalized_requirements) != len(set(normalized_requirements)):
            raise ContractError("unresolved_live_requirements must be unique")
        object.__setattr__(self, "unresolved_live_requirements", normalized_requirements)
        policy = SandboxSecurityPolicy()
        object.__setattr__(
            self,
            "max_ttl_seconds",
            _bounded_int(self.max_ttl_seconds, "max_ttl_seconds", minimum=60, maximum=policy.max_ttl_seconds),
        )
        for field_name in (
            "network_off_enforced",
            "ephemeral_workspace_enforced",
            "persistent_storage_disabled",
            "secret_injection_disabled",
            "snapshot_reuse_disabled",
            "public_ports_disabled",
            "cross_run_reuse_disabled",
            "explicit_teardown_required",
        ):
            if getattr(self, field_name) is not True:
                raise ContractError(f"Cloud M1 launch profile requires {field_name}=true")

    @property
    def setting_map(self) -> dict[str, bool | int | str]:
        return {item.key: item.expected_value for item in self.settings}

    @property
    def request_shape_ready(self) -> bool:
        return True

    @property
    def live_execution_ready(self) -> bool:
        return False

    def validate_lease_request(self, request: SandboxLeaseRequest) -> None:
        if not isinstance(request, SandboxLeaseRequest):
            raise ContractError("request must be SandboxLeaseRequest")
        if request.execution_mode is not ExecutionMode.CLOUD:
            raise ContractError("Cloud M1 provider launch requires cloud execution mode")
        SandboxProviderConformanceGate().validate_lease_request(request)
        if request.ttl_seconds > self.max_ttl_seconds:
            raise ContractError("lease request exceeds provider launch profile TTL")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-m1-provider-launch-profile.v1",
            "candidate": self.candidate.value,
            "profile_ref": self.profile_ref,
            "settings": [item.safe_dict() for item in self.settings],
            "unresolved_live_requirements": list(self.unresolved_live_requirements),
            "max_ttl_seconds": self.max_ttl_seconds,
            "network_off_enforced": self.network_off_enforced,
            "ephemeral_workspace_enforced": self.ephemeral_workspace_enforced,
            "persistent_storage_disabled": self.persistent_storage_disabled,
            "secret_injection_disabled": self.secret_injection_disabled,
            "snapshot_reuse_disabled": self.snapshot_reuse_disabled,
            "public_ports_disabled": self.public_ports_disabled,
            "cross_run_reuse_disabled": self.cross_run_reuse_disabled,
            "explicit_teardown_required": self.explicit_teardown_required,
            "request_shape_ready": True,
            "live_execution_ready": False,
            "provider_selected": False,
            "deployment_approval": False,
            "production_ready_claim": False,
            "credential_fields": False,
            "provider_endpoint_fields": False,
        }


@dataclass(frozen=True, slots=True)
class ControlProbeSpec:
    control: str
    probe_id: str
    method: ProbeMethod
    success_criterion_ref: str
    evidence_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.control not in capability_control_names():
            raise ContractError("unknown sandbox provider capability control")
        object.__setattr__(self, "probe_id", _ref(self.probe_id, "probe_id"))
        if not isinstance(self.method, ProbeMethod):
            try:
                object.__setattr__(self, "method", ProbeMethod(self.method))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid probe method") from exc
        object.__setattr__(
            self,
            "success_criterion_ref",
            _ref(self.success_criterion_ref, "success_criterion_ref"),
        )
        object.__setattr__(
            self,
            "evidence_ttl_seconds",
            _bounded_int(self.evidence_ttl_seconds, "evidence_ttl_seconds", minimum=60, maximum=86400),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "probe_id": self.probe_id,
            "method": self.method.value,
            "success_criterion_ref": self.success_criterion_ref,
            "evidence_ttl_seconds": self.evidence_ttl_seconds,
        }


@dataclass(frozen=True, slots=True)
class SandboxProviderLiveProbePlan:
    candidate: SandboxProviderCandidate
    plan_ref: str
    launch_profile_ref: str
    probes: tuple[ControlProbeSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SandboxProviderCandidate):
            try:
                object.__setattr__(self, "candidate", SandboxProviderCandidate(self.candidate))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid sandbox provider candidate") from exc
        object.__setattr__(self, "plan_ref", _ref(self.plan_ref, "plan_ref"))
        object.__setattr__(self, "launch_profile_ref", _ref(self.launch_profile_ref, "launch_profile_ref"))
        if not isinstance(self.probes, tuple) or not all(isinstance(item, ControlProbeSpec) for item in self.probes):
            raise ContractError("probes must be a tuple of ControlProbeSpec")
        names = tuple(item.control for item in self.probes)
        if len(names) != len(set(names)):
            raise ContractError("provider live probes must cover controls uniquely")
        expected = set(capability_control_names())
        actual = set(names)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ContractError(f"provider live probe plan must cover every capability; missing={missing}, extra={extra}")

    def validate_profile(self, profile: CloudM1ProviderLaunchProfile) -> None:
        if not isinstance(profile, CloudM1ProviderLaunchProfile):
            raise ContractError("profile must be CloudM1ProviderLaunchProfile")
        if profile.candidate is not self.candidate:
            raise ContractError("probe plan/provider candidate mismatch")
        if profile.profile_ref != self.launch_profile_ref:
            raise ContractError("probe plan/launch profile correlation mismatch")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-m1-provider-live-probe-plan.v1",
            "candidate": self.candidate.value,
            "plan_ref": self.plan_ref,
            "launch_profile_ref": self.launch_profile_ref,
            "probes": [item.safe_dict() for item in self.probes],
            "complete_control_coverage": True,
            "real_provider_call_executed": False,
            "provider_selected": False,
            "security_certification": False,
            "deployment_approval": False,
            "production_ready_claim": False,
            "credential_fields": False,
            "provider_endpoint_fields": False,
        }


@dataclass(frozen=True, slots=True)
class ProviderProbeControlObservation:
    control: str
    status: ProviderEvidenceStatus
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
                raise ContractError("invalid provider probe status") from exc
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        observed = _aware(self.observed_at, "observed_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= observed:
            raise ContractError("provider probe evidence expires_at must follow observed_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "expires_at", expires)

    def to_reviewed_evidence(self) -> ReviewedProviderControlEvidence:
        return ReviewedProviderControlEvidence(
            control=self.control,
            status=self.status,
            basis=ProviderEvidenceBasis.LIVE_PROVIDER_PROBE,
            evidence_ref=self.evidence_ref,
            observed_at=self.observed_at,
            expires_at=self.expires_at,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "status": self.status.value,
            "evidence_ref": self.evidence_ref,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "raw_provider_payload": False,
        }


@dataclass(frozen=True, slots=True)
class SandboxProviderLiveProbeResult:
    candidate: SandboxProviderCandidate
    profile_ref: str
    plan_ref: str
    result_ref: str
    isolation_primitive: IsolationPrimitive
    observations: tuple[ProviderProbeControlObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SandboxProviderCandidate):
            try:
                object.__setattr__(self, "candidate", SandboxProviderCandidate(self.candidate))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid sandbox provider candidate") from exc
        object.__setattr__(self, "profile_ref", _ref(self.profile_ref, "profile_ref"))
        object.__setattr__(self, "plan_ref", _ref(self.plan_ref, "plan_ref"))
        object.__setattr__(self, "result_ref", _ref(self.result_ref, "result_ref"))
        if not isinstance(self.isolation_primitive, IsolationPrimitive):
            try:
                object.__setattr__(self, "isolation_primitive", IsolationPrimitive(self.isolation_primitive))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid isolation primitive") from exc
        if not isinstance(self.observations, tuple) or not all(
            isinstance(item, ProviderProbeControlObservation) for item in self.observations
        ):
            raise ContractError("observations must be a tuple of ProviderProbeControlObservation")
        names = tuple(item.control for item in self.observations)
        if len(names) != len(set(names)):
            raise ContractError("provider live probe result controls must be unique")
        expected = set(capability_control_names())
        actual = set(names)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ContractError(f"provider live probe result must cover every capability; missing={missing}, extra={extra}")

    def to_evidence_review(
        self,
        plan: SandboxProviderLiveProbePlan,
        profile: CloudM1ProviderLaunchProfile,
    ) -> SandboxProviderEvidenceReview:
        if not isinstance(plan, SandboxProviderLiveProbePlan):
            raise ContractError("plan must be SandboxProviderLiveProbePlan")
        plan.validate_profile(profile)
        if self.candidate is not plan.candidate:
            raise ContractError("probe result/provider candidate mismatch")
        if self.profile_ref != profile.profile_ref:
            raise ContractError("probe result/launch profile correlation mismatch")
        if self.plan_ref != plan.plan_ref:
            raise ContractError("probe result/plan correlation mismatch")
        return SandboxProviderEvidenceReview(
            provider_candidate_ref=self.candidate.value,
            isolation_primitive=self.isolation_primitive,
            controls=tuple(item.to_reviewed_evidence() for item in self.observations),
            review_ref=self.result_ref,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-m1-provider-live-probe-result.v1",
            "candidate": self.candidate.value,
            "profile_ref": self.profile_ref,
            "plan_ref": self.plan_ref,
            "result_ref": self.result_ref,
            "isolation_primitive": self.isolation_primitive.value,
            "observations": [item.safe_dict() for item in self.observations],
            "complete_control_coverage": True,
            "provider_selected": False,
            "security_certification": False,
            "deployment_approval": False,
            "production_ready_claim": False,
            "raw_provider_payload": False,
            "credential_fields": False,
            "provider_endpoint_fields": False,
        }


def _setting(key: str, expected_value: bool | int | str, source_ref: str) -> ProviderLaunchSetting:
    return ProviderLaunchSetting(key=key, expected_value=expected_value, source_ref=source_ref)


def build_candidate_launch_profile(
    candidate: SandboxProviderCandidate,
    *,
    max_ttl_seconds: int = 900,
) -> CloudM1ProviderLaunchProfile:
    if not isinstance(candidate, SandboxProviderCandidate):
        try:
            candidate = SandboxProviderCandidate(candidate)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid sandbox provider candidate") from exc

    if candidate is SandboxProviderCandidate.MODAL:
        settings = (
            _setting("block_network", True, "docs:modal/sandbox-networking"),
            _setting("timeout_seconds", "lease_ttl_seconds", "docs:modal/sandbox-sdk"),
            _setting("secret_injection", False, "policy:cloud-m1/no-secrets"),
            _setting("volume_mounts", False, "policy:cloud-m1/no-persistence"),
            _setting("snapshot_reuse", False, "policy:cloud-m1/no-reuse"),
            _setting("public_tunnels", False, "policy:cloud-m1/private-ports"),
        )
        unresolved = (
            "exact_account_workspace",
            "disk_and_process_hard_limits",
            "provider_metadata_blocking",
            "teardown_terminal_state",
        )
    elif candidate is SandboxProviderCandidate.DAYTONA:
        settings = (
            _setting("networkBlockAll", True, "docs:daytona/network-limits"),
            _setting("ephemeral", True, "docs:daytona/persistence"),
            _setting("wall_clock_ttl_seconds", "lease_ttl_seconds", "docs:daytona/persistence"),
            _setting("shared_persistence", False, "policy:cloud-m1/no-persistence"),
            _setting("secret_injection", False, "policy:cloud-m1/no-secrets"),
            _setting("snapshot_reuse", False, "policy:cloud-m1/no-reuse"),
        )
        unresolved = (
            "exact_sandbox_class",
            "qualifying_network_policy_tier",
            "process_hard_limit",
            "provider_metadata_blocking",
        )
    elif candidate is SandboxProviderCandidate.RUNLOOP:
        settings = (
            _setting("network_policy", "explicit_deny_all", "docs:runloop/network-policies"),
            _setting("fresh_devbox_per_run", True, "policy:cloud-m1/dedicated-workspace"),
            _setting("suspend_resume", False, "docs:runloop/start-stop"),
            _setting("snapshot_reuse", False, "policy:cloud-m1/no-reuse"),
            _setting("explicit_teardown", True, "policy:cloud-m1/teardown"),
            _setting("secret_injection", False, "policy:cloud-m1/no-secrets"),
        )
        unresolved = (
            "exact_devbox_size",
            "hard_wall_clock_ttl",
            "process_hard_limit",
            "provider_metadata_blocking",
        )
    else:
        settings = (
            _setting("allow_internet_access", False, "docs:e2b/python-sdk-v2.15.2"),
            _setting("timeout_action", "kill", "docs:e2b/python-sdk-v2.15.2"),
            _setting("auto_resume", False, "policy:cloud-m1/no-reuse"),
            _setting("snapshot_reuse", False, "policy:cloud-m1/no-reuse"),
            _setting("secret_injection", False, "policy:cloud-m1/no-secrets"),
            _setting("public_ports", False, "policy:cloud-m1/private-ports"),
        )
        unresolved = (
            "exact_resource_hard_limit_contract",
            "process_hard_limit",
            "provider_metadata_blocking",
            "teardown_terminal_state",
        )

    return CloudM1ProviderLaunchProfile(
        candidate=candidate,
        profile_ref=f"profile:cloud-m1/{candidate.value}/v1",
        settings=settings,
        unresolved_live_requirements=unresolved,
        max_ttl_seconds=max_ttl_seconds,
    )


_NEGATIVE_TEST_CONTROLS = frozenset(
    {
        "checkout_hooks_disabled",
        "network_deny_by_default",
        "egress_policy_enforced",
        "privileged_runtime_disabled",
        "host_mounts_disabled",
        "runtime_socket_hidden",
        "provider_metadata_blocked",
        "host_secret_inheritance_disabled",
        "preview_ports_private_by_default",
    }
)
_LIFECYCLE_CONTROLS = frozenset(
    {
        "server_owned_lifecycle",
        "dedicated_workspace_per_run",
        "cross_run_reuse_disabled",
        "ttl_enforced",
        "cancellation_kills_workload",
        "teardown_guaranteed",
        "run_lease_audit_correlation",
    }
)
_RESOURCE_CONTROLS = frozenset(
    {
        "cpu_limit_enforced",
        "memory_limit_enforced",
        "disk_limit_enforced",
        "process_limit_enforced",
    }
)
_ARTIFACT_CONTROLS = frozenset(
    {
        "artifact_allowlist_enforced",
        "artifact_size_limit_enforced",
        "terminal_output_bounded",
        "terminal_output_sanitized",
    }
)


def _probe_method(control: str) -> ProbeMethod:
    if control in _NEGATIVE_TEST_CONTROLS:
        return ProbeMethod.IN_SANDBOX_NEGATIVE_TEST
    if control in _LIFECYCLE_CONTROLS:
        return ProbeMethod.LIFECYCLE_OBSERVATION
    if control in _RESOURCE_CONTROLS:
        return ProbeMethod.PROVIDER_API_OBSERVATION
    if control in _ARTIFACT_CONTROLS:
        return ProbeMethod.ARTIFACT_VERIFICATION
    return ProbeMethod.ADAPTER_ASSERTION


def build_live_probe_plan(
    profile: CloudM1ProviderLaunchProfile,
    *,
    evidence_ttl_seconds: int = 3600,
) -> SandboxProviderLiveProbePlan:
    if not isinstance(profile, CloudM1ProviderLaunchProfile):
        raise ContractError("profile must be CloudM1ProviderLaunchProfile")
    probes = tuple(
        ControlProbeSpec(
            control=control,
            probe_id=f"probe:{profile.candidate.value}/{control}",
            method=_probe_method(control),
            success_criterion_ref=f"criterion:cloud-m1/{control}",
            evidence_ttl_seconds=evidence_ttl_seconds,
        )
        for control in capability_control_names()
    )
    return SandboxProviderLiveProbePlan(
        candidate=profile.candidate,
        plan_ref=f"plan:cloud-m1/{profile.candidate.value}/live-probe-v1",
        launch_profile_ref=profile.profile_ref,
        probes=probes,
    )


PROVIDER_LIVE_PROBE_EXECUTION_CONFIGURED = False
PROVIDER_ACCOUNT_AUTHORIZATION_CONFIGURED = False
PROVIDER_SELECTION_FROM_LAUNCH_PROFILE_SUPPORTED = False
PRODUCTION_APPROVAL_FROM_LIVE_PROBE_PLAN_SUPPORTED = False
