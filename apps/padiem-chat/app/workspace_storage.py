from __future__ import annotations

import hashlib
import inspect
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile

from padiem_ai_core.document_normalization import DocumentNormalizationError, validate_ooxml_archive

SINGLE_FILE_MAX_BYTES = 10 * 1024 * 1024
GENERATED_DOCUMENT_RETENTION_DAYS = 30
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_WEB_XLSX_BYTES = 1_048_576
WEB_XLSX_RETENTION = timedelta(days=1)
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

    async def list_web_xlsx(self, *, tenant_id: str, key_prefix: str,
                            now: datetime, limit: int = 40) -> list[ClawDocumentMetadata]:
        if type(limit) is not int or not 1 <= limit <= 40:
            raise ValueError("bounded web office listing required")
        stmt = self.db.prepare(
            "SELECT document_id, tenant_id, object_key, filename, media_type, byte_length, created_at, expires_at "
            "FROM claw_document_metadata WHERE tenant_id=? AND deleted_at IS NULL "
            "AND substr(object_key, 1, length(?))=? AND expires_at>? "
            "ORDER BY created_at DESC, document_id DESC LIMIT ?"
        ).bind(tenant_id, key_prefix, key_prefix, now.isoformat(), limit)
        result = await stmt.all()
        if isinstance(result, (list, tuple)):
            rows = result
        elif isinstance(result, dict):
            rows = result.get("results")
        else:
            rows = getattr(result, "results", None)
            if rows is None:
                try:
                    rows = list(result)
                except (TypeError, ValueError) as exc:
                    raise WorkspaceStorageError("web Office metadata list is unavailable") from exc
        if rows is None:
            raise WorkspaceStorageError("web Office metadata list is unavailable")
        records = [_row_to_dict(row) for row in rows]
        if any(row is None for row in records):
            raise WorkspaceStorageError("web Office metadata list is malformed")
        return [_metadata_from_row(row) for row in records]


