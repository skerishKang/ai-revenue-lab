from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from .contracts import (
    ExecutionMode,
    NetworkPolicy,
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from .security import redact_secrets


MAX_VERIFIED_DIFF_BYTES = 256_000
MAX_VERIFICATION_OUTPUT_CHARS = 32_000
MAX_VERIFIED_CHANGED_FILES = 100
MAX_ARTIFACT_REF_CHARS = 512
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REVISION_RE = re.compile(r"^[A-Fa-f0-9]{7,64}$")


class SandboxPolicyError(ValueError):
    pass


class SandboxProviderRejected(SandboxPolicyError):
    def __init__(self, failures: tuple[str, ...]) -> None:
        if not failures:
            raise ValueError("provider rejection requires at least one failure")
        self.failures = failures
        super().__init__("sandbox provider does not satisfy Cloud M1 policy")


def _bounded_text(value: str, name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise SandboxPolicyError(f"{name} must be a string")
    text = value.strip()
    if not text:
        raise SandboxPolicyError(f"{name} is required")
    if len(text) > limit:
        raise SandboxPolicyError(f"{name} exceeds {limit} characters")
    if _CONTROL_RE.search(text):
        raise SandboxPolicyError(f"{name} contains control characters")
    return text


def _safe_id(value: str, name: str) -> str:
    text = _bounded_text(value, name, limit=128)
    if not _SAFE_ID_RE.fullmatch(text):
        raise SandboxPolicyError(f"{name} must be a safe identifier")
    return text


def _exact_revision(value: str, name: str = "revision") -> str:
    text = _bounded_text(value, name, limit=64)
    if not _REVISION_RE.fullmatch(text):
        raise SandboxPolicyError(
            f"{name} must be an exact hexadecimal revision of 7 to 64 characters"
        )
    return text.lower()


@dataclass(frozen=True, slots=True)
class SandboxSecurityPolicy:
    """Server-owned minimum policy for the first real Padiem Claw cloud sandbox.

    The values intentionally describe a conservative floor/ceiling rather than
    one provider's API. Client task input must never construct or weaken this
    policy.
    """

    network_policy: NetworkPolicy = NetworkPolicy.OFF
    privileged: bool = False
    host_mounts: bool = False
    runtime_socket: bool = False
    metadata_service_access: bool = False
    inherit_host_secrets: bool = False
    dedicated_workspace: bool = True
    exact_revision_required: bool = True
    kill_process_tree_on_teardown: bool = True
    terminal_reuse_allowed: bool = False
    max_ttl_seconds: int = 1_800
    max_cpu_cores: int = 4
    max_memory_mib: int = 8_192
    max_disk_mib: int = 20_480
    max_artifact_bytes: int = MAX_VERIFIED_DIFF_BYTES
    max_terminal_output_chars: int = MAX_VERIFICATION_OUTPUT_CHARS

    def __post_init__(self) -> None:
        if self.network_policy is not NetworkPolicy.OFF:
            raise SandboxPolicyError("Cloud M1 network policy must default to off")
        insecure_flags = {
            "privileged": self.privileged,
            "host_mounts": self.host_mounts,
            "runtime_socket": self.runtime_socket,
            "metadata_service_access": self.metadata_service_access,
            "inherit_host_secrets": self.inherit_host_secrets,
            "terminal_reuse_allowed": self.terminal_reuse_allowed,
        }
        enabled = tuple(name for name, value in insecure_flags.items() if value is True)
        if enabled:
            raise SandboxPolicyError(
                "Cloud M1 insecure policy flags enabled: " + ", ".join(enabled)
            )
        required_flags = {
            "dedicated_workspace": self.dedicated_workspace,
            "exact_revision_required": self.exact_revision_required,
            "kill_process_tree_on_teardown": self.kill_process_tree_on_teardown,
        }
        disabled = tuple(name for name, value in required_flags.items() if value is not True)
        if disabled:
            raise SandboxPolicyError(
                "Cloud M1 required policy flags disabled: " + ", ".join(disabled)
            )
        bounds = {
            "max_ttl_seconds": (self.max_ttl_seconds, 60, 3_600),
            "max_cpu_cores": (self.max_cpu_cores, 1, 32),
            "max_memory_mib": (self.max_memory_mib, 256, 131_072),
            "max_disk_mib": (self.max_disk_mib, 1_024, 1_048_576),
            "max_artifact_bytes": (self.max_artifact_bytes, 1_024, 2_000_000),
            "max_terminal_output_chars": (
                self.max_terminal_output_chars,
                1_024,
                128_000,
            ),
        }
        for name, (value, minimum, maximum) in bounds.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise SandboxPolicyError(f"{name} must be an integer")
            if not minimum <= value <= maximum:
                raise SandboxPolicyError(
                    f"{name} must be between {minimum} and {maximum}"
                )

    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": "claw-sandbox-security-policy.v1",
            "network_policy": self.network_policy.value,
            "privileged": self.privileged,
            "host_mounts": self.host_mounts,
            "runtime_socket": self.runtime_socket,
            "metadata_service_access": self.metadata_service_access,
            "inherit_host_secrets": self.inherit_host_secrets,
            "dedicated_workspace": self.dedicated_workspace,
            "exact_revision_required": self.exact_revision_required,
            "kill_process_tree_on_teardown": self.kill_process_tree_on_teardown,
            "terminal_reuse_allowed": self.terminal_reuse_allowed,
            "max_ttl_seconds": self.max_ttl_seconds,
            "max_cpu_cores": self.max_cpu_cores,
            "max_memory_mib": self.max_memory_mib,
            "max_disk_mib": self.max_disk_mib,
            "max_artifact_bytes": self.max_artifact_bytes,
            "max_terminal_output_chars": self.max_terminal_output_chars,
        }


@dataclass(frozen=True, slots=True)
class SandboxProviderCapabilities:
    """Non-secret facts a candidate provider must prove before Cloud M1 use."""

    isolation_primitive: str
    hard_cpu_limit: bool
    hard_memory_limit: bool
    hard_disk_limit: bool
    network_deny: bool
    dedicated_filesystem: bool
    blocks_metadata_service: bool
    blocks_host_mounts: bool
    blocks_runtime_socket: bool
    supports_unprivileged_execution: bool
    secret_noninheritance: bool
    exact_revision_materialization: bool
    process_tree_kill: bool
    hard_ttl: bool
    explicit_teardown: bool
    bounded_logs: bool
    bounded_artifact_export: bool
    cross_run_reuse_disabled: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "isolation_primitive",
            _safe_id(self.isolation_primitive, "isolation_primitive"),
        )
        for name in (
            "hard_cpu_limit",
            "hard_memory_limit",
            "hard_disk_limit",
            "network_deny",
            "dedicated_filesystem",
            "blocks_metadata_service",
            "blocks_host_mounts",
            "blocks_runtime_socket",
            "supports_unprivileged_execution",
            "secret_noninheritance",
            "exact_revision_materialization",
            "process_tree_kill",
            "hard_ttl",
            "explicit_teardown",
            "bounded_logs",
            "bounded_artifact_export",
            "cross_run_reuse_disabled",
        ):
            if not isinstance(getattr(self, name), bool):
                raise SandboxPolicyError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class SandboxProviderAcceptance:
    accepted: bool
    failures: tuple[str, ...]

    def require_accepted(self) -> None:
        if not self.accepted:
            raise SandboxProviderRejected(self.failures)

    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": "claw-sandbox-provider-acceptance.v1",
            "accepted": self.accepted,
            "failures": list(self.failures),
        }


