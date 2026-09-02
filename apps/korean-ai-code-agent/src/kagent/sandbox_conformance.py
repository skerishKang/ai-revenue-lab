from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from .contracts import ContractError, NetworkPolicy, SandboxLeaseRequest
from .security import redact_secrets


class IsolationPrimitive(str, Enum):
    MICROVM = "microvm"
    VM = "vm"
    CONTAINER = "container"
    REMOTE_WORKSPACE = "remote_workspace"
    UNKNOWN = "unknown"


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _ref(value: str, field_name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} has invalid reference syntax")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain raw credential material")
    return value


def _bounded_int(value: int, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _strict_bool(value: bool, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field_name} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class SandboxSecurityPolicy:
    """Server-owned Cloud M1 minimum policy, independent of provider brand."""

    network_default: NetworkPolicy = NetworkPolicy.OFF
    privileged_runtime_allowed: bool = False
    host_mounts_allowed: bool = False
    runtime_socket_exposed: bool = False
    provider_metadata_access_allowed: bool = False
    host_secret_inheritance_allowed: bool = False
    workspace_reuse_allowed: bool = False
    mutable_source_revision_allowed: bool = False
    max_ttl_seconds: int = 3600
    max_artifact_bytes: int = 25 * 1024 * 1024
    max_artifact_count: int = 100
    max_terminal_output_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.network_default is not NetworkPolicy.OFF:
            raise ContractError("Cloud M1 network default must be off")
        for field_name in (
            "privileged_runtime_allowed",
            "host_mounts_allowed",
            "runtime_socket_exposed",
            "provider_metadata_access_allowed",
            "host_secret_inheritance_allowed",
            "workspace_reuse_allowed",
            "mutable_source_revision_allowed",
        ):
            if getattr(self, field_name) is not False:
                raise ContractError(f"Cloud M1 {field_name} must be false")
        object.__setattr__(self, "max_ttl_seconds", _bounded_int(self.max_ttl_seconds, "max_ttl_seconds", minimum=60, maximum=3600))
        object.__setattr__(self, "max_artifact_bytes", _bounded_int(self.max_artifact_bytes, "max_artifact_bytes", minimum=1024, maximum=100 * 1024 * 1024))
        object.__setattr__(self, "max_artifact_count", _bounded_int(self.max_artifact_count, "max_artifact_count", minimum=1, maximum=1000))
        object.__setattr__(self, "max_terminal_output_bytes", _bounded_int(self.max_terminal_output_bytes, "max_terminal_output_bytes", minimum=1024, maximum=20 * 1024 * 1024))


@dataclass(frozen=True, slots=True)
class SandboxProviderCapabilities:
    provider_id: str
    isolation_primitive: IsolationPrimitive
    server_owned_lifecycle: bool
    exact_revision_materialization: bool
    checkout_hooks_disabled: bool
    network_deny_by_default: bool
    egress_policy_enforced: bool
    privileged_runtime_disabled: bool
    host_mounts_disabled: bool
    runtime_socket_hidden: bool
    provider_metadata_blocked: bool
    host_secret_inheritance_disabled: bool
    dedicated_workspace_per_run: bool
    cross_run_reuse_disabled: bool
    cpu_limit_enforced: bool
    memory_limit_enforced: bool
    disk_limit_enforced: bool
    process_limit_enforced: bool
    ttl_enforced: bool
    cancellation_kills_workload: bool
    teardown_guaranteed: bool
    artifact_allowlist_enforced: bool
    artifact_size_limit_enforced: bool
    terminal_output_bounded: bool
    terminal_output_sanitized: bool
    image_or_snapshot_provenance: bool
    run_lease_audit_correlation: bool
    preview_ports_private_by_default: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _ref(self.provider_id, "provider_id"))
        if not isinstance(self.isolation_primitive, IsolationPrimitive):
            try:
                object.__setattr__(self, "isolation_primitive", IsolationPrimitive(self.isolation_primitive))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid isolation_primitive") from exc
        for field_name in self.__dataclass_fields__:
            if field_name in {"provider_id", "isolation_primitive"}:
                continue
            _strict_bool(getattr(self, field_name), field_name)

    def safe_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider_id": self.provider_id,
            "isolation_primitive": self.isolation_primitive.value,
        }
        for field_name in self.__dataclass_fields__:
            if field_name in result:
                continue
            result[field_name] = getattr(self, field_name)
        return result


