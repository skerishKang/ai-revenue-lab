"""Private account-bound B66 quotation assets (#3402).

Logo/stamp bytes live only in the existing private R2 binding. D1 stores bounded
metadata needed to authorize and verify reads. Browser callers never choose R2
object keys, owner ids, or workspace ids.

There is deliberately no public upload route in this slice. Operator-assisted
alpha provisioning may call put_approved_asset only from a trusted server
surface added/reviewed separately.
"""

from __future__ import annotations

import hashlib
import inspect
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_B66_QUOTE_ASSET_BYTES = 256 * 1024
ASSET_KINDS = frozenset({"logo", "stamp"})
ASSET_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

_ASSET_ID_RE = re.compile(r"^b66asset_[0-9a-f]{32}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class B66QuoteAssetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class B66QuoteAssetMetadata:
    asset_id: str
    user_id: str
    workspace_id: str
    asset_kind: str
    media_type: str
    object_key: str
    byte_length: int
    sha256: str
    status: str
    created_at: str
    updated_at: str

    def public_projection(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "asset_kind": self.asset_kind,
            "media_type": self.media_type,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _owner(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise B66QuoteAssetError(f"{label} is required")
    text = value.strip()
    if not text or len(text) > limit or _CONTROL_RE.search(text):
        raise B66QuoteAssetError(f"{label} is invalid")
    return text


def validate_asset_id(value: object) -> str:
    if not isinstance(value, str) or not _ASSET_ID_RE.fullmatch(value.strip()):
        raise B66QuoteAssetError("asset_id is invalid")
    return value.strip()


def _asset_kind(value: object) -> str:
    if not isinstance(value, str) or value not in ASSET_KINDS:
        raise B66QuoteAssetError("asset_kind is invalid")
    return value


def _media_type(value: object) -> str:
    if not isinstance(value, str) or value not in ASSET_MEDIA_TYPES:
        raise B66QuoteAssetError("media_type is invalid")
    return value


def _extension(media_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }[media_type]


def _object_key(asset_id: str, media_type: str) -> str:
    return f"b66/quote-assets/{asset_id}{_extension(media_type)}"


def _magic_matches(media_type: str, body: bytes) -> bool:
    if media_type == "image/png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return body.startswith(b"\xff\xd8\xff")
    if media_type == "image/webp":
        return len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP"
    return False


def _payload(value: object, *, media_type: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise B66QuoteAssetError("asset body must be bytes")
    body = bytes(value)
    if not body or len(body) > MAX_B66_QUOTE_ASSET_BYTES:
        raise B66QuoteAssetError("asset body size is invalid")
    if not _magic_matches(media_type, body):
        raise B66QuoteAssetError("asset media type does not match bytes")
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


def _metadata(row: dict[str, Any]) -> B66QuoteAssetMetadata:
    try:
        meta = B66QuoteAssetMetadata(
            asset_id=validate_asset_id(row["id"]),
            user_id=_owner(row["user_id"], label="user_id", limit=80),
            workspace_id=_owner(row["workspace_id"], label="workspace_id", limit=160),
            asset_kind=_asset_kind(row["asset_kind"]),
            media_type=_media_type(row["media_type"]),
            object_key=str(row["object_key"]),
            byte_length=int(row["byte_length"]),
            sha256=str(row["sha256"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise B66QuoteAssetError("asset metadata is invalid") from exc
    if (
        meta.object_key != _object_key(meta.asset_id, meta.media_type)
        or meta.byte_length < 1
        or meta.byte_length > MAX_B66_QUOTE_ASSET_BYTES
        or not _SHA256_RE.fullmatch(meta.sha256)
        or meta.status != "approved"
    ):
        raise B66QuoteAssetError("asset metadata is invalid")
    return meta


class D1B66QuoteAssetMetadataStore:
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

    async def insert(self, metadata: B66QuoteAssetMetadata) -> None:
        await self._run(
            "INSERT INTO b66_quote_asset "
            "(id, user_id, workspace_id, asset_kind, media_type, object_key, byte_length, "
            "sha256, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)",
            metadata.asset_id,
            metadata.user_id,
            metadata.workspace_id,
            metadata.asset_kind,
            metadata.media_type,
            metadata.object_key,
            metadata.byte_length,
            metadata.sha256,
            metadata.created_at,
            metadata.updated_at,
        )

    async def get_active(
        self, *, asset_id: str, user_id: str, workspace_id: str
    ) -> B66QuoteAssetMetadata | None:
        row = await self._first(
            "SELECT id, user_id, workspace_id, asset_kind, media_type, object_key, "
            "byte_length, sha256, status, created_at, updated_at "
            "FROM b66_quote_asset "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='approved'",
            asset_id,
            user_id,
            workspace_id,
        )
        return _metadata(row) if row else None


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


class B66QuoteAssetStore:
    def __init__(self, metadata_store: D1B66QuoteAssetMetadataStore, r2_bucket: Any) -> None:
        if metadata_store is None:
            raise ValueError("asset metadata store is required")
        if r2_bucket is None:
            raise ValueError("private R2 binding is required")
        self.metadata_store = metadata_store
        self.r2_bucket = r2_bucket

    async def put_approved_asset(
        self,
        *,
        user_id: str,
        workspace_id: str,
        asset_kind: str,
        media_type: str,
        body: bytes,
    ) -> B66QuoteAssetMetadata:
        owner = _owner(user_id, label="user_id", limit=80)
        workspace = _owner(workspace_id, label="workspace_id", limit=160)
        kind = _asset_kind(asset_kind)
        media = _media_type(media_type)
        payload = _payload(body, media_type=media)
        asset_id = "b66asset_" + uuid.uuid4().hex
        object_key = _object_key(asset_id, media)
        now = _now_iso()
        metadata = B66QuoteAssetMetadata(
            asset_id=asset_id,
            user_id=owner,
            workspace_id=workspace,
            asset_kind=kind,
            media_type=media,
            object_key=object_key,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            status="approved",
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
            raise B66QuoteAssetError("asset storage failed") from exc
        return metadata

    async def get_for_owner(
        self,
        *,
        user_id: str,
        workspace_id: str,
        asset_id: str,
    ) -> tuple[B66QuoteAssetMetadata, bytes] | None:
        owner = _owner(user_id, label="user_id", limit=80)
        workspace = _owner(workspace_id, label="workspace_id", limit=160)
        safe_id = validate_asset_id(asset_id)
        metadata = await self.metadata_store.get_active(
            asset_id=safe_id,
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
            raise B66QuoteAssetError("asset read failed") from exc
        if (
            len(payload) != metadata.byte_length
            or hashlib.sha256(payload).hexdigest() != metadata.sha256
            or not _magic_matches(metadata.media_type, payload)
        ):
            raise B66QuoteAssetError("asset integrity check failed")
        return metadata, payload


__all__ = [
    "ASSET_KINDS",
    "ASSET_MEDIA_TYPES",
    "B66QuoteAssetError",
    "B66QuoteAssetMetadata",
    "B66QuoteAssetStore",
    "D1B66QuoteAssetMetadataStore",
    "MAX_B66_QUOTE_ASSET_BYTES",
    "validate_asset_id",
]