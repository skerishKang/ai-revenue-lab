"""Workspace storage boundary contracts and validation helpers (#2055).

Provides immutable value contracts, canonical object key formatting,
path traversal sanitization, quota checks, and share link validation
for Padiem Workspace storage (Claw documents/uploads, Chat files, and exports).

This module contains pure contracts and logic only — zero Cloudflare R2 calls,
zero database migrations, and zero network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Mapping

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_URL_LIKE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

# Default policy anchors from #2055
DEFAULT_FREE_MAX_STORAGE_BYTES = 100 * 1024 * 1024       # 100 MB
DEFAULT_PRO_MAX_STORAGE_BYTES = 1 * 1024 * 1024 * 1024    # 1 GB
DEFAULT_BUSINESS_MAX_STORAGE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB

DEFAULT_FREE_RETENTION_DAYS = 30
DEFAULT_SHARE_LINK_TTL_SECONDS = 7 * 24 * 60 * 60         # 7 days (604,800s)
DEFAULT_MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024          # 10 MB


class WorkspaceStoragePlanTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"


class WorkspaceStorageObjectKind(str, Enum):
    CLAW_DOCUMENT = "claw_document"
    CLAW_UPLOAD = "claw_upload"
    CHAT_FILE = "chat_file"
    EXPORT_ARTIFACT = "export_artifact"


class WorkspaceStorageBackend(str, Enum):
    R2 = "r2"
    MEMORY = "memory"


class WorkspaceStorageError(ValueError):
    """Raised when a workspace storage invariant, boundary or validation fails."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _validate_workspace_id(workspace_id: str) -> str:
    if not isinstance(workspace_id, str) or not _SAFE_ID_RE.fullmatch(workspace_id):
        raise WorkspaceStorageError(
            "invalid_workspace_id",
            "workspace_id must be a non-empty safe identifier without whitespace or special characters.",
        )
    return workspace_id


def _validate_file_name(file_name: str) -> str:
    if not isinstance(file_name, str) or not file_name.strip():
        raise WorkspaceStorageError(
            "invalid_file_name",
            "file_name must be a non-empty string.",
        )
    # Disallow path separators, path traversal, control chars
    if "/" in file_name or "\\" in file_name or ".." in file_name:
        raise WorkspaceStorageError(
            "invalid_file_name",
            "file_name cannot contain path separators or traversal sequences.",
        )
    if not _SAFE_SEGMENT_RE.fullmatch(file_name):
        raise WorkspaceStorageError(
            "invalid_file_name",
            "file_name must be a safe filename with standard alphanumeric, dot, underscore, or hyphen characters.",
        )
    return file_name


def _validate_object_key(object_key: str) -> str:
    if not isinstance(object_key, str) or not object_key.strip():
        raise WorkspaceStorageError(
            "invalid_object_key",
            "object_key must be a non-empty string.",
        )
    if _URL_LIKE_RE.match(object_key):
        raise WorkspaceStorageError(
            "invalid_object_key",
            "object_key cannot be a URL-like string.",
        )
    if "\\" in object_key:
        raise WorkspaceStorageError(
            "invalid_object_key",
            "object_key cannot contain backslashes.",
        )
    if object_key.startswith("/"):
        raise WorkspaceStorageError(
            "invalid_object_key",
            "object_key cannot be an absolute path.",
        )
    segments = object_key.split("/")
    if any(segment == "" or segment == "." or segment == ".." for segment in segments):
        raise WorkspaceStorageError(
            "invalid_object_key",
            "object_key contains empty segments or path traversal sequences.",
        )
    for seg in segments:
        if not _SAFE_SEGMENT_RE.fullmatch(seg):
            raise WorkspaceStorageError(
                "invalid_object_key",
                f"object_key segment {seg!r} contains invalid characters.",
            )
    return object_key


def _validate_content_type(content_type: str) -> str:
    if not isinstance(content_type, str) or not content_type.strip():
        raise WorkspaceStorageError(
            "invalid_content_type",
            "content_type must be a non-empty string.",
        )
    if "/" not in content_type:
        raise WorkspaceStorageError(
            "invalid_content_type",
            "content_type must be a valid MIME type format (e.g. application/pdf).",
        )
    return content_type.strip().lower()


def _validate_object_size(size_bytes: int) -> int:
    if not isinstance(size_bytes, int) or size_bytes <= 0:
        raise WorkspaceStorageError(
            "invalid_object_size",
            "size_bytes must be a strictly positive integer.",
        )
    return size_bytes