_REQUIRED_CAPABILITIES = (
    "server_owned_lifecycle",
    "exact_revision_materialization",
    "checkout_hooks_disabled",
    "network_deny_by_default",
    "egress_policy_enforced",
    "privileged_runtime_disabled",
    "host_mounts_disabled",
    "runtime_socket_hidden",
    "provider_metadata_blocked",
    "host_secret_inheritance_disabled",
    "dedicated_workspace_per_run",
    "cross_run_reuse_disabled",
    "cpu_limit_enforced",
    "memory_limit_enforced",
    "disk_limit_enforced",
    "process_limit_enforced",
    "ttl_enforced",
    "cancellation_kills_workload",
    "teardown_guaranteed",
    "artifact_allowlist_enforced",
    "artifact_size_limit_enforced",
    "terminal_output_bounded",
    "terminal_output_sanitized",
    "image_or_snapshot_provenance",
    "run_lease_audit_correlation",
    "preview_ports_private_by_default",
)


@dataclass(frozen=True, slots=True)
class SandboxProviderAssessment:
    provider_id: str
    isolation_primitive: IsolationPrimitive
    accepted_for_cloud_m1: bool
    missing_controls: tuple[str, ...]
    policy_version: str = "claw-cloud-m1-sandbox.v1"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "isolation_primitive": self.isolation_primitive.value,
            "accepted_for_cloud_m1": self.accepted_for_cloud_m1,
            "missing_controls": list(self.missing_controls),
            "policy_version": self.policy_version,
        }


class SandboxProviderConformanceGate:
    def __init__(self, policy: SandboxSecurityPolicy | None = None) -> None:
        self.policy = policy or SandboxSecurityPolicy()

    def assess(self, capabilities: SandboxProviderCapabilities) -> SandboxProviderAssessment:
        if not isinstance(capabilities, SandboxProviderCapabilities):
            raise ContractError("capabilities must be SandboxProviderCapabilities")
        missing = [
            field_name
            for field_name in _REQUIRED_CAPABILITIES
            if getattr(capabilities, field_name) is not True
        ]
        if capabilities.isolation_primitive is IsolationPrimitive.UNKNOWN:
            missing.append("known_isolation_primitive")
        return SandboxProviderAssessment(
            provider_id=capabilities.provider_id,
            isolation_primitive=capabilities.isolation_primitive,
            accepted_for_cloud_m1=not missing,
            missing_controls=tuple(missing),
        )

    def require_accepted(self, capabilities: SandboxProviderCapabilities) -> SandboxProviderAssessment:
        assessment = self.assess(capabilities)
        if not assessment.accepted_for_cloud_m1:
            raise ContractError(
                "sandbox provider fails Cloud M1 controls: " + ", ".join(assessment.missing_controls)
            )
        return assessment

    def validate_lease_request(self, request: SandboxLeaseRequest) -> None:
        if not isinstance(request, SandboxLeaseRequest):
            raise ContractError("request must be SandboxLeaseRequest")
        if request.network_policy is not self.policy.network_default:
            raise ContractError("Cloud M1 lease request violates deny-by-default network policy")
        if request.ttl_seconds > self.policy.max_ttl_seconds:
            raise ContractError("Cloud M1 lease request exceeds policy TTL")
        if not request.requested_revision:
            raise ContractError("Cloud M1 requires an exact immutable requested_revision")


