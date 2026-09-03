from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import re
from typing import Any

from .contracts import ContractError


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:/")
_MAX_MANIFEST_PATHS = 256
_FORBIDDEN_TRANSFER_PARTS = frozenset({
    ".env",
    ".ssh",
    ".aws",
    ".gnupg",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
})


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _manifest_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ContractError("hybrid manifest path must be bounded")
    raw = value.strip().replace("\\", "/")
    if _WINDOWS_DRIVE_PATH_RE.match(raw):
        raise ContractError("hybrid manifest paths must be relative and traversal-free")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError("hybrid manifest paths must be relative and traversal-free")
    lowered = {part.casefold() for part in path.parts}
    if lowered & _FORBIDDEN_TRANSFER_PARTS:
        raise ContractError("hybrid manifest contains a credential-sensitive path")
    if any(part.casefold().endswith((".pem", ".key", ".pfx", ".p12")) for part in path.parts):
        raise ContractError("hybrid manifest contains a private-key-like path")
    return str(path)


class ExecutionTarget(str, Enum):
    CLOUD_SANDBOX = "cloud_sandbox"
    LOCAL_AGENT = "local_agent"
    HYBRID = "hybrid"
    NO_SAFE_TARGET = "no_safe_target"


class SourceLocation(str, Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    MIXED = "mixed"


class ExecutionPreference(str, Enum):
    AUTO = "auto"
    CLOUD = "cloud"
    LOCAL = "local"
    LOCAL_FIRST = "local_first"


@dataclass(frozen=True, slots=True)
class HybridInputManifest:
    manifest_id: str
    root_ref: str
    paths: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_id", _ref(self.manifest_id, "manifest_id"))
        object.__setattr__(self, "root_ref", _ref(self.root_ref, "root_ref"))
        if not isinstance(self.paths, tuple) or not self.paths or len(self.paths) > _MAX_MANIFEST_PATHS:
            raise ContractError("hybrid manifest must contain 1-256 explicit paths")
        normalized = tuple(_manifest_path(path) for path in self.paths)
        if len(set(path.casefold() for path in normalized)) != len(normalized):
            raise ContractError("hybrid manifest paths must be unique")
        object.__setattr__(self, "paths", normalized)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "root_ref": self.root_ref,
            "paths": list(self.paths),
            "whole_disk_sync": False,
            "credential_paths_allowed": False,
            "apply_results_back_automatically": False,
        }


@dataclass(frozen=True, slots=True)
class ExecutionTargetRequest:
    run_id: str
    source_ref: str
    source_location: SourceLocation
    preference: ExecutionPreference = ExecutionPreference.AUTO
    local_device_online: bool = False
    local_capability_granted: bool = False
    cloud_sandbox_available: bool = False
    cloud_sandbox_conformant: bool = False
    transfer_allowed: bool = False
    requires_local_only_tool: bool = False
    isolation_required: bool = False
    hybrid_manifest: HybridInputManifest | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _ref(self.run_id, "run_id"))
        object.__setattr__(self, "source_ref", _ref(self.source_ref, "source_ref"))
        if not isinstance(self.source_location, SourceLocation):
            try:
                object.__setattr__(self, "source_location", SourceLocation(self.source_location))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid source_location") from exc
        if not isinstance(self.preference, ExecutionPreference):
            try:
                object.__setattr__(self, "preference", ExecutionPreference(self.preference))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid execution preference") from exc
        for field_name in (
            "local_device_online",
            "local_capability_granted",
            "cloud_sandbox_available",
            "cloud_sandbox_conformant",
            "transfer_allowed",
            "requires_local_only_tool",
            "isolation_required",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ContractError(f"{field_name} must be boolean")
        if self.hybrid_manifest is not None and not isinstance(self.hybrid_manifest, HybridInputManifest):
            raise ContractError("hybrid_manifest must be HybridInputManifest or None")


@dataclass(frozen=True, slots=True)
class ExecutionTargetDecision:
    run_id: str
    target: ExecutionTarget
    reason_code: str
    source_ref: str
    hybrid_manifest_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _ref(self.run_id, "run_id"))
        object.__setattr__(self, "source_ref", _ref(self.source_ref, "source_ref"))
        object.__setattr__(self, "reason_code", _ref(self.reason_code, "reason_code"))
        if not isinstance(self.target, ExecutionTarget):
            try:
                object.__setattr__(self, "target", ExecutionTarget(self.target))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid execution target") from exc
        if self.hybrid_manifest_ref is not None:
            object.__setattr__(self, "hybrid_manifest_ref", _ref(self.hybrid_manifest_ref, "hybrid_manifest_ref"))
        if self.target is ExecutionTarget.HYBRID and self.hybrid_manifest_ref is None:
            raise ContractError("hybrid target requires manifest reference")
        if self.target is not ExecutionTarget.HYBRID and self.hybrid_manifest_ref is not None:
            raise ContractError("non-hybrid target must not carry hybrid manifest reference")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target": self.target.value,
            "reason_code": self.reason_code,
            "source_ref": self.source_ref,
            "hybrid_manifest_ref": self.hybrid_manifest_ref,
            "model_provider_route": False,
            "p01_execution_authority": False,
            "result_apply_is_separate_write": True,
        }


