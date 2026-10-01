"""Source-only gate for one future Vercel isolated-parser live probe (#3283).

This module composes existing authorities only:
- Core owns bounded isolated-parser request/response contracts.
- #1405 owns Cloud M1 provider launch/probe/evidence policy.
- #2824 owns the single binary parser authority decision.

No Vercel client, credential, endpoint, sandbox allocation, provider call,
workflow dispatch, or Production binding exists here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError, exact_commit_revision
from .sandbox_provider_probe import (
    CloudM1ProviderLaunchProfile,
    SandboxProviderCandidate,
    SandboxProviderLiveProbePlan,
    build_candidate_launch_profile,
    build_live_probe_plan,
)

VERCEL_PARSER_LIVE_GATE_SOURCE_VERSION = "claw-vercel-parser-live-probe-gate.v1"
VERCEL_PARSER_CENTRAL_CONFIRMATION = "CENTRAL_VERCEL_PARSER_LIVE_PROBE=YES"
VERCEL_PARSER_LIVE_DISPATCH_TRIGGERED = False
VERCEL_PARSER_SANDBOX_ALLOCATIONS = 0
VERCEL_PARSER_CREDENTIAL_BINDINGS = 0
VERCEL_PARSER_PROVIDER_CALLS = 0
VERCEL_PARSER_PRODUCTION_MUTATIONS = 0

PARSER_HARD_DEADLINE_SECONDS = 30
_MIN_SANDBOX_TTL_SECONDS = 60
_MAX_SANDBOX_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class VercelParserLiveProbeGate:
    """Pre-dispatch parser-runtime requirements; never a live authorization."""

    exact_main_sha: str
    central_confirmation: str
    parser_deadline_seconds: int
    sandbox_ttl_seconds: int
    resource_lineage: str
    cleanup_mandatory: bool
    target_environment: str
    parser_request_contract: str
    parser_response_contract: str
    profile: CloudM1ProviderLaunchProfile
    plan: SandboxProviderLiveProbePlan

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exact_main_sha",
            exact_commit_revision(self.exact_main_sha, "exact_main_sha"),
        )
        if self.central_confirmation != VERCEL_PARSER_CENTRAL_CONFIRMATION:
            raise ContractError("Vercel parser live gate requires explicit CENTRAL confirmation")
        if (
            isinstance(self.parser_deadline_seconds, bool)
            or not isinstance(self.parser_deadline_seconds, int)
            or self.parser_deadline_seconds != PARSER_HARD_DEADLINE_SECONDS
        ):
            raise ContractError("parser deadline must equal the canonical 30-second hard limit")
        if (
            isinstance(self.sandbox_ttl_seconds, bool)
            or not isinstance(self.sandbox_ttl_seconds, int)
            or not _MIN_SANDBOX_TTL_SECONDS <= self.sandbox_ttl_seconds <= _MAX_SANDBOX_TTL_SECONDS
        ):
            raise ContractError("sandbox TTL must be between 60 and 300 seconds")
        if self.sandbox_ttl_seconds <= self.parser_deadline_seconds:
            raise ContractError("sandbox TTL must exceed the parser hard deadline")
        if self.resource_lineage != "single_fresh_nonpersistent_sandbox":
            raise ContractError("Vercel parser live gate permits one fresh nonpersistent sandbox only")
        if self.cleanup_mandatory is not True:
            raise ContractError("Vercel parser live gate requires teardown on every terminal path")
        if self.target_environment != "non_production":
            raise ContractError("Vercel parser live gate is restricted to non_Production")
        if self.parser_request_contract != "padiem_ai_core.isolated_parser_client":
            raise ContractError("gate must reuse the canonical isolated parser request contract")
        if self.parser_response_contract != "padiem_ai_core.isolated_parser_client":
            raise ContractError("gate must reuse the canonical isolated parser response contract")
        if self.profile.candidate is not SandboxProviderCandidate.VERCEL_SANDBOX:
            raise ContractError("Vercel parser live gate requires the canonical Vercel profile")
        self.plan.validate_profile(self.profile)
        if self.plan.plan_ref != "plan:cloud-m1/vercel_sandbox/live-probe-v1":
            raise ContractError("Vercel parser gate must reuse the canonical probe plan")

        settings = self.profile.setting_map
        required = {
            "networkPolicy": "deny-all",
            "persistent": False,
            "public_port_count": 0,
            "guest_secret_count": 0,
            "snapshot_reuse": False,
            "fork_reuse": False,
            "getOrCreate": False,
            "resume": False,
            "teardown_sequence": "stop_then_permanent_delete",
            "exact_revision_verification": True,
        }
        for key, expected in required.items():
            if settings.get(key) != expected:
                raise ContractError(f"canonical Vercel parser profile requires {key}={expected!r}")

    @property
    def metadata_negative_test_required(self) -> bool:
        return "provider_metadata_blocking" in self.profile.unresolved_live_requirements

    @property
    def process_tree_death_required(self) -> bool:
        return "process_tree_death" in self.profile.unresolved_live_requirements

    @property
    def non_resurrection_required(self) -> bool:
        return "exact_teardown_and_non_resurrectability" in self.profile.unresolved_live_requirements

    @property
    def resource_limits_required(self) -> bool:
        return "applied_disk_and_process_hard_limits" in self.profile.unresolved_live_requirements

    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": VERCEL_PARSER_LIVE_GATE_SOURCE_VERSION,
            "candidate": self.profile.candidate.value,
            "profile_ref": self.profile.profile_ref,
            "plan_ref": self.plan.plan_ref,
            "exact_main_guard": True,
            "central_confirmation_required": True,
            "target_environment": self.target_environment,
            "parser_deadline_seconds": self.parser_deadline_seconds,
            "sandbox_ttl_seconds": self.sandbox_ttl_seconds,
            "resource_lineage": self.resource_lineage,
            "cleanup_mandatory": self.cleanup_mandatory,
            "network_deny_default_required": True,
            "persistence_disabled_required": True,
            "public_ports_disabled_required": True,
            "guest_secrets_disabled_required": True,
            "metadata_negative_test_required": self.metadata_negative_test_required,
            "process_tree_death_required": self.process_tree_death_required,
            "non_resurrection_required": self.non_resurrection_required,
            "resource_limits_required": self.resource_limits_required,
            "parser_request_contract": self.parser_request_contract,
            "parser_response_contract": self.parser_response_contract,
            "live_dispatch_allowed": False,
            "provider_calls": 0,
            "sandbox_allocations": 0,
            "credential_bindings": 0,
            "production_mutations": 0,
            "provider_selected": False,
            "production_parser_binding": False,
            "production_ready_claim": False,
        }


def build_vercel_parser_live_probe_gate(
    *,
    exact_main_sha: str,
    central_confirmation: str,
    parser_deadline_seconds: int = PARSER_HARD_DEADLINE_SECONDS,
    sandbox_ttl_seconds: int = 120,
) -> VercelParserLiveProbeGate:
    """Build the source-only gate from existing authorities; performs no I/O."""

    profile = build_candidate_launch_profile(SandboxProviderCandidate.VERCEL_SANDBOX)
    plan = build_live_probe_plan(profile)
    return VercelParserLiveProbeGate(
        exact_main_sha=exact_main_sha,
        central_confirmation=central_confirmation,
        parser_deadline_seconds=parser_deadline_seconds,
        sandbox_ttl_seconds=sandbox_ttl_seconds,
        resource_lineage="single_fresh_nonpersistent_sandbox",
        cleanup_mandatory=True,
        target_environment="non_production",
        parser_request_contract="padiem_ai_core.isolated_parser_client",
        parser_response_contract="padiem_ai_core.isolated_parser_client",
        profile=profile,
        plan=plan,
    )
