from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Protocol

from .contracts import ContractError
from .security import redact_secrets


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_EXACT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _repository(value: str) -> str:
    if not isinstance(value, str) or not _REPOSITORY_RE.fullmatch(value.strip()):
        raise ContractError("repository must use bounded owner/repo syntax")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError("repository must not contain credential material")
    return value


def _sha(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _EXACT_SHA_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact 40-hex commit SHA")
    return value


def _digest(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class RepositoryMaterializationPolicy:
    max_files: int = 100_000
    max_bytes: int = 2 * 1024 * 1024 * 1024
    checkout_hooks_enabled: bool = False
    submodules_enabled: bool = False
    lfs_enabled: bool = False
    credential_helper_inheritance: bool = False
    symlink_entries_allowed: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.max_files, bool) or not isinstance(self.max_files, int) or not 1 <= self.max_files <= 1_000_000:
            raise ContractError("max_files outside supported bounds")
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or not 1 <= self.max_bytes <= 20 * 1024 * 1024 * 1024:
            raise ContractError("max_bytes outside supported bounds")
        for field_name in (
            "checkout_hooks_enabled",
            "submodules_enabled",
            "lfs_enabled",
            "credential_helper_inheritance",
            "symlink_entries_allowed",
        ):
            if getattr(self, field_name) is not False:
                raise ContractError(f"Cloud M1 {field_name} must be false")


@dataclass(frozen=True, slots=True)
class RepositoryMaterializationRequest:
    request_id: str
    run_id: str
    lease_id: str
    repository: str
    exact_revision: str

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "lease_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(self, "exact_revision", _sha(self.exact_revision, "exact_revision"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "repository": self.repository,
            "exact_revision": self.exact_revision,
            "mutable_ref_input": False,
            "submodules": False,
            "lfs": False,
            "checkout_hooks": False,
            "credential_helper_inheritance": False,
        }


@dataclass(frozen=True, slots=True)
class RepositoryMaterializationReceipt:
    request_id: str
    run_id: str
    lease_id: str
    repository: str
    requested_revision: str
    observed_revision: str
    tree_sha256: str
    file_count: int
    materialized_bytes: int
    symlink_count: int = 0

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "lease_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        object.__setattr__(self, "repository", _repository(self.repository))
        requested = _sha(self.requested_revision, "requested_revision")
        observed = _sha(self.observed_revision, "observed_revision")
        if requested != observed:
            raise ContractError("observed repository revision does not match requested revision")
        object.__setattr__(self, "requested_revision", requested)
        object.__setattr__(self, "observed_revision", observed)
        object.__setattr__(self, "tree_sha256", _digest(self.tree_sha256, "tree_sha256"))
        for name, value, high in (
            ("file_count", self.file_count, 1_000_000),
            ("materialized_bytes", self.materialized_bytes, 20 * 1024 * 1024 * 1024),
            ("symlink_count", self.symlink_count, 1_000_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high:
                raise ContractError(f"{name} outside supported bounds")

    def validate_against(self, request: RepositoryMaterializationRequest, policy: RepositoryMaterializationPolicy) -> None:
        if not isinstance(request, RepositoryMaterializationRequest) or not isinstance(policy, RepositoryMaterializationPolicy):
            raise ContractError("invalid materialization validation inputs")
        if (
            self.request_id != request.request_id
            or self.run_id != request.run_id
            or self.lease_id != request.lease_id
            or self.repository != request.repository
            or self.requested_revision != request.exact_revision
        ):
            raise ContractError("materialization receipt correlation mismatch")
        if self.file_count > policy.max_files:
            raise ContractError("materialized repository file count exceeds policy")
        if self.materialized_bytes > policy.max_bytes:
            raise ContractError("materialized repository size exceeds policy")
        if not policy.symlink_entries_allowed and self.symlink_count:
            raise ContractError("Cloud M1 repository contains symlink entries")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "repository": self.repository,
            "requested_revision": self.requested_revision,
            "observed_revision": self.observed_revision,
            "tree_sha256": self.tree_sha256,
            "file_count": self.file_count,
            "materialized_bytes": self.materialized_bytes,
            "symlink_count": self.symlink_count,
            "repository_content_in_receipt": False,
        }


class RepositoryMaterializerPort(Protocol):
    def materialize(self, request: RepositoryMaterializationRequest, policy: RepositoryMaterializationPolicy) -> RepositoryMaterializationReceipt:
        ...


class UnconfiguredRepositoryMaterializer:
    def materialize(self, request: RepositoryMaterializationRequest, policy: RepositoryMaterializationPolicy) -> RepositoryMaterializationReceipt:
        raise ContractError("repository materialization adapter is not configured")


class DeterministicFakeRepositoryMaterializer:
    def __init__(self, *, file_count: int = 10, materialized_bytes: int = 1000, symlink_count: int = 0) -> None:
        self.file_count = file_count
        self.materialized_bytes = materialized_bytes
        self.symlink_count = symlink_count
        self.requests: list[RepositoryMaterializationRequest] = []

    def materialize(self, request: RepositoryMaterializationRequest, policy: RepositoryMaterializationPolicy) -> RepositoryMaterializationReceipt:
        if not isinstance(request, RepositoryMaterializationRequest):
            raise ContractError("request must be RepositoryMaterializationRequest")
        if not isinstance(policy, RepositoryMaterializationPolicy):
            raise ContractError("policy must be RepositoryMaterializationPolicy")
        self.requests.append(request)
        tree_digest = hashlib.sha256(f"{request.repository}:{request.exact_revision}".encode("utf-8")).hexdigest()
        receipt = RepositoryMaterializationReceipt(
            request_id=request.request_id,
            run_id=request.run_id,
            lease_id=request.lease_id,
            repository=request.repository,
            requested_revision=request.exact_revision,
            observed_revision=request.exact_revision,
            tree_sha256=tree_digest,
            file_count=self.file_count,
            materialized_bytes=self.materialized_bytes,
            symlink_count=self.symlink_count,
        )
        receipt.validate_against(request, policy)
        return receipt


REAL_GIT_NETWORK_MATERIALIZATION_CONFIGURED = False