async def _read_r2_object_bytes(obj: Any) -> bytes:
    """Read bytes from a real R2ObjectBody or a bytes-shaped test double."""
    array_buffer = getattr(obj, "arrayBuffer", None)
    if callable(array_buffer):
        data = array_buffer()
        if inspect.isawaitable(data):
            data = await data
        to_bytes = getattr(data, "to_bytes", None)
        if callable(to_bytes):
            data = to_bytes()
        return bytes(data)

    body = getattr(obj, "body", obj)
    return bytes(body)


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
            payload = await _read_r2_object_bytes(obj)
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

    # #3580 WEB-FIRST: user-selected XLSX ORIGINAL bytes. This is a storage
    # surface, not P01 permission to process the workbook or Drive WRITE.
    @staticmethod
    def _web_xlsx_prefix(tenant_id: str, owner_id: str, workspace_id: str) -> str:
        tenant = _safe_identifier("tenant_id", tenant_id)
        owner = _safe_identifier("owner_id", owner_id)
        workspace = _safe_identifier("workspace_id", workspace_id)
        return f"workspaces/{tenant}/claw/web-office/{owner}/{workspace}/"

    @staticmethod
    def _web_xlsx_projection(metadata: ClawDocumentMetadata, prefix: str) -> dict[str, Any]:
        relative = metadata.object_key.removeprefix(prefix)
        parts = relative.split("/")
        if (not metadata.object_key.startswith(prefix)
                or len(parts) != 3 or parts[0] != metadata.document_id
                or len(parts[1]) != 64 or not re.fullmatch(r"[0-9a-f]{64}", parts[1])
                or parts[2] != metadata.filename
                or metadata.media_type != XLSX_MEDIA_TYPE):
            raise WorkspaceStorageError("web XLSX metadata scope invalid")
        return {
            "document_id": metadata.document_id,
            "filename": metadata.filename,
            "size_bytes": metadata.byte_length,
            "source_sha256": parts[1],
            "expires_at": metadata.expires_at.isoformat(),
            "original_immutable": True,
            "processing_authorized": False,
        }

    async def put_web_xlsx(self, *, tenant_id: str, owner_id: str,
                           workspace_id: str, filename: str, body: bytes,
                           now: datetime | None = None) -> dict[str, Any]:
        prefix = self._web_xlsx_prefix(tenant_id, owner_id, workspace_id)
        if (type(filename) is not str or not 1 <= len(filename) <= 155
                or filename in (".", "..")
                or filename != filename.strip()
                or any(ord(ch) < 32 or ch in '<>:"/\\|?*' for ch in filename)
                or not filename.lower().endswith(".xlsx")):
            raise ValueError("bounded XLSX basename required")
        if not isinstance(body, bytes) or not 0 < len(body) <= MAX_WEB_XLSX_BYTES:
            raise ValueError("web Office XLSX exceeds upload limit")
        try:
            validate_ooxml_archive(body)
            with ZipFile(BytesIO(body)) as archive:
                members = set(archive.namelist())
                if ("[Content_Types].xml" not in members
                        or "xl/workbook.xml" not in members
                        or not any(n.startswith("xl/worksheets/") and n.endswith(".xml")
                                   for n in members)):
                    raise ValueError("not an XLSX workbook")
        except (DocumentNormalizationError, BadZipFile, ValueError) as exc:
            raise ValueError("invalid or unsafe XLSX workbook") from exc
        current = now or _utcnow()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("aware timestamp required")
        doc_id = _document_id()
        digest = hashlib.sha256(body).hexdigest()
        key = f"{prefix}{doc_id}/{digest}/{filename}"
        metadata = ClawDocumentMetadata(
            document_id=doc_id, tenant_id=tenant_id, object_key=key,
            filename=filename, media_type=XLSX_MEDIA_TYPE,
            byte_length=len(body), created_at=current,
            expires_at=current + WEB_XLSX_RETENTION,
        )
        try:
            written = self.r2_bucket.put(
                key, body, httpMetadata={"contentType": XLSX_MEDIA_TYPE},
            )
            if inspect.isawaitable(written):
                await written
            await self.metadata_store.insert(metadata)
        except Exception as exc:
            try:
                cleanup = self.r2_bucket.delete(key)
                if inspect.isawaitable(cleanup):
                    await cleanup
            except Exception:
                pass
            raise WorkspaceStorageError("web XLSX write failed") from exc
        return self._web_xlsx_projection(metadata, prefix)

    async def list_web_xlsx(self, *, tenant_id: str, owner_id: str,
                            workspace_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
        prefix = self._web_xlsx_prefix(tenant_id, owner_id, workspace_id)
        current = now or _utcnow()
        method = getattr(self.metadata_store, "list_web_xlsx", None)
        if not callable(method):
            raise WorkspaceStorageError("web XLSX metadata listing unavailable")
        records = method(tenant_id=tenant_id, key_prefix=prefix, now=current)
        if inspect.isawaitable(records):
            records = await records
        if not isinstance(records, list) or len(records) > 40:
            raise WorkspaceStorageError("web XLSX metadata listing malformed")
        return [self._web_xlsx_projection(row, prefix) for row in records]

    async def get_web_xlsx_metadata(self, *, tenant_id: str, owner_id: str,
                                    workspace_id: str, document_id: str,
                                    now: datetime | None = None) -> dict[str, Any] | None:
        """Verify owner-scoped ORIGINAL metadata without reading R2 content.

        Merely selecting an uploaded file must never imply approval to read its
        bytes for processing. This method does not call the R2 binding.
        """
        prefix = self._web_xlsx_prefix(tenant_id, owner_id, workspace_id)
        doc_id = _safe_identifier("document_id", document_id)
        metadata = await self.metadata_store.get_active(doc_id)
        if metadata is None or metadata.tenant_id != tenant_id:
            return None
        if not metadata.object_key.startswith(prefix + doc_id + "/"):
            return None
        current = now or _utcnow()
        if current >= metadata.expires_at:
            return None
        return self._web_xlsx_projection(metadata, prefix)

    async def get_web_xlsx(self, *, tenant_id: str, owner_id: str,
                           workspace_id: str, document_id: str,
                           now: datetime | None = None) -> tuple[dict[str, Any], bytes] | None:
        prefix = self._web_xlsx_prefix(tenant_id, owner_id, workspace_id)
        doc_id = _safe_identifier("document_id", document_id)
        metadata = await self.metadata_store.get_active(doc_id)
        if metadata is None or metadata.tenant_id != tenant_id:
            return None
        # Check owner/workspace + immutable content digest BEFORE touching R2.
        if not metadata.object_key.startswith(prefix + doc_id + "/"):
            return None
        projection = self._web_xlsx_projection(metadata, prefix)
        result = await self.get_for_tenant(
            tenant_id=tenant_id, document_id=doc_id, now=now,
        )
        if result is None:
            return None
        _, payload = result
        if hashlib.sha256(payload).hexdigest() != projection["source_sha256"]:
            raise WorkspaceStorageError("web XLSX source digest mismatch")
        return projection, payload

    async def find_approved_web_xlsx_workcopy(
        self, *, tenant_id: str, owner_id: str, workspace_id: str,
        run_id: str, source_document_id: str, expected_source_sha256: str,
    ) -> dict[str, Any] | None:
        """Read-only receipt lookup; only caller may decide the owner D1
        P01 confirmation is authentic. Never projects private object keys."""
        tenant = _safe_identifier("tenant_id", tenant_id)
        owner = _safe_identifier("owner_id", owner_id)
        workspace = _safe_identifier("workspace_id", workspace_id)
        run = _safe_identifier("run_id", run_id)
        doc = _safe_identifier("source_document_id", source_document_id)
        if not isinstance(expected_source_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_source_sha256
        ):
            raise WorkspaceStorageAccessError("original fingerprint invalid")
        prefix = (
            f"workspaces/{tenant}/claw/web-office-workcopies/"
            f"{owner}/{workspace}/{run}/{doc}/"
        )
        rows = await self.metadata_store.list_web_xlsx(
            tenant_id=tenant, key_prefix=prefix, now=_utcnow(), limit=2,
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise WorkspaceStorageError("ambiguous approved workcopy receipt")
        record = rows[0]
        if (
            record.tenant_id != tenant
            or record.object_key != (
                f"{prefix}{record.document_id}/{expected_source_sha256}"
            )
            or record.media_type != XLSX_MEDIA_TYPE
            or not re.fullmatch(r"doc_[0-9a-f]{32}", record.document_id)
            or record.byte_length <= 0
        ):
            raise WorkspaceStorageError("approved workcopy receipt mismatch")
        return {
            "workcopy_created": True,
            "workcopy_document_id": record.document_id,
            "source_document_id": doc,
            "source_sha256": expected_source_sha256,
        }

    async def create_approved_web_xlsx_workcopy(
        self, *, tenant_id: str, owner_id: str, workspace_id: str,
        source_document_id: str, expected_source_sha256: str,
        run_id: str, grant_verifier: Any,
    ) -> dict[str, Any]:
        """Private host-only operation after independent Core/P01 READ grant.

        There is deliberately NO public browser route for this method.
        The trusted host must supply an authority verifier from Engine/Core;
        a browser decision status, persisted receipt or boolean is NOT a grant.
        Verify the exact original a second time before copying bytes.
        """
        import inspect as _inspect
        tenant = _safe_identifier("tenant_id", tenant_id)
        owner = _safe_identifier("owner_id", owner_id)
        workspace = _safe_identifier("workspace_id", workspace_id)
        run = _safe_identifier("run_id", run_id)
        source_id = _safe_identifier("source_document_id", source_document_id)
        if (not isinstance(expected_source_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256)
                or not callable(grant_verifier)):
            raise WorkspaceStorageAccessError("verified P01 read grant required")
        original = await self.get_web_xlsx_metadata(
            tenant_id=tenant, owner_id=owner, workspace_id=workspace,
            document_id=source_id,
        )
        if (original is None or original["source_sha256"] != expected_source_sha256
                or original["original_immutable"] is not True):
            raise WorkspaceStorageAccessError("original owner or fingerprint mismatch")

        # The verifier is host-composed, never a browser-supplied callback.
        # No R2 bytes are read before this exact-operation authority check.
        allowed = grant_verifier(
            owner_id=owner, workspace_id=workspace, run_id=run,
            document_id=source_id, source_sha256=expected_source_sha256,
            operation="read_for_workcopy",
        )
        if _inspect.isawaitable(allowed):
            allowed = await allowed
        if allowed is not True:
            raise WorkspaceStorageAccessError("P01 original read not authorized")
        loaded = await self.get_web_xlsx(
            tenant_id=tenant, owner_id=owner, workspace_id=workspace,
            document_id=source_id,
        )
        if loaded is None:
            raise WorkspaceStorageAccessError("approved original expired")
        verified, payload = loaded
        if (verified["source_sha256"] != expected_source_sha256
                or verified["size_bytes"] != len(payload)):
            raise WorkspaceStorageError("approved original changed")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != expected_source_sha256:
            raise WorkspaceStorageError("approved original digest mismatch")

        copy_id = _document_id()
        key = (f"workspaces/{tenant}/claw/web-office-workcopies/"
               f"{owner}/{workspace}/{run}/{source_id}/{copy_id}/{digest}")
        now = _utcnow()
        source_expires = _parse_time(verified["expires_at"])
        if source_expires <= now:
            raise WorkspaceStorageAccessError("approved original expired")
        metadata = ClawDocumentMetadata(
            document_id=copy_id, tenant_id=tenant, object_key=key,
            filename=verified["filename"], media_type=XLSX_MEDIA_TYPE,
            byte_length=len(payload), created_at=now,
            expires_at=min(source_expires, now + WEB_XLSX_RETENTION),
        )
        try:
            written = self.r2_bucket.put(
                key, payload, httpMetadata={"contentType": XLSX_MEDIA_TYPE},
            )
            if _inspect.isawaitable(written):
                await written
            await self.metadata_store.insert(metadata)
        except Exception as exc:
            try:
                deleted = self.r2_bucket.delete(key)
                if _inspect.isawaitable(deleted):
                    await deleted
            except Exception:
                pass
            raise WorkspaceStorageError("approved workcopy write failed") from exc
        return {
            "source_document_id": source_id,
            "source_sha256": digest,
            "workcopy_document_id": copy_id,
            "workcopy_sha256": digest,
            "run_id": run,
            "size_bytes": len(payload),
            "original_immutable": True,
            "workcopy_created": True,
            "processing_authorized_for_this_copy": True,
        }

    async def create_authorized_web_quote_revision(
        self, *, tenant_id: str, owner_id: str, workspace_id: str,
        run_id: str, source_document_id: str, expected_source_sha256: str,
        workcopy_document_id: str, school_name: str, supply_amount: int,
        write_grant_verifier: Any,
    ) -> dict[str, Any]:
        """Host-only, P01 write-granted revision of exact private workcopy.

        No public endpoint or automatic use of the original-read grant.
        The host is responsible for separately verifying the Core write
        operation for this source, copy, run and immutable edit digest.
        """
        import json as _json
        from .claw_web_xlsx_quote_editor import (
            revise_single_sheet_quote, WebQuoteEditUnsupported,
        )

        tenant = _safe_identifier("tenant_id", tenant_id)
        owner = _safe_identifier("owner_id", owner_id)
        workspace = _safe_identifier("workspace_id", workspace_id)
        run = _safe_identifier("run_id", run_id)
        source_id = _safe_identifier("source_document_id", source_document_id)
        copy_id = _safe_identifier("workcopy_document_id", workcopy_document_id)
        if (not isinstance(expected_source_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256)
                or not callable(write_grant_verifier)
                or type(school_name) is not str
                or type(supply_amount) is not int):
            raise WorkspaceStorageAccessError("exact independent XLSX WRITE grant required")

        original = await self.get_web_xlsx_metadata(
            tenant_id=tenant, owner_id=owner, workspace_id=workspace,
            document_id=source_id,
        )
        record = await self.metadata_store.get_active(copy_id)
        prefix = (
            f"workspaces/{tenant}/claw/web-office-workcopies/"
            f"{owner}/{workspace}/{run}/{source_id}/{copy_id}/"
        )
        if (original is None or original["source_sha256"] != expected_source_sha256
                or original["original_immutable"] is not True
                or record is None or record.tenant_id != tenant
                or record.object_key != prefix + expected_source_sha256
                or record.media_type != XLSX_MEDIA_TYPE
                or record.filename != original["filename"]
                or record.byte_length != original["size_bytes"]
                or record.expires_at <= _utcnow()):
            raise WorkspaceStorageAccessError("approved workcopy scope changed")

        edit_contract = _json.dumps(
            {"school_name": school_name, "supply_amount": supply_amount,
             "output_formats": ["xlsx"], "overwrite_original": False},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        edit_sha = hashlib.sha256(edit_contract.encode("utf-8")).hexdigest()
        allowed = write_grant_verifier(
            owner_id=owner, workspace_id=workspace, run_id=run,
            source_document_id=source_id, source_sha256=expected_source_sha256,
            workcopy_document_id=copy_id, workcopy_sha256=expected_source_sha256,
            edit_sha256=edit_sha, operation="xlsx.quote.revise_workcopy",
        )
        if inspect.isawaitable(allowed):
            allowed = await allowed
        if allowed is not True:
            raise WorkspaceStorageAccessError("separate P01 edit/write approval missing")

        # Neither a browser confirmation nor read-only P01 intent is a write grant.
        # The R2 copy bytes are not touched until the exact write authority passed.
        try:
            obj = self.r2_bucket.get(record.object_key)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                raise WorkspaceStorageError("workcopy bytes unavailable")
            payload = await _read_r2_object_bytes(obj)
        except WorkspaceStorageError:
            raise
        except Exception as exc:
            raise WorkspaceStorageError("workcopy read unavailable") from exc
        if (len(payload) != record.byte_length
                or hashlib.sha256(payload).hexdigest() != expected_source_sha256):
            raise WorkspaceStorageError("workcopy bytes changed")
        try:
            revision = revise_single_sheet_quote(
                original=payload, original_sha256=expected_source_sha256,
                school_name=school_name, supply_amount=supply_amount,
            )
        except WebQuoteEditUnsupported as exc:
            raise WorkspaceStorageError(
                "quote template or requested export unsupported: " + str(exc)
            ) from exc

        # Only the supplied Engine-granted one-shot write authority can make
        # this safe under concurrency. No broader user-triggered public route.
        revision_id = _document_id()
        key = (
            f"workspaces/{tenant}/claw/web-office-revisions/"
            f"{owner}/{workspace}/{run}/{source_id}/{copy_id}/"
            f"{revision_id}/{revision.revised_sha256}"
        )
        now = _utcnow()
        metadata = ClawDocumentMetadata(
            document_id=revision_id, tenant_id=tenant,
            object_key=key, filename=record.filename,
            media_type=XLSX_MEDIA_TYPE,
            byte_length=len(revision.revised_xlsx), created_at=now,
            expires_at=min(record.expires_at, now + WEB_XLSX_RETENTION),
        )
        if metadata.expires_at <= now:
            raise WorkspaceStorageAccessError("approved workcopy expired")
        try:
            saved = self.r2_bucket.put(
                key, revision.revised_xlsx,
                httpMetadata={"contentType": XLSX_MEDIA_TYPE},
            )
            if inspect.isawaitable(saved):
                await saved
            await self.metadata_store.insert(metadata)
        except Exception as exc:
            try:
                removed = self.r2_bucket.delete(key)
                if inspect.isawaitable(removed):
                    await removed
            except Exception:
                pass
            raise WorkspaceStorageError("XLSX revision storage unavailable") from exc
        return {
            "source_document_id": source_id,
            "source_sha256": expected_source_sha256,
            "workcopy_document_id": copy_id,
            "revision_document_id": revision_id,
            "revision_sha256": revision.revised_sha256,
            "edit_sha256": edit_sha,
            "supply_amount": supply_amount,
            "vat_amount": revision.vat_amount,
            "total_amount": revision.total_amount,
            "original_overwritten": False,
            "revised_xlsx_created": True,
            "pdf_exported": False,
            "pdf_fidelity": revision.print_pdf_fidelity,
        }
