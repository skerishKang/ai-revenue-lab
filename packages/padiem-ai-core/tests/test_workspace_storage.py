"""Tests for Workspace Storage boundary contracts and helpers (#2055)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from padiem_ai_core.workspace_storage import (
    DEFAULT_BUSINESS_MAX_STORAGE_BYTES,
    DEFAULT_FREE_MAX_STORAGE_BYTES,
    DEFAULT_FREE_RETENTION_DAYS,
    DEFAULT_MAX_SINGLE_FILE_BYTES,
    DEFAULT_PRO_MAX_STORAGE_BYTES,
    DEFAULT_SHARE_LINK_TTL_SECONDS,
    WorkspaceShareLink,
    WorkspaceStorageBackend,
    WorkspaceStorageError,
    WorkspaceStorageObject,
    WorkspaceStorageObjectKind,
    WorkspaceStoragePlanTier,
    WorkspaceStorageQuota,
    WorkspaceStorageUsage,
    check_storage_admission,
    format_canonical_object_key,
    validate_share_link,
    validate_storage_backend,
)


def test_default_tier_quotas() -> None:
    free = WorkspaceStorageQuota.default_for_tier("ws-1", WorkspaceStoragePlanTier.FREE)
    assert free.max_storage_bytes == DEFAULT_FREE_MAX_STORAGE_BYTES
    assert free.max_single_file_bytes == DEFAULT_MAX_SINGLE_FILE_BYTES
    assert free.generated_file_retention_days == DEFAULT_FREE_RETENTION_DAYS
    assert free.share_link_ttl_seconds == DEFAULT_SHARE_LINK_TTL_SECONDS

    pro = WorkspaceStorageQuota.default_for_tier("ws-2", "pro")
    assert pro.max_storage_bytes == DEFAULT_PRO_MAX_STORAGE_BYTES
    assert pro.max_single_file_bytes == DEFAULT_MAX_SINGLE_FILE_BYTES
    assert pro.tier == WorkspaceStoragePlanTier.PRO

    biz = WorkspaceStorageQuota.default_for_tier("ws-3", "business")
    assert biz.max_storage_bytes == DEFAULT_BUSINESS_MAX_STORAGE_BYTES
    assert biz.tier == WorkspaceStoragePlanTier.BUSINESS

    with pytest.raises(WorkspaceStorageError) as exc:
        WorkspaceStorageQuota.default_for_tier("ws-1", "unlimited")
    assert exc.value.code == "invalid_workspace_id"


def test_format_canonical_object_keys() -> None:
    doc_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
        entity_id="doc-456",
        file_name="report.pdf",
    )
    assert doc_key == "workspaces/ws-123/claw/documents/doc-456/report.pdf"

    upload_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.CLAW_UPLOAD,
        entity_id="up-789",
        file_name="data.xlsx",
    )
    assert upload_key == "workspaces/ws-123/claw/uploads/up-789/data.xlsx"

    chat_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.CHAT_FILE,
        entity_id="file-101",
        file_name="image.png",
    )
    assert chat_key == "workspaces/ws-123/chat/files/file-101/image.png"

    export_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.EXPORT_ARTIFACT,
        entity_id="exp-202",
        file_name="archive.zip",
    )
    assert export_key == "workspaces/ws-123/exports/exp-202/archive.zip"


@pytest.mark.parametrize(
    "traversal_key",
    [
        "../etc/passwd",
        "workspaces/ws-1/../../etc/passwd",
        "/absolute/path/file.txt",
        "workspaces\\ws-1\\file.txt",
        "http://bucket.example.com/file.txt",
        "https://r2.cloudflare.com/obj.bin",
        "workspaces/ws-1//empty_segment.txt",
        "workspaces/ws-1/./cur.txt",
        "workspaces/ws-1/../other_ws/file.txt",
    ],
)
def test_traversal_and_invalid_object_keys_rejected(traversal_key: str) -> None:
    with pytest.raises(WorkspaceStorageError) as exc:
        WorkspaceStorageObject(
            workspace_id="ws-1",
            object_key=traversal_key,
            file_name="file.txt",
            content_type="text/plain",
            size_bytes=100,
            kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
        )
    assert exc.value.code == "invalid_object_key"


def test_cross_workspace_prefix_rejected() -> None:
    with pytest.raises(WorkspaceStorageError) as exc:
        WorkspaceStorageObject(
            workspace_id="ws-alpha",
            object_key="workspaces/ws-beta/claw/documents/doc-1/file.txt",
            file_name="file.txt",
            content_type="text/plain",
            size_bytes=100,
            kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
        )
    assert exc.value.code == "invalid_object_key"


def test_private_by_default_enforced() -> None:
    # Public object is strictly forbidden
    with pytest.raises(WorkspaceStorageError) as exc:
        WorkspaceStorageObject(
            workspace_id="ws-1",
            object_key="workspaces/ws-1/claw/documents/doc-1/file.txt",
            file_name="file.txt",
            content_type="text/plain",
            size_bytes=100,
            kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
            is_public=True,
        )
    assert exc.value.code == "unsafe_public_object"


@pytest.mark.parametrize("invalid_size", [0, -1, -500, "100"])
def test_invalid_object_size_rejected(invalid_size: object) -> None:
    with pytest.raises(WorkspaceStorageError) as exc:
        WorkspaceStorageObject(
            workspace_id="ws-1",
            object_key="workspaces/ws-1/claw/documents/doc-1/file.txt",
            file_name="file.txt",
            content_type="text/plain",
            size_bytes=invalid_size,  # type: ignore[arg-type]
            kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
        )
    assert exc.value.code == "invalid_object_size"


def test_quota_admission_checks() -> None:
    quota = WorkspaceStorageQuota(
        workspace_id="ws-1",
        tier=WorkspaceStoragePlanTier.FREE,
        max_storage_bytes=100 * 1024 * 1024,  # 100 MB
        max_single_file_bytes=10 * 1024 * 1024,  # 10 MB
    )
    usage = WorkspaceStorageUsage(
        workspace_id="ws-1",
        used_storage_bytes=95 * 1024 * 1024,  # 95 MB used
        object_count=10,
    )

    # 4 MB file -> fits within single limit (4 <= 10) and aggregate (95 + 4 = 99 <= 100)
    check_storage_admission(
        quota=quota,
        usage=usage,
        new_object_size_bytes=4 * 1024 * 1024,
    )

    # 12 MB file -> exceeds single file limit
    with pytest.raises(WorkspaceStorageError) as exc_single:
        check_storage_admission(
            quota=quota,
            usage=usage,
            new_object_size_bytes=12 * 1024 * 1024,
        )
    assert exc_single.value.code == "single_file_too_large"

    # 6 MB file -> exceeds aggregate storage limit (95 + 6 = 101 > 100)
    with pytest.raises(WorkspaceStorageError) as exc_quota:
        check_storage_admission(
            quota=quota,
            usage=usage,
            new_object_size_bytes=6 * 1024 * 1024,
        )
    assert exc_quota.value.code == "quota_exceeded"

    # Mismatched workspace usage & quota
    mismatched_usage = WorkspaceStorageUsage(
        workspace_id="ws-foreign",
        used_storage_bytes=10,
        object_count=1,
    )
    with pytest.raises(WorkspaceStorageError) as exc_mismatch:
        check_storage_admission(
            quota=quota,
            usage=mismatched_usage,
            new_object_size_bytes=100,
        )
    assert exc_mismatch.value.code == "invalid_workspace_id"


def test_share_link_expiry_and_revocation() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    future = now + timedelta(days=2)
    past = now - timedelta(minutes=1)

    # Valid active link
    valid_link = WorkspaceShareLink(
        workspace_id="ws-1",
        object_key="workspaces/ws-1/claw/documents/doc-1/file.txt",
        expires_at=future,
        revoked=False,
    )
    validate_share_link(valid_link, now=now)

    # Expired link
    expired_link = WorkspaceShareLink(
        workspace_id="ws-1",
        object_key="workspaces/ws-1/claw/documents/doc-1/file.txt",
        expires_at=past,
        revoked=False,
    )
    with pytest.raises(WorkspaceStorageError) as exc_exp:
        validate_share_link(expired_link, now=now)
    assert exc_exp.value.code == "share_link_expired"

    # Revoked link
    revoked_link = WorkspaceShareLink(
        workspace_id="ws-1",
        object_key="workspaces/ws-1/claw/documents/doc-1/file.txt",
        expires_at=future,
        revoked=True,
    )
    with pytest.raises(WorkspaceStorageError) as exc_rev:
        validate_share_link(revoked_link, now=now)
    assert exc_rev.value.code == "share_link_revoked"


def test_unsupported_storage_backend_rejected() -> None:
    assert validate_storage_backend(WorkspaceStorageBackend.R2) == WorkspaceStorageBackend.R2
    assert validate_storage_backend("r2") == WorkspaceStorageBackend.R2
    assert validate_storage_backend("memory") == WorkspaceStorageBackend.MEMORY

    for forbidden in ["dothome", "ftp", "s3", "local_disk", ""]:
        with pytest.raises(WorkspaceStorageError) as exc:
            validate_storage_backend(forbidden)
        assert exc.value.code == "unsupported_storage_backend"