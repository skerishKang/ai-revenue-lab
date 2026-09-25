"""Source-only gate for one future GCP Seoul N2 Cloud M1 live probe.

This module defines the pre-dispatch contract. It never calls GCP, binds a
credential, creates a resource, dispatches a workflow, or records live evidence.
The canonical Cloud M1 launch profile and live probe plan remain the only
conformance authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .contracts import ContractError, exact_commit_revision
from .sandbox_provider_probe import (
    CloudM1ProviderLaunchProfile,
    SandboxProviderCandidate,
    SandboxProviderLiveProbePlan,
    build_candidate_launch_profile,
    build_live_probe_plan,
    validate_gcp_seoul_n2_request_shape,
)

GCP_N2_LIVE_GATE_SOURCE_VERSION = "claw-gcp-seoul-n2-live-probe-gate.v1"
GCP_N2_CENTRAL_CONFIRMATION = "CENTRAL_GCP_N2_LIVE_PROBE=YES"
GCP_N2_LIVE_DISPATCH_TRIGGERED = False
GCP_N2_CLOUD_RESOURCES_CREATED = 0
GCP_N2_CREDENTIAL_BINDINGS = 0
GCP_N2_PROVIDER_CALLS = 0
GCP_N2_PRODUCTION_MUTATIONS = 0

_GCP_N2_ZONES = frozenset({"asia-northeast3-a", "asia-northeast3-b", "asia-northeast3-c"})
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")


def _safe_ref(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


@dataclass(frozen=True, slots=True)
class GCPSeoulN2LiveProbeGate:
    """Pre-dispatch requirements; not a live execution authorization."""

    exact_main_sha: str
    central_confirmation: str
    zone: str
    ttl_seconds: int
    resource_lineage: str
    cleanup_mandatory: bool
    target_environment: str
    profile: CloudM1ProviderLaunchProfile
    plan: SandboxProviderLiveProbePlan

    def __post_init__(self) -> None:
        object.__setattr__(self, "exact_main_sha", exact_commit_revision(self.exact_main_sha, "exact_main_sha"))
        if self.central_confirmation != GCP_N2_CENTRAL_CONFIRMATION:
            raise ContractError("GCP N2 live gate requires explicit CENTRAL confirmation")
        if self.zone not in _GCP_N2_ZONES:
            raise ContractError("GCP N2 live gate requires an asia-northeast3-a/b/c zone")
        if self.resource_lineage != "single_fresh_resource_lineage":
            raise ContractError("GCP N2 live gate permits one fresh resource lineage only")
        if self.cleanup_mandatory is not True:
            raise ContractError("GCP N2 live gate requires mandatory cleanup and terminal verification")
        if self.target_environment != "non_production":
            raise ContractError("GCP N2 live gate is restricted to non_Production")
        if isinstance(self.ttl_seconds, bool) or not isinstance(self.ttl_seconds, int):
            raise ContractError("GCP N2 live gate TTL must be an integer")
        if not 60 <= self.ttl_seconds <= 900:
            raise ContractError("GCP N2 live gate TTL must be between 60 and 900 seconds")
        if self.profile.candidate is not SandboxProviderCandidate.GCP_SEOUL_N2:
            raise ContractError("GCP N2 live gate requires the canonical gcp_seoul_n2 profile")
        self.plan.validate_profile(self.profile)
        if self.plan.plan_ref != "plan:cloud-m1/gcp_seoul_n2/live-probe-v1":
            raise ContractError("GCP N2 live gate must reuse the canonical probe plan")
        validate_gcp_seoul_n2_request_shape(
            region="asia-northeast3",
            zone=self.zone,
            machine_family="N2",
            cpu_platform="Intel",
            cpu_minimum_generation="Haswell-or-newer",
            local_ssd_enabled=True,
            nested_virtualization_enabled=True,
            vpc="dedicated_non_default",
            default_egress_policy="deny-default",
            public_ip_enabled=False,
            public_port_count=0,
            guest_secret_count=0,
            mig_enabled=False,
            snapshot_reuse=False,
            resume_enabled=False,
            max_run_duration_action="DELETE",
            max_run_duration_seconds=self.ttl_seconds,
        )

    @property
    def metadata_negative_test_required(self) -> bool:
        return "metadata_link_local_blocking" in self.profile.unresolved_live_requirements

    @property
    def process_tree_death_required(self) -> bool:
        return "pids_and_process_tree_death" in self.profile.unresolved_live_requirements

    @property
    def non_resurrection_required(self) -> bool:
        return "delete_non_resurrection_observation" in self.profile.unresolved_live_requirements

    def safe_dict(self) -> dict[str, object]:
        """Safe source projection: no project/account/credential/provider payload."""
        return {
            "contract_version": GCP_N2_LIVE_GATE_SOURCE_VERSION,
            "candidate": self.profile.candidate.value,
            "profile_ref": self.profile.profile_ref,
            "plan_ref": self.plan.plan_ref,
            "exact_main_guard": True,
            "central_confirmation_required": True,
            "zone": self.zone,
            "machine_family": "N2",
            "cpu_platform": "Intel",
            "cpu_minimum_generation": "Haswell-or-newer",
            "local_ssd_required": True,
            "nested_virtualization_required": True,
            "vpc": "dedicated_non_default",
            "egress_policy": "deny-default",
            "ttl_action": "DELETE",
            "ttl_seconds": self.ttl_seconds,
            "resource_lineage": self.resource_lineage,
            "cleanup_mandatory": self.cleanup_mandatory,
            "metadata_negative_test_required": self.metadata_negative_test_required,
            "process_tree_death_required": self.process_tree_death_required,
            "non_resurrection_required": self.non_resurrection_required,
            "live_dispatch_allowed": False,
            "provider_calls": 0,
            "workflow_dispatches": 0,
            "cloud_resources_created": 0,
            "credential_bindings": 0,
            "production_mutations": 0,
            "provider_selected": False,
            "deployment_approval": False,
            "production_ready_claim": False,
        }


def build_gcp_seoul_n2_live_probe_gate(
    *, exact_main_sha: str, central_confirmation: str, zone: str, ttl_seconds: int = 900
) -> GCPSeoulN2LiveProbeGate:
    """Build the source gate from canonical contracts; performs no provider I/O."""
    profile = build_candidate_launch_profile(SandboxProviderCandidate.GCP_SEOUL_N2)
    plan = build_live_probe_plan(profile)
    return GCPSeoulN2LiveProbeGate(
        exact_main_sha=exact_main_sha,
        central_confirmation=central_confirmation,
        zone=_safe_ref(zone, "zone"),
        ttl_seconds=ttl_seconds,
        resource_lineage="single_fresh_resource_lineage",
        cleanup_mandatory=True,
        target_environment="non_production",
        profile=profile,
        plan=plan,
    )
