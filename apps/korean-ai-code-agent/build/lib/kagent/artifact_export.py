from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any, Protocol

from .contracts import ContractError


_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ALLOWED_EXTENSIONS = frozenset({".txt", ".md", ".json", ".csv", ".log", ".xml", ".html", ".diff", ".patch"})
_FORBIDDEN_NAMES = frozenset({".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials", "credentials.json"})
_FORBIDDEN_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".sqlite", ".db", ".exe", ".dll", ".so", ".dylib"})


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _path(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("artifact path must be a string")
    value = value.strip()
    if not value or len(value) > 512 or "\\" in value or _CONTROL_RE.search(value):
        raise ContractError("artifact path must be a bounded POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError("artifact path must remain inside workspace")
    name = path.name.lower()
    if name in _FORBIDDEN_NAMES or any(name.endswith(suffix) for suffix in _FORBIDDEN_SUFFIXES):
        raise ContractError("artifact path is a forbidden credential/binary class")
    if path.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise ContractError("artifact extension is not allowlisted")
    return str(path)


@dataclass(frozen=True, slots=True)
class ArtifactExportPolicy:
    max_files: int = 50
    max_file_bytes: int = 5 * 1024 * 1024
    max_total_bytes: int = 20 * 1024 * 1024

    def __post_init__(self) -> None:
        for name, value, low, high in (
            ("max_files", self.max_files, 1, 200),
            ("max_file_bytes", self.max_file_bytes, 1024, 25 * 1024 * 1024),
            ("max_total_bytes", self.max_total_bytes, 1024, 100 * 1024 * 1024),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ContractError(f"{name} is outside supported bounds")
        if self.max_file_bytes > self.max_total_bytes:
            raise ContractError("max_file_bytes cannot exceed max_total_bytes")


@dataclass(frozen=True, slots=True)
class SandboxArtifactCandidate:
    artifact_id: str
    run_id: str
    lease_id: str
    path: str
    kind: str
    size_bytes: int
    sha256: str
    is_symlink: bool = False

    def __post_init__(self) -> None:
        for field_name in ("artifact_id", "run_id", "lease_id", "kind"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        object.__setattr__(self, "path", _path(self.path))
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ContractError("size_bytes must be a non-negative integer")
        digest = self.sha256.strip().lower() if isinstance(self.sha256, str) else ""
        if not _SHA256_RE.fullmatch(digest):
            raise ContractError("sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "sha256", digest)
        if self.is_symlink is not False:
            raise ContractError("symlink artifacts cannot be exported")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "path": self.path,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "raw_content_in_projection": False,
        }


@dataclass(frozen=True, slots=True)
class ArtifactExportManifest:
    manifest_id: str
    run_id: str
    lease_id: str
    artifacts: tuple[SandboxArtifactCandidate, ...]

    def __post_init__(self) -> None:
        for field_name in ("manifest_id", "run_id", "lease_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if not isinstance(self.artifacts, tuple) or not self.artifacts:
            raise ContractError("artifacts must be a non-empty tuple")
        if not all(isinstance(item, SandboxArtifactCandidate) for item in self.artifacts):
            raise ContractError("manifest contains invalid artifact candidate")
        ids = [item.artifact_id for item in self.artifacts]
        paths = [item.path for item in self.artifacts]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ContractError("artifact IDs and paths must be unique")
        for item in self.artifacts:
            if item.run_id != self.run_id or item.lease_id != self.lease_id:
                raise ContractError("artifact run/lease correlation mismatch")

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.artifacts)

    def validate_against(self, policy: ArtifactExportPolicy) -> None:
        if not isinstance(policy, ArtifactExportPolicy):
            raise ContractError("policy must be ArtifactExportPolicy")
        if len(self.artifacts) > policy.max_files:
            raise ContractError("artifact count exceeds export policy")
        if any(item.size_bytes > policy.max_file_bytes for item in self.artifacts):
            raise ContractError("artifact file size exceeds export policy")
        if self.total_bytes > policy.max_total_bytes:
            raise ContractError("artifact aggregate size exceeds export policy")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-artifact-export-manifest.v1",
            "manifest_id": self.manifest_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "total_bytes": self.total_bytes,
            "artifacts": [item.safe_dict() for item in self.artifacts],
            "raw_content_in_manifest": False,
        }


class ArtifactExportPort(Protocol):
    def export(self, manifest: ArtifactExportManifest) -> str:
        ...


class UnconfiguredArtifactExportPort:
    def export(self, manifest: ArtifactExportManifest) -> str:
        raise ContractError("artifact export adapter is not configured")


REAL_ARTIFACT_EXPORT_CONFIGURED = False
