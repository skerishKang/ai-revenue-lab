"""Private account-bound B66 customer template source custody (#3884 Slice 1).

The customer's original uploaded quotation form (XLSX/PDF/DOCX/CSV) lives only
in the existing private R2 binding as immutable bytes. D1 stores bounded
metadata needed to authorize and verify reads. Browser callers never choose R2
object keys, owner ids, or workspace ids, and a caller-supplied owner field is
a contract violation rather than authority.

Upload alone never certifies a template: the stored status is exactly
``uploaded``. Analysis/approval and repeat-use rendering are separate slices.
There is deliberately no compile/approve route in this slice.

Sensitive-field application-level encryption (#3884 threat model) is NOT part
of this slice; transport TLS + R2 at-rest provider encryption apply, and the
custody policy (docs/products/b66/TEMPLATE_CUSTODY_POLICY.md) governs.
"""

from __future__ import annotations

import hashlib
import inspect
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_B66_TEMPLATE_SOURCE_BYTES = 10 * 1024 * 1024
MAX_TEMPLATE_SOURCE_LIST = 50
MAX_ORIGINAL_FILENAME_CHARS = 200

TEMPLATE_SOURCE_MEDIA_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/csv": ".csv",
}
_ALLOWED_MEDIA_TYPES = frozenset(TEMPLATE_SOURCE_MEDIA_TYPES)