def evaluate_provider_capabilities(
    capabilities: SandboxProviderCapabilities,
    *,
    policy: SandboxSecurityPolicy | None = None,
) -> SandboxProviderAcceptance:
    if not isinstance(capabilities, SandboxProviderCapabilities):
        raise SandboxPolicyError("capabilities must be SandboxProviderCapabilities")
    if policy is not None and not isinstance(policy, SandboxSecurityPolicy):
        raise SandboxPolicyError("policy must be SandboxSecurityPolicy")

    required = {
        "hard_cpu_limit": capabilities.hard_cpu_limit,
        "hard_memory_limit": capabilities.hard_memory_limit,
        "hard_disk_limit": capabilities.hard_disk_limit,
        "network_deny": capabilities.network_deny,
        "dedicated_filesystem": capabilities.dedicated_filesystem,
        "blocks_metadata_service": capabilities.blocks_metadata_service,
        "blocks_host_mounts": capabilities.blocks_host_mounts,
        "blocks_runtime_socket": capabilities.blocks_runtime_socket,
        "supports_unprivileged_execution": capabilities.supports_unprivileged_execution,
        "secret_noninheritance": capabilities.secret_noninheritance,
        "exact_revision_materialization": capabilities.exact_revision_materialization,
        "process_tree_kill": capabilities.process_tree_kill,
        "hard_ttl": capabilities.hard_ttl,
        "explicit_teardown": capabilities.explicit_teardown,
        "bounded_logs": capabilities.bounded_logs,
        "bounded_artifact_export": capabilities.bounded_artifact_export,
        "cross_run_reuse_disabled": capabilities.cross_run_reuse_disabled,
    }
    failures = tuple(name for name, supported in required.items() if not supported)
    return SandboxProviderAcceptance(accepted=not failures, failures=failures)


def validate_cloud_m1_request(
    request: SandboxLeaseRequest,
    *,
    policy: SandboxSecurityPolicy | None = None,
) -> str:
    """Validate product input against the server-owned Cloud M1 policy.

    Returns the normalized exact revision that the provider must materialize.
    """

    if not isinstance(request, SandboxLeaseRequest):
        raise SandboxPolicyError("request must be SandboxLeaseRequest")
    effective = policy or SandboxSecurityPolicy()
    if request.execution_mode is not ExecutionMode.CLOUD:
        raise SandboxPolicyError("Cloud M1 requires cloud execution mode")
    if request.network_policy is not effective.network_policy:
        raise SandboxPolicyError("Cloud M1 request cannot widen network policy")
    if request.ttl_seconds > effective.max_ttl_seconds:
        raise SandboxPolicyError("Cloud M1 request exceeds server-owned TTL ceiling")
    if not request.writable_workspace:
        raise SandboxPolicyError("Cloud M1 verified-diff execution requires a writable workspace")
    if request.requested_revision is None:
        raise SandboxPolicyError("Cloud M1 requires an exact repository revision")
    return _exact_revision(request.requested_revision, "requested_revision")


