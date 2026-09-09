from __future__ import annotations

import inspect
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

SINGLE_FILE_MAX_BYTES = 10 * 1024 * 1024
GENERATED_DOCUMENT_RETENTION_DAYS = 30
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class WorkspaceStorageError(RuntimeError):
    pass


class WorkspaceStorageAccessError(WorkspaceStorageError):
    pass


@dataclass(frozen=True, slots=True)
class ClawDocumentMetadata:
    document_id: str
    tenant_id: str
    object_key: str
    filename: str
    media_type: str
    byte_length: int
    created_at: datetime
    expires_at: datetime

    def public_projection(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "media_type": self.media_type,
            "byte_length": self.byte_length,
            "expires_at": self.expires_at.isoformat(),
        }


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be a bounded safe identifier")
    return value


def _safe_filename(filename: str) -> str:
    if not isinstance(filename, str):
        raise ValueError("filename must be text")
    leaf = filename.replace("\\", "/").split("/")[-1].strip()
    leaf = _SAFE_FILENAME_RE.sub("-", leaf).strip(".-")
    if not leaf:
        leaf = "document.docx"
    if not leaf.lower().endswith(".docx"):
        leaf += ".docx"
    return leaf[:120]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _document_id() -> str:
    return "doc_" + uuid.uuid4().hex


