"""Canonical scoped image-byte store authority for Engine E5 (#2138).

This module is the durable scoped byte store contract that the #2137
deployment resolver consumes (#2182 S5), still ahead of any ``att_*``
multimodal activation (#1971/#1972). It mirrors the repository-native
precedents exactly:

- the D1-like adapter pattern of ``app/evidence_storage_d1.py`` and
  ``app/continuation_d1.py`` (constructor takes a trusted binding, async SQL
  via ``prepare(sql).bind(*params)``, fail-closed when the binding is missing);
- server-minted opaque references (``continuation_d1`` uses
  ``secrets.token_urlsafe``; the ``att_*`` grammar stays owned by
  ``app/attachment_authority.py`` and is never re-declared here);
- scope triples identical to ``app.document_context_service.TrustedCallerScope``
  (app/tenant/subject), validated on every read;
- TTL/expiry semantics of ``app/idempotency_binding.py`` (tz-aware ISO
  timestamps, expired records fail closed).

Authority rules enforced here:

- callers may only present a server-minted opaque ``att_*`` reference; no
  storage locator, key, path or URL ever appears in any public interface;
- bytes are admitted once with a bounded size reusing Core's
  ``MAX_B14_IMAGE_BYTES`` and the JPEG/PNG/WebP media allowlist; media magic
  remains deliberately validated by Core B14 downstream, not a second Engine
  image validator;
- every read re-checks scope, expiry, terminal invalidation and record
  integrity; any mismatch fails closed and error messages never echo payload
  bytes, references or storage state.

Wired in #2182 S5: ``worker_identity.py`` composes ``ScopedImageByteStore`` over
the repo-owned ``ENGINE_IMAGE_STORE`` D1 binding and hands it to the multimodal
services. That wiring declares no storage of its own: production schema
provisioning stays with the D1 provision gate, resolver construction stays
per-request behind the trusted scope authority, and manifest activation remains
a separate explicitly gated step.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import inspect
import re
import secrets
from typing import Any, Callable, Protocol

from padiem_ai_core.b14_multimodal import MAX_B14_IMAGE_BYTES

from app.attachment_authority import EngineAttachmentAuthorityError, require_opaque_attachment_ref

# Reuse Core's byte ceiling; the media allowlist mirrors Core's private
# _ALLOWED_IMAGE_MEDIA_TYPES and a test pins the two together against drift.
SUPPORTED_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_STORED_IMAGE_BYTES = MAX_B14_IMAGE_BYTES
# Mirrors the base64 bound expression Core applies in _normalize_image_data_url.
MAX_STORED_IMAGE_BASE64_CHARS = ((MAX_B14_IMAGE_BYTES + 2) // 3) * 4 + 4

# Same grammar as app/attachment_authority._SAFE_ID_RE; pinned by a drift test.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

_TABLE_NAME = "padiem_engine_attachment_images"
_REF_ENTROPY_BYTES = 24


class ImageByteStoreError(ValueError):
    """Fail-closed image byte store error safe for first-party products.

    Messages are static per code: they never echo attachment references,
    payload bytes, digests or storage state.
    """

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("image byte store error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _require_ref(value: object) -> str:
    """Normalize the shared attachment grammar authority into a store error."""

    try:
        return require_opaque_attachment_ref(value)
    except EngineAttachmentAuthorityError as exc:
        raise ImageByteStoreError(exc.code, exc.safe_message, status_code=exc.status_code) from None


def _require_scope_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ImageByteStoreError(
            "invalid_scope",
            f"Image attachment {label} scope is invalid.",
        )
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True, slots=True)
class StoredImageRecord:
    """Scope-bound metadata for one admitted image payload.

    The record never carries bytes or storage coordinates; payload bytes are
    exchanged only through the port alongside this record.
    """

    attachment_ref: str
    app_id: str
    tenant_id: str
    subject_id: str
    media_type: str
    byte_size: int
    created_at: datetime
    expires_at: datetime | None = None
    terminal: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_ref", require_opaque_attachment_ref(self.attachment_ref))
        _require_scope_id(self.app_id, "application")
        _require_scope_id(self.tenant_id, "tenant")
        _require_scope_id(self.subject_id, "subject")
        if not isinstance(self.media_type, str) or self.media_type.strip().lower() not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ImageByteStoreError(
                "unsupported_media_type",
                "Image attachment media type is not supported.",
                status_code=415,
            )
        object.__setattr__(self, "media_type", self.media_type.strip().lower())
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise ImageByteStoreError("integrity_mismatch", "Image attachment record is invalid.", status_code=503)
        if not 0 < self.byte_size <= MAX_STORED_IMAGE_BYTES:
            raise ImageByteStoreError(
                "attachment_too_large",
                "Image attachment exceeds the bounded multimodal size.",
                status_code=413,
            )
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ImageByteStoreError("invalid_expiry", "Image attachment record time is invalid.")
        if self.expires_at is not None:
            if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
                raise ImageByteStoreError("invalid_expiry", "Image attachment expiry is invalid.")
            if self.expires_at <= self.created_at:
                raise ImageByteStoreError("invalid_expiry", "Image attachment expiry is not in the future.")

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and self.expires_at <= now


class ImageByteStorePort(Protocol):
    """Durable byte retention keyed only by the server-minted opaque ref.

    Implementations never expose storage locators; ``fetch`` returns the
    metadata record with its payload bytes, or ``None`` for unknown refs.
    """

    async def put(self, record: StoredImageRecord, data: bytes) -> None: ...

    async def fetch(self, attachment_ref: str) -> tuple[StoredImageRecord, bytes] | None: ...

    async def mark_terminal(self, attachment_ref: str) -> bool: ...


class InMemoryImageByteStore:
    """Deterministic in-memory port for tests and local composition.

    No network, filesystem or environment access. Records are append-only:
    a duplicate ref is rejected and terminal flags are the only mutation.
    """

    def __init__(self) -> None:
        self._records: dict[str, StoredImageRecord] = {}
        self._payloads: dict[str, bytes] = {}

    def __repr__(self) -> str:
        return f"InMemoryImageByteStore(records={len(self._records)})"

    async def put(self, record: StoredImageRecord, data: bytes) -> None:
        if not isinstance(record, StoredImageRecord):
            raise ImageByteStoreError("integrity_mismatch", "Image attachment record is invalid.", status_code=503)
        if not isinstance(data, bytes) or not data:
            raise ImageByteStoreError("empty_payload", "Image attachment payload is empty.")
        if record.attachment_ref in self._records:
            raise ImageByteStoreError("ref_conflict", "Image attachment reference already exists.", status_code=503)
        self._records[record.attachment_ref] = record
        self._payloads[record.attachment_ref] = bytes(data)

    async def fetch(self, attachment_ref: str) -> tuple[StoredImageRecord, bytes] | None:
        record = self._records.get(attachment_ref)
        if record is None:
            return None
        return record, bytes(self._payloads[attachment_ref])

    async def mark_terminal(self, attachment_ref: str) -> bool:
        record = self._records.get(attachment_ref)
        if record is None:
            return False
        self._records[attachment_ref] = replace(record, terminal=True)
        return True


class CloudflareD1ImageByteStore:
    """Durable image byte retention backed by a trusted D1-like binding.

    Mirrors ``CloudflareD1EvidenceStoragePort``: the binding is deployment-
    owned, the schema is provisioned by the deployment owner (never by app
    code), and payloads are stored base64-encoded in a bounded column. Since
    #2182 S5 this adapter is composed only in ``worker_identity.py`` behind the
    repo-owned ``ENGINE_IMAGE_STORE`` binding; app code never creates or mutates
    schema.
    """

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ImageByteStoreError(
                "store_unavailable",
                "Image byte store binding must provide prepare(sql).",
                status_code=503,
            )
        self._binding = binding

    def __repr__(self) -> str:
        return "CloudflareD1ImageByteStore(configured)"

    async def _first(self, sql: str, *params: Any) -> Mapping[str, Any] | None:
        row = await _maybe_await(self._binding.prepare(sql).bind(*params).first())
        return dict(row) if isinstance(row, Mapping) else None

    async def _run(self, sql: str, *params: Any) -> Any:
        return await _maybe_await(self._binding.prepare(sql).bind(*params).run())

    @staticmethod
    def _record(row: Mapping[str, Any]) -> StoredImageRecord:
        try:
            return StoredImageRecord(
                attachment_ref=str(row["attachment_ref"]),
                app_id=str(row["app_id"]),
                tenant_id=str(row["tenant_id"]),
                subject_id=str(row["subject_id"]),
                media_type=str(row["media_type"]),
                byte_size=int(row["byte_size"]),
                created_at=_parse_time(row["created_at"]),
                expires_at=_parse_time(row["expires_at"]) if row["expires_at"] is not None else None,
                terminal=bool(row["terminal"]),
            )
        except (KeyError, TypeError, ValueError, ImageByteStoreError):
            raise ImageByteStoreError(
                "integrity_mismatch",
                "Image byte store returned an invalid record.",
                status_code=503,
            ) from None

    async def put(self, record: StoredImageRecord, data: bytes) -> None:
        if not isinstance(record, StoredImageRecord):
            raise ImageByteStoreError("integrity_mismatch", "Image attachment record is invalid.", status_code=503)
        if not isinstance(data, bytes) or not data:
            raise ImageByteStoreError("empty_payload", "Image attachment payload is empty.")
        if len(data) != record.byte_size:
            raise ImageByteStoreError("integrity_mismatch", "Image attachment record is invalid.", status_code=503)
        payload_base64 = base64.b64encode(data).decode("ascii")
        if len(payload_base64) > MAX_STORED_IMAGE_BASE64_CHARS:
            raise ImageByteStoreError(
                "attachment_too_large",
                "Image attachment exceeds the bounded multimodal size.",
                status_code=413,
            )
        existing = await self._first(
            f"SELECT attachment_ref FROM {_TABLE_NAME} WHERE attachment_ref=? LIMIT 1",
            record.attachment_ref,
        )
        if existing is not None:
            raise ImageByteStoreError("ref_conflict", "Image attachment reference already exists.", status_code=503)
        await self._run(
            f"INSERT INTO {_TABLE_NAME} "
            "(attachment_ref,app_id,tenant_id,subject_id,media_type,byte_size,created_at,expires_at,"
            "terminal,payload_base64) VALUES (?,?,?,?,?,?,?,?,?,?)",
            record.attachment_ref,
            record.app_id,
            record.tenant_id,
            record.subject_id,
            record.media_type,
            record.byte_size,
            record.created_at.isoformat(),
            record.expires_at.isoformat() if record.expires_at is not None else None,
            1 if record.terminal else 0,
            payload_base64,
        )

    async def fetch(self, attachment_ref: str) -> tuple[StoredImageRecord, bytes] | None:
        row = await self._first(
            f"SELECT attachment_ref,app_id,tenant_id,subject_id,media_type,byte_size,created_at,expires_at,"
            f"terminal,payload_base64 FROM {_TABLE_NAME} WHERE attachment_ref=? LIMIT 1",
            attachment_ref,
        )
        if row is None:
            return None
        record = self._record(row)
        try:
            data = base64.b64decode(str(row["payload_base64"]), validate=True)
        except (binascii.Error, ValueError):
            raise ImageByteStoreError(
                "integrity_mismatch",
                "Image byte store returned an invalid record.",
                status_code=503,
            ) from None
        if len(data) != record.byte_size:
            raise ImageByteStoreError(
                "integrity_mismatch",
                "Image byte store returned an invalid record.",
                status_code=503,
            )
        return record, data

    async def mark_terminal(self, attachment_ref: str) -> bool:
        existing = await self._first(
            f"SELECT attachment_ref FROM {_TABLE_NAME} WHERE attachment_ref=? LIMIT 1",
            attachment_ref,
        )
        if existing is None:
            return False
        await self._run(
            f"UPDATE {_TABLE_NAME} SET terminal=1 WHERE attachment_ref=?",
            attachment_ref,
        )
        return True


class ScopedImageByteStore:
    """Authority facade: server-side ref minting and scope-checked retrieval.

    Callers can never choose or influence the attachment reference, and every
    read re-validates grammar, scope, expiry, terminal state and integrity
    fail-closed. The facade holds no storage knowledge beyond the port.
    """

    def __init__(self, *, port: ImageByteStorePort, clock: Callable[[], datetime] | None = None) -> None:
        if port is None:
            raise ImageByteStoreError("store_unavailable", "Image byte store port is unavailable.", status_code=503)
        self._port = port
        self._clock = clock if clock is not None else _utcnow

    def __repr__(self) -> str:
        return "ScopedImageByteStore(configured)"

    async def admit_image(
        self,
        *,
        data: bytes,
        media_type: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
        expires_at: datetime | None = None,
    ) -> StoredImageRecord:
        """Store bounded bytes once and return the minted opaque reference record."""

        _require_scope_id(app_id, "application")
        _require_scope_id(tenant_id, "tenant")
        _require_scope_id(subject_id, "subject")
        if not isinstance(media_type, str) or media_type.strip().lower() not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ImageByteStoreError(
                "unsupported_media_type",
                "Image attachment media type is not supported.",
                status_code=415,
            )
        if not isinstance(data, bytes) or not data:
            raise ImageByteStoreError("empty_payload", "Image attachment payload is empty.")
        if len(data) > MAX_STORED_IMAGE_BYTES:
            raise ImageByteStoreError(
                "attachment_too_large",
                "Image attachment exceeds the bounded multimodal size.",
                status_code=413,
            )
        if expires_at is not None:
            if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
                raise ImageByteStoreError("invalid_expiry", "Image attachment expiry must be timezone-aware.")
            if expires_at <= self._clock():
                raise ImageByteStoreError("invalid_expiry", "Image attachment expiry is not in the future.")
        attachment_ref = _require_ref("att_" + secrets.token_urlsafe(_REF_ENTROPY_BYTES))
        record = StoredImageRecord(
            attachment_ref=attachment_ref,
            app_id=app_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
            media_type=media_type.strip().lower(),
            byte_size=len(data),
            created_at=self._clock(),
            expires_at=expires_at,
        )
        await self._port.put(record, data)
        return record

    async def fetch_image(
        self,
        *,
        attachment_ref: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
    ) -> tuple[StoredImageRecord, bytes]:
        """Return scope-matched live bytes; every failure mode fails closed."""

        _require_ref(attachment_ref)
        _require_scope_id(app_id, "application")
        _require_scope_id(tenant_id, "tenant")
        _require_scope_id(subject_id, "subject")
        fetched = await self._port.fetch(attachment_ref)
        if fetched is None:
            raise ImageByteStoreError("not_found", "Image attachment is not available.", status_code=404)
        record, data = fetched
        if not isinstance(record, StoredImageRecord) or record.attachment_ref != attachment_ref:
            raise ImageByteStoreError(
                "integrity_mismatch",
                "Image byte store returned an invalid record.",
                status_code=503,
            )
        if record.app_id != app_id or record.tenant_id != tenant_id or record.subject_id != subject_id:
            raise ImageByteStoreError(
                "unauthorized",
                "Image attachment scope does not match the caller.",
                status_code=403,
            )
        if (
            record.media_type not in SUPPORTED_IMAGE_MEDIA_TYPES
            or not isinstance(data, bytes)
            or not data
            or len(data) != record.byte_size
            or record.byte_size > MAX_STORED_IMAGE_BYTES
        ):
            raise ImageByteStoreError(
                "integrity_mismatch",
                "Image byte store returned an invalid record.",
                status_code=503,
            )
        if record.terminal:
            raise ImageByteStoreError("attachment_terminal", "Image attachment is no longer active.", status_code=410)
        if record.is_expired(self._clock()):
            raise ImageByteStoreError("attachment_expired", "Image attachment has expired.", status_code=410)
        return record, data

    async def invalidate(
        self,
        *,
        attachment_ref: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
    ) -> bool:
        """Mark one scope-matched record terminal; reads after this fail closed."""

        _require_ref(attachment_ref)
        _require_scope_id(app_id, "application")
        _require_scope_id(tenant_id, "tenant")
        _require_scope_id(subject_id, "subject")
        fetched = await self._port.fetch(attachment_ref)
        if fetched is None:
            raise ImageByteStoreError("not_found", "Image attachment is not available.", status_code=404)
        record, _ = fetched
        if (
            not isinstance(record, StoredImageRecord)
            or record.app_id != app_id
            or record.tenant_id != tenant_id
            or record.subject_id != subject_id
        ):
            raise ImageByteStoreError(
                "unauthorized",
                "Image attachment scope does not match the caller.",
                status_code=403,
            )
        return await self._port.mark_terminal(attachment_ref)