@dataclass(frozen=True, slots=True)
class VerifiedDiffEvidence:
    """Bounded B54 product evidence for a single Cloud M1 workspace result.

    This is not a replacement for P01 Evidence/Verification authority. It is a
    safe product artifact envelope that can reference/transport a verified diff.
    """

    run_id: str
    lease_id: str
    input_revision: str
    changed_files: tuple[str, ...]
    unified_diff: str
    verification_command: str
    verification_exit_status: int
    verification_output: str
    terminal_reason: str
    workspace_revision: str | None = None
    artifact_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(self, "lease_id", _safe_id(self.lease_id, "lease_id"))
        object.__setattr__(
            self,
            "input_revision",
            _exact_revision(self.input_revision, "input_revision"),
        )
        if not isinstance(self.changed_files, tuple):
            raise SandboxPolicyError("changed_files must be a tuple")
        if not 1 <= len(self.changed_files) <= MAX_VERIFIED_CHANGED_FILES:
            raise SandboxPolicyError(
                f"changed_files must contain 1 to {MAX_VERIFIED_CHANGED_FILES} paths"
            )
        normalized_paths: list[str] = []
        for path in self.changed_files:
            normalized_paths.append(_bounded_text(path, "changed_file", limit=512))
        if len(set(normalized_paths)) != len(normalized_paths):
            raise SandboxPolicyError("changed_files must not contain duplicates")
        object.__setattr__(self, "changed_files", tuple(normalized_paths))

        diff = _bounded_text(self.unified_diff, "unified_diff", limit=MAX_VERIFIED_DIFF_BYTES)
        object.__setattr__(self, "unified_diff", diff)
        object.__setattr__(
            self,
            "verification_command",
            _bounded_text(self.verification_command, "verification_command", limit=512),
        )
        if (
            isinstance(self.verification_exit_status, bool)
            or not isinstance(self.verification_exit_status, int)
            or not 0 <= self.verification_exit_status <= 255
        ):
            raise SandboxPolicyError("verification_exit_status must be between 0 and 255")
        object.__setattr__(
            self,
            "verification_output",
            _bounded_text(
                self.verification_output,
                "verification_output",
                limit=MAX_VERIFICATION_OUTPUT_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "terminal_reason",
            _safe_id(self.terminal_reason, "terminal_reason"),
        )
        if self.workspace_revision is not None:
            object.__setattr__(
                self,
                "workspace_revision",
                _exact_revision(self.workspace_revision, "workspace_revision"),
            )
        if self.artifact_ref is not None:
            object.__setattr__(
                self,
                "artifact_ref",
                _bounded_text(self.artifact_ref, "artifact_ref", limit=MAX_ARTIFACT_REF_CHARS),
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-verified-diff-evidence.v1",
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "input_revision": self.input_revision,
            "changed_files": list(self.changed_files),
            "unified_diff": redact_secrets(self.unified_diff),
            "verification_command": redact_secrets(self.verification_command),
            "verification_exit_status": self.verification_exit_status,
            "verification_output": redact_secrets(self.verification_output),
            "terminal_reason": self.terminal_reason,
            "workspace_revision": self.workspace_revision,
            "artifact_ref": redact_secrets(self.artifact_ref) if self.artifact_ref else None,
        }


class CloudM1SandboxPort(Protocol):
    """Required provider seam for the future real Cloud M1 adapter.

    Existing Phase 2 fake lease providers intentionally do not claim this richer
    contract. A selected provider must pass the conformance harness first.
    """

    def allocate(self, request: SandboxLeaseRequest) -> SandboxLease: ...

    def get(self, lease_id: str) -> SandboxLease: ...

    def terminate(self, lease_id: str, *, run_id: str, reason: str) -> SandboxLease: ...

    def collect_verified_diff(
        self,
        lease_id: str,
        *,
        run_id: str,
    ) -> VerifiedDiffEvidence: ...


def validate_terminal_lease(lease: SandboxLease, *, run_id: str) -> None:
    if not isinstance(lease, SandboxLease):
        raise SandboxPolicyError("lease must be SandboxLease")
    expected_run = _safe_id(run_id, "run_id")
    if lease.run_id != expected_run:
        raise SandboxPolicyError("terminal lease belongs to a different run")
    if lease.state not in {SandboxLeaseState.RELEASED, SandboxLeaseState.EXPIRED}:
        raise SandboxPolicyError("Cloud M1 terminal run must not retain an active lease")
