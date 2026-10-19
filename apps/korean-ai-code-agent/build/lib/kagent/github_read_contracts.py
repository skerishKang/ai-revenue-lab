from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import re
from typing import Any, Protocol

from .contracts import ContractError
from .security import redact_secrets

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_EXACT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONTEXT_TEXT = 20_000
_MAX_CONTEXT_ITEMS = 100


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


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
        raise ContractError(f"{field_name} must be an exact 40-hex revision")
    return value


def _digest(value: str, field_name: str) -> str:
    value = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _bounded_text(value: str, field_name: str, limit: int = _MAX_CONTEXT_TEXT) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = redact_secrets(value.strip())
    if len(value) > limit:
        raise ContractError(f"{field_name} exceeds bounded read envelope")
    return value


class GitHubReadCapability(str, Enum):
    REPOSITORY_METADATA = "repository.metadata"
    TREE_FILE_BLOB = "repository.content"
    ISSUE_CONTEXT = "issue.context"
    PULL_REQUEST_CONTEXT = "pull_request.context"
    CHECK_STATUS = "check_status.read"


class GitHubContextKind(str, Enum):
    ISSUE = "issue"
    PULL_REQUEST = "pull_request"
    CHECK_STATUS = "check_status"


@dataclass(frozen=True, slots=True)
class GitHubInstallationBinding:
    binding_ref: str
    installation_ref: str
    actor_ref: str
    workspace_ref: str
    allowed_repositories: tuple[str, ...]
    capabilities: tuple[GitHubReadCapability, ...] = (
        GitHubReadCapability.REPOSITORY_METADATA,
        GitHubReadCapability.TREE_FILE_BLOB,
        GitHubReadCapability.ISSUE_CONTEXT,
        GitHubReadCapability.PULL_REQUEST_CONTEXT,
        GitHubReadCapability.CHECK_STATUS,
    )
    github_app: bool = True

    def __post_init__(self) -> None:
        for name in ("binding_ref", "installation_ref", "actor_ref", "workspace_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if self.github_app is not True:
            raise ContractError("canonical GitHub connector binding requires GitHub App authority")
        if not isinstance(self.allowed_repositories, tuple) or not self.allowed_repositories:
            raise ContractError("GitHub installation requires a non-empty repository allowlist")
        repositories = tuple(_repository(item) for item in self.allowed_repositories)
        if len(repositories) != len(set(item.casefold() for item in repositories)):
            raise ContractError("GitHub repository allowlist must be unique")
        object.__setattr__(self, "allowed_repositories", repositories)
        if not isinstance(self.capabilities, tuple) or not self.capabilities:
            raise ContractError("GitHub installation requires explicit read capabilities")
        normalized: list[GitHubReadCapability] = []
        for item in self.capabilities:
            try:
                capability = item if isinstance(item, GitHubReadCapability) else GitHubReadCapability(item)
            except (TypeError, ValueError) as exc:
                raise ContractError("unknown GitHub read capability") from exc
            normalized.append(capability)
        if len(normalized) != len(set(normalized)):
            raise ContractError("GitHub read capabilities must be unique")
        object.__setattr__(self, "capabilities", tuple(normalized))

    def require_repository(self, repository: str) -> str:
        repository = _repository(repository)
        allowed = {item.casefold(): item for item in self.allowed_repositories}
        try:
            return allowed[repository.casefold()]
        except KeyError as exc:
            raise ContractError("repository is outside GitHub installation allowlist") from exc

    def require_capability(self, capability: GitHubReadCapability) -> None:
        if capability not in self.capabilities:
            raise ContractError("GitHub read capability is not granted")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "installation_ref": self.installation_ref,
            "actor_ref": self.actor_ref,
            "workspace_ref": self.workspace_ref,
            "allowed_repositories": list(self.allowed_repositories),
            "capabilities": [item.value for item in self.capabilities],
            "github_app": True,
            "raw_installation_token": False,
            "raw_private_key": False,
            "personal_access_token": False,
        }


@dataclass(frozen=True, slots=True)
class GitHubRepositoryReadRequest:
    request_id: str
    repository: str
    exact_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _ref(self.request_id, "request_id"))
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(self, "exact_revision", _sha(self.exact_revision, "exact_revision"))