@dataclass(frozen=True, slots=True)
class WorkspaceStorageQuota:
    """Storage quota and policy bounds for a workspace."""

    workspace_id: str
    tier: WorkspaceStoragePlanTier
    max_storage_bytes: int
    max_single_file_bytes: int = DEFAULT_MAX_SINGLE_FILE_BYTES
    generated_file_retention_days: int = DEFAULT_FREE_RETENTION_DAYS
    share_link_ttl_seconds: int = DEFAULT_SHARE_LINK_TTL_SECONDS

    def __post_init__(self) -> None:
        _validate_workspace_id(self.workspace_id)
        if not isinstance(self.tier, WorkspaceStoragePlanTier):
            raise WorkspaceStorageError("invalid_workspace_id", "tier must be a WorkspaceStoragePlanTier.")
        if self.max_storage_bytes <= 0:
            raise WorkspaceStorageError("invalid_object_size", "max_storage_bytes must be strictly positive.")
        if self.max_single_file_bytes <= 0:
            raise WorkspaceStorageError("invalid_object_size", "max_single_file_bytes must be strictly positive.")
        if self.generated_file_retention_days <= 0:
            raise WorkspaceStorageError("invalid_object_size", "generated_file_retention_days must be strictly positive.")
        if self.share_link_ttl_seconds <= 0:
            raise WorkspaceStorageError("invalid_object_size", "share_link_ttl_seconds must be strictly positive.")

    @classmethod
    def default_for_tier(cls, workspace_id: str, tier: WorkspaceStoragePlanTier | str) -> WorkspaceStorageQuota:
        if isinstance(tier, str):
            try:
                tier = WorkspaceStoragePlanTier(tier.lower())
            except ValueError:
                raise WorkspaceStorageError("invalid_workspace_id", f"Unknown plan tier: {tier}")

        if tier == WorkspaceStoragePlanTier.FREE:
            return cls(
                workspace_id=workspace_id,
                tier=tier,
                max_storage_bytes=DEFAULT_FREE_MAX_STORAGE_BYTES,
                max_single_file_bytes=DEFAULT_MAX_SINGLE_FILE_BYTES,
                generated_file_retention_days=DEFAULT_FREE_RETENTION_DAYS,
                share_link_ttl_seconds=DEFAULT_SHARE_LINK_TTL_SECONDS,
            )
        elif tier == WorkspaceStoragePlanTier.PRO:
            return cls(
                workspace_id=workspace_id,
                tier=tier,
                max_storage_bytes=DEFAULT_PRO_MAX_STORAGE_BYTES,
                max_single_file_bytes=DEFAULT_MAX_SINGLE_FILE_BYTES,
                generated_file_retention_days=365,
                share_link_ttl_seconds=30 * 24 * 60 * 60,
            )
        elif tier == WorkspaceStoragePlanTier.BUSINESS:
            return cls(
                workspace_id=workspace_id,
                tier=tier,
                max_storage_bytes=DEFAULT_BUSINESS_MAX_STORAGE_BYTES,
                max_single_file_bytes=DEFAULT_MAX_SINGLE_FILE_BYTES,
                generated_file_retention_days=365 * 3,
                share_link_ttl_seconds=90 * 24 * 60 * 60,
            )
        raise WorkspaceStorageError("invalid_workspace_id", f"Unhandled tier {tier}")


@dataclass(frozen=True, slots=True)
class WorkspaceStorageObject:
    """Metadata record representing a stored object within a workspace."""

    workspace_id: str
    object_key: str
    file_name: str
    content_type: str
    size_bytes: int
    kind: WorkspaceStorageObjectKind
    is_public: bool = False
    created_at: str | None = None

    def __post_init__(self) -> None:
        _validate_workspace_id(self.workspace_id)
        _validate_object_key(self.object_key)
        _validate_file_name(self.file_name)
        _validate_content_type(self.content_type)
        _validate_object_size(self.size_bytes)
        if not isinstance(self.kind, WorkspaceStorageObjectKind):
            raise WorkspaceStorageError("invalid_object_key", "kind must be WorkspaceStorageObjectKind.")

        # Invariant: Object key must start with workspaces/{workspace_id}/
        expected_prefix = f"workspaces/{self.workspace_id}/"
        if not self.object_key.startswith(expected_prefix):
            raise WorkspaceStorageError(
                "invalid_object_key",
                f"object_key must begin with {expected_prefix!r} for workspace isolation.",
            )

        # Invariant: Private-by-default (reject public object creation)
        if self.is_public:
            raise WorkspaceStorageError(
                "unsafe_public_object",
                "Workspace storage objects are private by default; public objects are forbidden.",
            )


@dataclass(frozen=True, slots=True)
class WorkspaceStorageUsage:
    """Current aggregated storage usage for a workspace."""

    workspace_id: str
    used_storage_bytes: int
    object_count: int

    def __post_init__(self) -> None:
        _validate_workspace_id(self.workspace_id)
        if not isinstance(self.used_storage_bytes, int) or self.used_storage_bytes < 0:
            raise WorkspaceStorageError(
                "invalid_object_size",
                "used_storage_bytes must be a non-negative integer.",
            )
        if not isinstance(self.object_count, int) or self.object_count < 0:
            raise WorkspaceStorageError(
                "invalid_object_size",
                "object_count must be a non-negative integer.",
            )