_TEMPLATE_SOURCE_ID_RE = re.compile(r"^b66tplsrc_[0-9a-f]{32}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FILENAME_INVALID_CHARS_RE = re.compile(r"[\\/:*?\"<>|]")

_OBJECT_KEY_PREFIX = "b66/template-source/"


class B66TemplateSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class B66TemplateSourceMetadata:
    template_source_id: str
    user_id: str
    workspace_id: str
    media_type: str
    original_filename: str
    object_key: str
    byte_length: int
    sha256: str
    status: str
    created_at: str
    updated_at: str

    def public_projection(self) -> dict[str, object]:
        # Object keys are server authority and owner ids are account authority;
        # neither is ever projected to the browser.
        return {
            "template_source_id": self.template_source_id,
            "media_type": self.media_type,
            "original_filename": self.original_filename,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "status": self.status,
            "created_at": self.created_at,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _owner(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise B66TemplateSourceError(f"{label} is required")
    text = value.strip()
    if not text or len(text) > limit or _CONTROL_RE.search(text):
        raise B66TemplateSourceError(f"{label} is invalid")
    return text


def validate_template_source_id(value: object) -> str:
    if not isinstance(value, str) or not _TEMPLATE_SOURCE_ID_RE.fullmatch(value.strip()):
        raise B66TemplateSourceError("template source id is invalid")
    return value.strip()


def _media_type(value: object) -> str:
    if not isinstance(value, str) or value not in _ALLOWED_MEDIA_TYPES:
        raise B66TemplateSourceError("media_type is invalid")
    return value


def sanitize_original_filename(value: object) -> str:
    """Return a bounded, path-free display name. Server-derived, never authority."""
    if value is None:
        return "original"
    if not isinstance(value, str):
        raise B66TemplateSourceError("original_filename is invalid")
    text = value.strip()
    if not text:
        return "original"
    # Strip any path components the client may have sent (Windows and POSIX).
    text = text.replace("\\", "/").split("/")[-1].strip()
    text = _FILENAME_INVALID_CHARS_RE.sub("", text)
    text = _CONTROL_RE.sub("", text).strip()
    if not text:
        return "original"
    if len(text) > MAX_ORIGINAL_FILENAME_CHARS:
        raise B66TemplateSourceError("original_filename is invalid")
    return text


def _object_key(template_source_id: str, media_type: str) -> str:
    extension = TEMPLATE_SOURCE_MEDIA_TYPES[media_type]
    return f"{_OBJECT_KEY_PREFIX}{template_source_id}{extension}"


def _magic_matches(media_type: str, body: bytes) -> bool:
    if media_type == "application/pdf":
        return body.startswith(b"%PDF-")
    if media_type in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return body.startswith(b"PK\x03\x04")
    if media_type == "text/csv":
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return False
        # Reject binary-looking payloads masquerading as CSV: a run of control
        # characters (allowing \r \n and tab) is not a text form.
        allowed_control = {"\r", "\n", "\t"}
        suspicious = sum(
            1 for ch in text[:4096] if ord(ch) < 32 and ch not in allowed_control
        )
        return suspicious <= 2
    return False


def _payload(value: object, *, media_type: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise B66TemplateSourceError("template source body must be bytes")
    body = bytes(value)
    if not body or len(body) > MAX_B66_TEMPLATE_SOURCE_BYTES:
        raise B66TemplateSourceError("template source body size is invalid")
    if not _magic_matches(media_type, body):
        raise B66TemplateSourceError("template source media type does not match bytes")
    return body


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


def _metadata(row: dict[str, Any]) -> B66TemplateSourceMetadata:
    try:
        meta = B66TemplateSourceMetadata(
            template_source_id=validate_template_source_id(row["id"]),
            user_id=_owner(row["user_id"], label="user_id", limit=80),
            workspace_id=_owner(row["workspace_id"], label="workspace_id", limit=160),
            media_type=_media_type(row["media_type"]),
            original_filename=str(row["original_filename"]),
            object_key=str(row["object_key"]),
            byte_length=int(row["byte_length"]),
            sha256=str(row["sha256"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise B66TemplateSourceError("template source metadata is invalid") from exc
    if (
        meta.object_key != _object_key(meta.template_source_id, meta.media_type)
        or not meta.original_filename
        or len(meta.original_filename) > MAX_ORIGINAL_FILENAME_CHARS
        or meta.byte_length < 1
        or meta.byte_length > MAX_B66_TEMPLATE_SOURCE_BYTES
        or not _SHA256_RE.fullmatch(meta.sha256)
        or meta.status != "uploaded"
    ):
        raise B66TemplateSourceError("template source metadata is invalid")
    return meta


class D1B66TemplateSourceMetadataStore:
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

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        stmt = self.db.prepare(sql)
        if values:
            stmt = stmt.bind(*values)
        result = await stmt.all()
        rows = getattr(result, "results", None)
        if rows is None and isinstance(result, dict):
            rows = result.get("results")
        if not rows:
            return []
        output: list[dict[str, Any]] = []
        for row in rows:
            item = _row_to_dict(row)
            if item is not None:
                output.append(item)
        return output

    async def insert(self, metadata: B66TemplateSourceMetadata) -> None:
        await self._run(
            "INSERT INTO b66_template_source "
            "(id, user_id, workspace_id, media_type, original_filename, object_key, "
            "byte_length, sha256, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)",
            metadata.template_source_id,
            metadata.user_id,
            metadata.workspace_id,
            metadata.media_type,
            metadata.original_filename,
            metadata.object_key,
            metadata.byte_length,
            metadata.sha256,
            metadata.created_at,
            metadata.updated_at,
        )

    async def get_active(
        self, *, template_source_id: str, user_id: str, workspace_id: str
    ) -> B66TemplateSourceMetadata | None:
        row = await self._first(
            "SELECT id, user_id, workspace_id, media_type, original_filename, object_key, "
            "byte_length, sha256, status, created_at, updated_at "
            "FROM b66_template_source "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='uploaded'",
            template_source_id,
            user_id,
            workspace_id,
        )
        return _metadata(row) if row else None

    async def list_for_owner(
        self, *, user_id: str, workspace_id: str, limit: int = MAX_TEMPLATE_SOURCE_LIST
    ) -> list[B66TemplateSourceMetadata]:
        bounded = max(1, min(int(limit), MAX_TEMPLATE_SOURCE_LIST))
        rows = await self._all(
            "SELECT id, user_id, workspace_id, media_type, original_filename, object_key, "
            "byte_length, sha256, status, created_at, updated_at "
            "FROM b66_template_source "
            "WHERE user_id=? AND workspace_id=? AND status='uploaded' "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            user_id,
            workspace_id,
            bounded,
        )
        return [_metadata(row) for row in rows]


async def _read_r2_bytes(obj: Any) -> bytes:
    array_buffer = getattr(obj, "arrayBuffer", None)
    if callable(array_buffer):
        value = array_buffer()
        if inspect.isawaitable(value):
            value = await value
        to_bytes = getattr(value, "to_bytes", None)
        if callable(to_bytes):
            value = to_bytes()
        return bytes(value)
    return bytes(getattr(obj, "body", obj))


class B66TemplateSourceStore:
    def __init__(self, metadata_store: D1B66TemplateSourceMetadataStore, r2_bucket: Any) -> None:
        if metadata_store is None:
            raise ValueError("template source metadata store is required")
        if r2_bucket is None:
            raise ValueError("private R2 binding is required")
        self.metadata_store = metadata_store
        self.r2_bucket = r2_bucket

    async def put_template_source(
        self,
        *,
        user_id: str,
        workspace_id: str,
        media_type: str,
        original_filename: object = None,
        body: bytes,
    ) -> B66TemplateSourceMetadata:
        owner = _owner(user_id, label="user_id", limit=80)
        workspace = _owner(workspace_id, label="workspace_id", limit=160)
        media = _media_type(media_type)
        filename = sanitize_original_filename(original_filename)
        payload = _payload(body, media_type=media)
        template_source_id = "b66tplsrc_" + uuid.uuid4().hex
        object_key = _object_key(template_source_id, media)
        now = _now_iso()
        metadata = B66TemplateSourceMetadata(
            template_source_id=template_source_id,
            user_id=owner,
            workspace_id=workspace,
            media_type=media,
            original_filename=filename,
            object_key=object_key,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            # Upload alone never certifies the template (#3884 guardrail).
            status="uploaded",
            created_at=now,
            updated_at=now,
        )
        try:
            result = self.r2_bucket.put(
                object_key,
                payload,
                httpMetadata={"contentType": media},
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
            raise B66TemplateSourceError("template source storage failed") from exc
        return metadata

    async def get_for_owner(
        self,
        *,
        user_id: str,
        workspace_id: str,
        template_source_id: str,
    ) -> tuple[B66TemplateSourceMetadata, bytes] | None:
        owner = _owner(user_id, label="user_id", limit=80)
        workspace = _owner(workspace_id, label="workspace_id", limit=160)
        safe_id = validate_template_source_id(template_source_id)
        metadata = await self.metadata_store.get_active(
            template_source_id=safe_id,
            user_id=owner,
            workspace_id=workspace,
        )
        if metadata is None:
            return None
        try:
            obj = self.r2_bucket.get(metadata.object_key)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                return None
            payload = await _read_r2_bytes(obj)
        except Exception as exc:
            raise B66TemplateSourceError("template source read failed") from exc
        if (
            len(payload) != metadata.byte_length
            or hashlib.sha256(payload).hexdigest() != metadata.sha256
            or not _magic_matches(metadata.media_type, payload)
        ):
            raise B66TemplateSourceError("template source integrity check failed")
        return metadata, payload


__all__ = [
    "B66TemplateSourceError",
    "B66TemplateSourceMetadata",
    "B66TemplateSourceStore",
    "D1B66TemplateSourceMetadataStore",
    "MAX_B66_TEMPLATE_SOURCE_BYTES",
    "MAX_TEMPLATE_SOURCE_LIST",
    "TEMPLATE_SOURCE_MEDIA_TYPES",
    "sanitize_original_filename",
    "validate_template_source_id",
]