@dataclass(frozen=True, slots=True)
class GitHubRepositorySnapshot:
    request_id: str
    repository: str
    requested_revision: str
    observed_revision: str
    default_branch: str
    tree_sha256: str
    file_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _ref(self.request_id, "request_id"))
        object.__setattr__(self, "repository", _repository(self.repository))
        requested = _sha(self.requested_revision, "requested_revision")
        observed = _sha(self.observed_revision, "observed_revision")
        if requested != observed:
            raise ContractError("GitHub repository snapshot revision mismatch")
        object.__setattr__(self, "requested_revision", requested)
        object.__setattr__(self, "observed_revision", observed)
        object.__setattr__(self, "default_branch", _ref(self.default_branch, "default_branch"))
        object.__setattr__(self, "tree_sha256", _digest(self.tree_sha256, "tree_sha256"))
        if isinstance(self.file_count, bool) or not isinstance(self.file_count, int) or not 0 <= self.file_count <= 1_000_000:
            raise ContractError("file_count outside supported bounds")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "repository": self.repository,
            "requested_revision": self.requested_revision,
            "observed_revision": self.observed_revision,
            "default_branch": self.default_branch,
            "tree_sha256": self.tree_sha256,
            "file_count": self.file_count,
            "repository_contents_embedded": False,
        }


@dataclass(frozen=True, slots=True)
class GitHubContextReadRequest:
    request_id: str
    repository: str
    kind: GitHubContextKind
    number: int | None = None
    exact_revision: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _ref(self.request_id, "request_id"))
        object.__setattr__(self, "repository", _repository(self.repository))
        if not isinstance(self.kind, GitHubContextKind):
            try:
                object.__setattr__(self, "kind", GitHubContextKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid GitHub context kind") from exc
        if self.kind in {GitHubContextKind.ISSUE, GitHubContextKind.PULL_REQUEST}:
            if isinstance(self.number, bool) or not isinstance(self.number, int) or not 1 <= self.number <= 2_147_483_647:
                raise ContractError("issue/PR context requires a positive number")
            if self.exact_revision is not None:
                raise ContractError("issue/PR context must not carry exact_revision")
        else:
            if self.number is not None:
                raise ContractError("check status context must not carry issue/PR number")
            if self.exact_revision is None:
                raise ContractError("check status context requires exact_revision")
            object.__setattr__(self, "exact_revision", _sha(self.exact_revision, "exact_revision"))


@dataclass(frozen=True, slots=True)
class GitHubContextSnapshot:
    request_id: str
    repository: str
    kind: GitHubContextKind
    context_ref: str
    text: str
    item_count: int
    exact_revision: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _ref(self.request_id, "request_id"))
        object.__setattr__(self, "repository", _repository(self.repository))
        if not isinstance(self.kind, GitHubContextKind):
            try:
                object.__setattr__(self, "kind", GitHubContextKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid GitHub context kind") from exc
        object.__setattr__(self, "context_ref", _ref(self.context_ref, "context_ref"))
        object.__setattr__(self, "text", _bounded_text(self.text, "text"))
        if isinstance(self.item_count, bool) or not isinstance(self.item_count, int) or not 0 <= self.item_count <= _MAX_CONTEXT_ITEMS:
            raise ContractError("GitHub context item_count outside supported bounds")
        if self.kind is GitHubContextKind.CHECK_STATUS:
            if self.exact_revision is None:
                raise ContractError("check status snapshot requires exact_revision")
            object.__setattr__(self, "exact_revision", _sha(self.exact_revision, "exact_revision"))
        elif self.exact_revision is not None:
            raise ContractError("issue/PR context snapshot must not carry exact_revision")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "repository": self.repository,
            "kind": self.kind.value,
            "context_ref": self.context_ref,
            "text": self.text,
            "item_count": self.item_count,
            "exact_revision": self.exact_revision,
            "untrusted_external_content": self.kind in {GitHubContextKind.ISSUE, GitHubContextKind.PULL_REQUEST},
            "raw_credentials": False,
        }


class GitHubReadPort(Protocol):
    def read_repository(self, request: GitHubRepositoryReadRequest) -> GitHubRepositorySnapshot:
        ...

    def read_context(self, request: GitHubContextReadRequest) -> GitHubContextSnapshot:
        ...