@dataclass(frozen=True, slots=True)
class SandboxArtifactRef:
    artifact_id: str
    kind: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _ref(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "kind", _ref(self.kind, "kind", limit=64))
        object.__setattr__(self, "size_bytes", _bounded_int(self.size_bytes, "size_bytes", minimum=0, maximum=100 * 1024 * 1024))
        digest = self.sha256.strip().lower() if isinstance(self.sha256, str) else ""
        if not _SHA256_RE.fullmatch(digest):
            raise ContractError("sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True, slots=True)
class SandboxArtifactManifest:
    run_id: str
    lease_id: str
    artifacts: tuple[SandboxArtifactRef, ...]
    terminal_output_bytes: int
    terminal_output_sanitized: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _ref(self.run_id, "run_id"))
        object.__setattr__(self, "lease_id", _ref(self.lease_id, "lease_id"))
        if not isinstance(self.artifacts, tuple) or not all(isinstance(item, SandboxArtifactRef) for item in self.artifacts):
            raise ContractError("artifacts must be a tuple of SandboxArtifactRef")
        if len({item.artifact_id for item in self.artifacts}) != len(self.artifacts):
            raise ContractError("artifact IDs must be unique")
        object.__setattr__(self, "terminal_output_bytes", _bounded_int(self.terminal_output_bytes, "terminal_output_bytes", minimum=0, maximum=20 * 1024 * 1024))
        object.__setattr__(self, "terminal_output_sanitized", _strict_bool(self.terminal_output_sanitized, "terminal_output_sanitized"))

    @property
    def total_artifact_bytes(self) -> int:
        return sum(item.size_bytes for item in self.artifacts)

    def validate_against(self, policy: SandboxSecurityPolicy) -> None:
        if not isinstance(policy, SandboxSecurityPolicy):
            raise ContractError("policy must be SandboxSecurityPolicy")
        if len(self.artifacts) > policy.max_artifact_count:
            raise ContractError("artifact count exceeds Cloud M1 policy")
        if any(item.size_bytes > policy.max_artifact_bytes for item in self.artifacts):
            raise ContractError("artifact size exceeds Cloud M1 policy")
        if self.total_artifact_bytes > policy.max_artifact_bytes * policy.max_artifact_count:
            raise ContractError("total artifact export exceeds Cloud M1 policy")
        if self.terminal_output_bytes > policy.max_terminal_output_bytes:
            raise ContractError("terminal output exceeds Cloud M1 policy")
        if not self.terminal_output_sanitized:
            raise ContractError("terminal output must be sanitized before export")


@dataclass(frozen=True, slots=True)
class VerifiedDiffEvidence:
    run_id: str
    lease_id: str
    repository_ref: str
    input_revision: str
    changed_files: tuple[str, ...]
    unified_diff_sha256: str
    verification_command_id: str
    verification_exit_code: int
    verification_output_sha256: str
    terminal_reason: str
    final_revision_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _ref(self.run_id, "run_id"))
        object.__setattr__(self, "lease_id", _ref(self.lease_id, "lease_id"))
        object.__setattr__(self, "repository_ref", _ref(self.repository_ref, "repository_ref"))
        object.__setattr__(self, "input_revision", _ref(self.input_revision, "input_revision"))
        if not isinstance(self.changed_files, tuple) or len(self.changed_files) > 100:
            raise ContractError("changed_files must be a tuple with at most 100 entries")
        normalized: list[str] = []
        for path in self.changed_files:
            if not isinstance(path, str) or not path.strip() or len(path.strip()) > 512 or any(ord(ch) < 32 for ch in path):
                raise ContractError("changed file path is invalid or unbounded")
            normalized.append(path.strip())
        if len(set(normalized)) != len(normalized):
            raise ContractError("changed file paths must be unique")
        object.__setattr__(self, "changed_files", tuple(normalized))
        for field_name in ("unified_diff_sha256", "verification_output_sha256"):
            value = getattr(self, field_name)
            digest = value.strip().lower() if isinstance(value, str) else ""
            if not _SHA256_RE.fullmatch(digest):
                raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
            object.__setattr__(self, field_name, digest)
        object.__setattr__(self, "verification_command_id", _ref(self.verification_command_id, "verification_command_id"))
        if isinstance(self.verification_exit_code, bool) or not isinstance(self.verification_exit_code, int) or not -255 <= self.verification_exit_code <= 255:
            raise ContractError("verification_exit_code must be bounded")
        object.__setattr__(self, "terminal_reason", _ref(self.terminal_reason, "terminal_reason"))
        if self.final_revision_ref is not None:
            object.__setattr__(self, "final_revision_ref", _ref(self.final_revision_ref, "final_revision_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "repository_ref": self.repository_ref,
            "input_revision": self.input_revision,
            "changed_files": list(self.changed_files),
            "unified_diff_sha256": self.unified_diff_sha256,
            "verification_command_id": self.verification_command_id,
            "verification_exit_code": self.verification_exit_code,
            "verification_output_sha256": self.verification_output_sha256,
            "terminal_reason": self.terminal_reason,
            "final_revision_ref": self.final_revision_ref,
            "raw_diff_in_projection": False,
            "raw_terminal_output_in_projection": False,
        }


REAL_SANDBOX_PROVIDER_SELECTED = False
REAL_SANDBOX_PROVIDER_CALLS = 0
PRODUCTION_SANDBOX_CLAIM = False
