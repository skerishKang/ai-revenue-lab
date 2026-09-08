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


def test_workspace_id_uses_object_key_safe_segment_policy() -> None:
    # Valid alphanumeric, dash, dot, underscore segments
    valid_ids = ["ws-1", "workspace_100", "ws.prod.1", "WS123"]
    for valid_id in valid_ids:
        quota = WorkspaceStorageQuota.default_for_tier(valid_id, WorkspaceStoragePlanTier.FREE)
        assert quota.workspace_id == valid_id


def test_workspace_id_with_colon_is_rejected() -> None:
    # Colon is explicitly rejected to match object key path segment safety
    with pytest.raises(WorkspaceStorageError) as exc:
        WorkspaceStorageQuota.default_for_tier("ws:tenant:1", WorkspaceStoragePlanTier.FREE)
    assert exc.value.code == "invalid_workspace_id"


def test_korean_display_file_name_is_allowed_on_object() -> None:
    # Korean display filenames for Padiem Claw (견적서.docx, 발주서.hwpx)
    korean_names = ["견적서.docx", "발주서.hwpx", "보고서_최종본_2026.pdf"]
    for idx, k_name in enumerate(korean_names):
        safe_storage_name = f"doc_{idx}.bin"
        key = format_canonical_object_key(
            workspace_id="ws-123",
            kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
            entity_id="doc-456",
            storage_file_name=safe_storage_name,
        )
        assert key == f"workspaces/ws-123/claw/documents/doc-456/{safe_storage_name}"
        assert k_name not in key

        obj = WorkspaceStorageObject(
            workspace_id="ws-123",
            object_key=key,
            file_name=k_name,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=2048,
            kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
        )
        assert obj.file_name == k_name


def test_korean_display_file_name_rejected_as_storage_file_name() -> None:
    # Raw non-ASCII / Unicode display names are rejected as storage object-key segments
    with pytest.raises(WorkspaceStorageError) as exc:
        format_canonical_object_key(
            workspace_id="ws-123",
            kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
            entity_id="doc-456",
            storage_file_name="견적서.docx",
        )
    assert exc.value.code == "invalid_object_key"


def test_file_name_with_path_separator_is_rejected() -> None:
    for sep_name in ["sub/file.docx", "folder\\file.hwpx", "/etc/file.txt", "file/"]:
        with pytest.raises(WorkspaceStorageError) as exc:
            WorkspaceStorageObject(
                workspace_id="ws-123",
                object_key="workspaces/ws-123/claw/documents/doc-456/file.docx",
                file_name=sep_name,
                content_type="text/plain",
                size_bytes=100,
                kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
            )
        assert exc.value.code == "invalid_file_name"


def test_file_name_with_traversal_is_rejected() -> None:
    for bad_name in ["..", "../file.docx", "..\\file.hwpx", "normal..name"]:
        with pytest.raises(WorkspaceStorageError) as exc:
            WorkspaceStorageObject(
                workspace_id="ws-123",
                object_key="workspaces/ws-123/claw/documents/doc-456/file.docx",
                file_name=bad_name,
                content_type="text/plain",
                size_bytes=100,
                kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
            )
        assert exc.value.code == "invalid_file_name"


def test_format_canonical_object_keys() -> None:
    doc_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.CLAW_DOCUMENT,
        entity_id="doc-456",
        storage_file_name="report.pdf",
    )
    assert doc_key == "workspaces/ws-123/claw/documents/doc-456/report.pdf"

    upload_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.CLAW_UPLOAD,
        entity_id="up-789",
        storage_file_name="data.xlsx",
    )
    assert upload_key == "workspaces/ws-123/claw/uploads/up-789/data.xlsx"

    chat_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.CHAT_FILE,
        entity_id="file-101",
        storage_file_name="image.png",
    )
    assert chat_key == "workspaces/ws-123/chat/files/file-101/image.png"

    export_key = format_canonical_object_key(
        workspace_id="ws-123",
        kind=WorkspaceStorageObjectKind.EXPORT_ARTIFACT,
        entity_id="exp-202",
        storage_file_name="archive.zip",
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
        "workspaces/ws-1/claw/has space/file.txt",
        "workspaces/ws-1/claw/has?query/file.txt",
        "workspaces/ws-1/claw/has#fragment/file.txt",
        "workspaces/ws-1/claw/has%20encoded/file.txt",
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


def test_share_link_rejects_cross_workspace_object_key() -> None:
    now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
    future = now + timedelta(days=2)

    with pytest.raises(WorkspaceStorageError) as exc:
        WorkspaceShareLink(
            workspace_id="ws-alpha",
            object_key="workspaces/ws-beta/claw/documents/doc-1/file.txt",
            expires_at=future,
            revoked=False,
        )
    assert exc.value.code == "invalid_object_key"


def test_unsupported_storage_backend_rejected() -> None:
    assert validate_storage_backend(WorkspaceStorageBackend.R2) == WorkspaceStorageBackend.R2
    assert validate_storage_backend("r2") == WorkspaceStorageBackend.R2
    assert validate_storage_backend("memory") == WorkspaceStorageBackend.MEMORY

    for forbidden in ["dothome", "ftp", "s3", "local_disk", ""]:
        with pytest.raises(WorkspaceStorageError) as exc:
            validate_storage_backend(forbidden)
        assert exc.value.code == "unsupported_storage_backend"