class UnconfiguredGitHubReadPort:
    def read_repository(self, request: GitHubRepositoryReadRequest) -> GitHubRepositorySnapshot:
        raise ContractError("GitHub read adapter is not configured")

    def read_context(self, request: GitHubContextReadRequest) -> GitHubContextSnapshot:
        raise ContractError("GitHub read adapter is not configured")


class GitHubReadService:
    def __init__(self, binding: GitHubInstallationBinding, port: GitHubReadPort | None = None) -> None:
        if not isinstance(binding, GitHubInstallationBinding):
            raise ContractError("binding must be GitHubInstallationBinding")
        self.binding = binding
        self.port = port or UnconfiguredGitHubReadPort()

    def read_repository(self, request: GitHubRepositoryReadRequest) -> GitHubRepositorySnapshot:
        repository = self.binding.require_repository(request.repository)
        self.binding.require_capability(GitHubReadCapability.REPOSITORY_METADATA)
        self.binding.require_capability(GitHubReadCapability.TREE_FILE_BLOB)
        snapshot = self.port.read_repository(request)
        if not isinstance(snapshot, GitHubRepositorySnapshot):
            raise ContractError("GitHub read adapter returned invalid repository snapshot")
        if snapshot.request_id != request.request_id or snapshot.repository.casefold() != repository.casefold():
            raise ContractError("GitHub repository snapshot correlation mismatch")
        if snapshot.requested_revision != request.exact_revision or snapshot.observed_revision != request.exact_revision:
            raise ContractError("GitHub repository snapshot exact revision mismatch")
        return snapshot

    def read_context(self, request: GitHubContextReadRequest) -> GitHubContextSnapshot:
        repository = self.binding.require_repository(request.repository)
        capability = {
            GitHubContextKind.ISSUE: GitHubReadCapability.ISSUE_CONTEXT,
            GitHubContextKind.PULL_REQUEST: GitHubReadCapability.PULL_REQUEST_CONTEXT,
            GitHubContextKind.CHECK_STATUS: GitHubReadCapability.CHECK_STATUS,
        }[request.kind]
        self.binding.require_capability(capability)
        snapshot = self.port.read_context(request)
        if not isinstance(snapshot, GitHubContextSnapshot):
            raise ContractError("GitHub read adapter returned invalid context snapshot")
        if snapshot.request_id != request.request_id or snapshot.repository.casefold() != repository.casefold() or snapshot.kind is not request.kind:
            raise ContractError("GitHub context snapshot correlation mismatch")
        if request.kind is GitHubContextKind.CHECK_STATUS and snapshot.exact_revision != request.exact_revision:
            raise ContractError("GitHub check status revision mismatch")
        return snapshot


class DeterministicFakeGitHubReadPort:
    def __init__(self) -> None:
        self.repository_reads: list[GitHubRepositoryReadRequest] = []
        self.context_reads: list[GitHubContextReadRequest] = []

    def read_repository(self, request: GitHubRepositoryReadRequest) -> GitHubRepositorySnapshot:
        self.repository_reads.append(request)
        tree = hashlib.sha256(f"{request.repository}:{request.exact_revision}".encode("utf-8")).hexdigest()
        return GitHubRepositorySnapshot(
            request_id=request.request_id,
            repository=request.repository,
            requested_revision=request.exact_revision,
            observed_revision=request.exact_revision,
            default_branch="main",
            tree_sha256=tree,
            file_count=42,
        )

    def read_context(self, request: GitHubContextReadRequest) -> GitHubContextSnapshot:
        self.context_reads.append(request)
        if request.kind is GitHubContextKind.CHECK_STATUS:
            return GitHubContextSnapshot(
                request_id=request.request_id,
                repository=request.repository,
                kind=request.kind,
                context_ref=f"checks:{request.exact_revision}",
                text="all required checks passed",
                item_count=3,
                exact_revision=request.exact_revision,
            )
        return GitHubContextSnapshot(
            request_id=request.request_id,
            repository=request.repository,
            kind=request.kind,
            context_ref=f"{request.kind.value}:{request.number}",
            text="bounded external GitHub context",
            item_count=2,
        )


GITHUB_APP_PREFERRED = True
PERSONAL_ACCESS_TOKEN_PREFERRED = False
REAL_GITHUB_READ_CONFIGURED = False
REPOSITORY_ALLOWLIST_REQUIRED = True
EXTERNAL_GITHUB_TEXT_IS_UNTRUSTED = True