@dataclass(frozen=True, slots=True)
class WorkspaceShareLink:
    """Time-bounded share link reference for an object (no public bucket)."""

    workspace_id: str
    object_key: str
    expires_at: datetime
    revoked: bool = False

    def __post_init__(self) -> None:
        _validate_workspace_id(self.workspace_id)
        _validate_object_key(self.object_key)
        if not isinstance(self.expires_at, datetime):
            raise WorkspaceStorageError(
                "share_link_expired",
                "expires_at must be a valid datetime instance.",
            )


def format_canonical_object_key(
    *,
    workspace_id: str,
    kind: WorkspaceStorageObjectKind,
    entity_id: str,
    file_name: str,
) -> str:
    """Format a canonical object key within the workspace isolation boundary."""
    _validate_workspace_id(workspace_id)
    _validate_file_name(file_name)
    if not isinstance(entity_id, str) or not _SAFE_SEGMENT_RE.fullmatch(entity_id):
        raise WorkspaceStorageError(
            "invalid_object_key",
            "entity_id must be a safe identifier segment.",
        )

    if kind == WorkspaceStorageObjectKind.CLAW_DOCUMENT:
        path = f"workspaces/{workspace_id}/claw/documents/{entity_id}/{file_name}"
    elif kind == WorkspaceStorageObjectKind.CLAW_UPLOAD:
        path = f"workspaces/{workspace_id}/claw/uploads/{entity_id}/{file_name}"
    elif kind == WorkspaceStorageObjectKind.CHAT_FILE:
        path = f"workspaces/{workspace_id}/chat/files/{entity_id}/{file_name}"
    elif kind == WorkspaceStorageObjectKind.EXPORT_ARTIFACT:
        path = f"workspaces/{workspace_id}/exports/{entity_id}/{file_name}"
    else:
        raise WorkspaceStorageError("invalid_object_key", f"Unsupported object kind: {kind}")

    return _validate_object_key(path)


def check_storage_admission(
    *,
    quota: WorkspaceStorageQuota,
    usage: WorkspaceStorageUsage,
    new_object_size_bytes: int,
) -> None:
    """Verify that a new object does not exceed single-file or aggregate workspace quotas."""
    if quota.workspace_id != usage.workspace_id:
        raise WorkspaceStorageError(
            "invalid_workspace_id",
            f"Quota workspace_id {quota.workspace_id!r} does not match usage {usage.workspace_id!r}.",
        )
    _validate_object_size(new_object_size_bytes)

    if new_object_size_bytes > quota.max_single_file_bytes:
        raise WorkspaceStorageError(
            "single_file_too_large",
            f"File size {new_object_size_bytes} exceeds maximum single file limit {quota.max_single_file_bytes}.",
        )

    if usage.used_storage_bytes + new_object_size_bytes > quota.max_storage_bytes:
        raise WorkspaceStorageError(
            "quota_exceeded",
            f"Workspace storage quota exceeded: {usage.used_storage_bytes + new_object_size_bytes} > {quota.max_storage_bytes}.",
        )


def validate_share_link(
    share_link: WorkspaceShareLink,
    *,
    now: datetime | None = None,
) -> None:
    """Validate that a share link has not been revoked or expired."""
    if share_link.revoked:
        raise WorkspaceStorageError(
            "share_link_revoked",
            "This share link has been revoked.",
        )

    reference_time = now or datetime.now(timezone.utc)
    # Ensure reference_time is timezone-aware if expires_at is timezone-aware
    expires_at = share_link.expires_at
    if expires_at.tzinfo is not None and reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    elif expires_at.tzinfo is None and reference_time.tzinfo is not None:
        reference_time = reference_time.astimezone(timezone.utc).replace(tzinfo=None)

    if expires_at <= reference_time:
        raise WorkspaceStorageError(
            "share_link_expired",
            "This share link has expired.",
        )


def validate_storage_backend(backend: str | WorkspaceStorageBackend) -> WorkspaceStorageBackend:
    """Verify backend is supported; reject arbitrary/unsupported storage backends."""
    if isinstance(backend, WorkspaceStorageBackend):
        return backend
    if isinstance(backend, str):
        try:
            return WorkspaceStorageBackend(backend.lower())
        except ValueError:
            pass
    raise WorkspaceStorageError(
        "unsupported_storage_backend",
        f"Unsupported storage backend: {backend!r}. Only R2 or in-memory backends are allowed.",
    )