def resolve_execution_target(request: ExecutionTargetRequest) -> ExecutionTargetDecision:
    if not isinstance(request, ExecutionTargetRequest):
        raise ContractError("request must be ExecutionTargetRequest")

    local_ready = request.local_device_online and request.local_capability_granted
    cloud_ready = request.cloud_sandbox_available and request.cloud_sandbox_conformant

    if request.requires_local_only_tool:
        if local_ready:
            return _decision(request, ExecutionTarget.LOCAL_AGENT, "local_only_tool")
        return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "local_only_tool_unavailable")

    if request.source_location is SourceLocation.LOCAL and request.isolation_required:
        if not request.transfer_allowed:
            return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "local_transfer_forbidden")
        if not cloud_ready:
            return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "conformant_cloud_unavailable")
        if request.hybrid_manifest is None:
            return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "hybrid_manifest_required")
        return _decision(
            request,
            ExecutionTarget.HYBRID,
            "local_source_isolated_in_cloud",
            manifest=request.hybrid_manifest,
        )

    if request.source_location is SourceLocation.CLOUD:
        if request.preference in {ExecutionPreference.LOCAL, ExecutionPreference.LOCAL_FIRST} and local_ready:
            if not request.transfer_allowed:
                if cloud_ready:
                    return _decision(request, ExecutionTarget.CLOUD_SANDBOX, "cloud_source_transfer_forbidden")
                return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "cloud_source_transfer_forbidden_no_cloud")
            return _decision(request, ExecutionTarget.LOCAL_AGENT, "client_local_preference_with_authority")
        if cloud_ready:
            return _decision(request, ExecutionTarget.CLOUD_SANDBOX, "cloud_source_cloud_ready")
        if request.transfer_allowed and local_ready:
            return _decision(request, ExecutionTarget.LOCAL_AGENT, "cloud_unavailable_local_authorized")
        return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "cloud_source_no_authorized_target")

    if request.source_location is SourceLocation.LOCAL:
        if request.preference is ExecutionPreference.CLOUD:
            if request.transfer_allowed and cloud_ready:
                if request.hybrid_manifest is None:
                    return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "hybrid_manifest_required")
                return _decision(
                    request,
                    ExecutionTarget.HYBRID,
                    "cloud_preference_with_bounded_local_transfer",
                    manifest=request.hybrid_manifest,
                )
            if local_ready:
                return _decision(request, ExecutionTarget.LOCAL_AGENT, "cloud_preference_not_authority")
            return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "local_source_cloud_preference_unsafe")
        if local_ready:
            return _decision(request, ExecutionTarget.LOCAL_AGENT, "local_source_local_ready")
        if request.transfer_allowed and cloud_ready and request.hybrid_manifest is not None:
            return _decision(
                request,
                ExecutionTarget.HYBRID,
                "local_offline_bounded_cloud_transfer",
                manifest=request.hybrid_manifest,
            )
        return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "local_source_local_unavailable")

    # MIXED source requires both explicit local authority and a conformant cloud target.
    if not local_ready:
        return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "mixed_source_local_unavailable")
    if not request.transfer_allowed:
        return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "mixed_source_transfer_forbidden")
    if not cloud_ready:
        return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "mixed_source_cloud_unavailable")
    if request.hybrid_manifest is None:
        return _decision(request, ExecutionTarget.NO_SAFE_TARGET, "hybrid_manifest_required")
    return _decision(request, ExecutionTarget.HYBRID, "mixed_source_bounded_hybrid", manifest=request.hybrid_manifest)


def _decision(
    request: ExecutionTargetRequest,
    target: ExecutionTarget,
    reason_code: str,
    *,
    manifest: HybridInputManifest | None = None,
) -> ExecutionTargetDecision:
    return ExecutionTargetDecision(
        run_id=request.run_id,
        target=target,
        reason_code=reason_code,
        source_ref=request.source_ref,
        hybrid_manifest_ref=manifest.manifest_id if manifest is not None else None,
    )


B14_ROUTER_DUPLICATED = False
P01_ORCHESTRATION_DUPLICATED = False
CLIENT_PREFERENCE_IS_AUTHORITY = False
WHOLE_DISK_SYNC_SUPPORTED = False
RESULT_APPLY_IS_SEPARATE_WRITE = True
REAL_EXECUTION_PERFORMED_BY_ROUTER = False
PRODUCTION_MUTATION = False