def _object_key(tenant_id: str, document_id: str, filename: str) -> str:
    return f"workspaces/{tenant_id}/claw/documents/{document_id}/{filename}"


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise WorkspaceStorageError("workspace document metadata is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkspaceStorageError("workspace document metadata is invalid")
    return parsed


def _metadata_from_row(row: dict[str, Any]) -> ClawDocumentMetadata:
    try:
        return ClawDocumentMetadata(
            document_id=str(row["document_id"]),
            tenant_id=str(row["tenant_id"]),
            object_key=str(row["object_key"]),
            filename=str(row["filename"]),
            media_type=str(row["media_type"]),
            byte_length=int(row["byte_length"]),
            created_at=_parse_time(row["created_at"]),
            expires_at=_parse_time(row["expires_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceStorageError("workspace document metadata is invalid") from exc


class D1ClawDocumentMetadataStore:
    def __init__(self, db: Any) -> None:
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _run(self, sql: str, *values: Any) -> Any:
        stmt = self.db.prepare(sql)
        if values:
            stmt = stmt.bind(*values)
        return await stmt.run()

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        stmt = self.db.prepare(sql)
        if values:
            stmt = stmt.bind(*values)
        return _row_to_dict(await stmt.first())

    async def insert(self, metadata: ClawDocumentMetadata) -> None:
        await self._run(
            "INSERT INTO claw_document_metadata "
            "(document_id, tenant_id, object_key, filename, media_type, byte_length, created_at, expires_at, deleted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            metadata.document_id,
            metadata.tenant_id,
            metadata.object_key,
            metadata.filename,
            metadata.media_type,
            metadata.byte_length,
            metadata.created_at.isoformat(),
            metadata.expires_at.isoformat(),
        )

    async def get_active(self, document_id: str) -> ClawDocumentMetadata | None:
        row = await self._first(
            "SELECT document_id, tenant_id, object_key, filename, media_type, byte_length, created_at, expires_at "
            "FROM claw_document_metadata WHERE document_id=? AND deleted_at IS NULL",
            document_id,
        )
        return _metadata_from_row(row) if row else None

    async def mark_deleted(self, document_id: str, deleted_at: datetime) -> None:
        await self._run(
            "UPDATE claw_document_metadata SET deleted_at=? WHERE document_id=? AND deleted_at IS NULL",
            deleted_at.isoformat(),
            document_id,
        )


class WorkspaceDocumentStore:
    """#2055 platform/workspace storage projection for generated Claw documents.

    Object bytes live only in private R2. D1 stores bounded metadata. Access is
    authorized by the canonical Control Plane auth-session tenant projection;
    callers never provide object keys or filesystem paths.
    """

    def __init__(self, metadata_store: D1ClawDocumentMetadataStore, r2_bucket: Any) -> None:
        if metadata_store is None:
            raise ValueError("metadata store is required")
        if r2_bucket is None:
            raise ValueError("private R2 binding is required")
        self.metadata_store = metadata_store
        self.r2_bucket = r2_bucket

    async def put_generated_docx(
        self,
        *,
        tenant_id: str,
        filename: str,
        body: bytes,
        now: datetime | None = None,
    ) -> ClawDocumentMetadata:
        tenant = _safe_identifier("tenant_id", tenant_id)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            raise ValueError("document body must be bytes")
        payload = bytes(body)
        if not payload or len(payload) > SINGLE_FILE_MAX_BYTES:
            raise ValueError("generated document exceeds workspace storage file limit")
        clean_filename = _safe_filename(filename)
        document_id = _document_id()
        object_key = _object_key(tenant, document_id, clean_filename)
        created_at = now or _utcnow()
        expires_at = created_at + timedelta(days=GENERATED_DOCUMENT_RETENTION_DAYS)
        metadata = ClawDocumentMetadata(
            document_id=document_id,
            tenant_id=tenant,
            object_key=object_key,
            filename=clean_filename,
            media_type=DOCX_MEDIA_TYPE,
            byte_length=len(payload),
            created_at=created_at,
            expires_at=expires_at,
        )
        try:
            result = self.r2_bucket.put(
                object_key,
                payload,
                httpMetadata={"contentType": DOCX_MEDIA_TYPE},
            )
            if inspect.isawaitable(result):
                await result
            await self.metadata_store.insert(metadata)
        except Exception as exc:
            try:
                cleanup = self.r2_bucket.delete(object_key)
                if inspect.isawaitable(cleanup):
                    await cleanup
            except Exception:
                pass
            raise WorkspaceStorageError("workspace document storage failed") from exc
        return metadata

    async def get_for_tenant(
        self,
        *,
        tenant_id: str,
        document_id: str,
        now: datetime | None = None,
    ) -> tuple[ClawDocumentMetadata, bytes] | None:
        tenant = _safe_identifier("tenant_id", tenant_id)
        doc_id = _safe_identifier("document_id", document_id)
        metadata = await self.metadata_store.get_active(doc_id)
        if metadata is None:
            return None
        if metadata.tenant_id != tenant:
            raise WorkspaceStorageAccessError("workspace document access denied")
        current = now or _utcnow()
        if current >= metadata.expires_at:
            await self.delete_for_tenant(tenant_id=tenant, document_id=doc_id, now=current)
            return None
        try:
            obj = self.r2_bucket.get(metadata.object_key)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                return None
            body = getattr(obj, "body", obj)
            array_buffer = getattr(body, "arrayBuffer", None)
            if callable(array_buffer):
                body = array_buffer()
                if inspect.isawaitable(body):
                    body = await body
            payload = bytes(body)
        except Exception as exc:
            raise WorkspaceStorageError("workspace document read failed") from exc
        if len(payload) != metadata.byte_length:
            raise WorkspaceStorageError("workspace document length mismatch")
        return metadata, payload

    async def delete_for_tenant(
        self,
        *,
        tenant_id: str,
        document_id: str,
        now: datetime | None = None,
    ) -> bool:
        tenant = _safe_identifier("tenant_id", tenant_id)
        doc_id = _safe_identifier("document_id", document_id)
        metadata = await self.metadata_store.get_active(doc_id)
        if metadata is None:
            return False
        if metadata.tenant_id != tenant:
            raise WorkspaceStorageAccessError("workspace document access denied")
        try:
            result = self.r2_bucket.delete(metadata.object_key)
            if inspect.isawaitable(result):
                await result
            await self.metadata_store.mark_deleted(doc_id, now or _utcnow())
        except Exception as exc:
            raise WorkspaceStorageError("workspace document deletion failed") from exc
        return True
