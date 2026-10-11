"""Canonical scoped document-byte store authority for Engine E8C-B (#2741).

This is the document counterpart of the #2138 scoped image byte store and
follows its repository-native precedents exactly:

- the D1-like adapter pattern of ``app/attachment_byte_store.py`` and
  ``app/evidence_storage_d1.py`` (constructor takes a trusted binding, async
  SQL via ``prepare(sql).bind(*params)``, fail-closed when the binding is
  missing);
- server-minted opaque ``doc_*`` references (grammar owned by
  ``app/document_reference.py``; ``secrets.token_urlsafe`` entropy only — a
  token leading ``-``/``_`` is grammar-legal for this namespace because the
  full value always starts with ``doc_``);
- scope triples identical to ``app.document_context_service.TrustedCallerScope``
  (app/tenant/subject), re-validated on every read;
- TTL/expiry/terminal semantics of the image store with one document
  hardening: document retention is never indefinite — every record carries a
  server-minted bounded expiry (default 24h, ceiling 7 days) that callers on
  the wire cannot choose or influence.

Authority rules:

- callers may only present a server-minted ``doc_*`` reference; no storage
  locator, key, path or URL ever appears in any public interface;
- bytes are admitted once with per-media-class ceilings reused from Core's
  document normalization budgets (text vs binary OOXML/PDF classes); media
  allowlist membership is checked here, content semantics and magic stay with
  Core normalization;
- every read re-checks grammar, scope, expiry, terminal invalidation and
  record integrity; any failure is fail-closed and messages never echo
  payload bytes, references, storage state or scope values.

Source-only in this slice: nothing in the composition root or worker code
imports this module; ``ENGINE_DOCUMENT_STORE`` is a logical binding alias
declared in ``wrangler.toml`` and the migration is source provisioning text
applied only by the separate D1 provision gate.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import inspect
import re
import secrets
from typing import Any, Callable, Protocol

from padiem_ai_core.document_normalization import (
    BINARY_DOCUMENT_MEDIA,
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_DOCUMENT_NAME_CHARS,
    MAX_TEXT_DOCUMENT_BYTES,
    TEXT_DOCUMENT_MEDIA,
)

from app.document_reference import DOC_REFERENCE_PATTERN

# One media truth source: the Core normalization allowlists. A drift test pins
# these derived values against Core so the store never widens the accepted
# document vocabulary.
SUPPORTED_DOCUMENT_MEDIA_TYPES = frozenset(TEXT_DOCUMENT_MEDIA) | frozenset(
    BINARY_DOCUMENT_MEDIA
)
_DOCUMENT_SIZE_BY_MEDIA: dict[str, int] = {
    **{media: MAX_TEXT_DOCUMENT_BYTES for media in TEXT_DOCUMENT_MEDIA},
    **{media: MAX_BINARY_DOCUMENT_BYTES for media in BINARY_DOCUMENT_MEDIA},
}
MAX_STORED_DOCUMENT_BYTES = MAX_BINARY_DOCUMENT_BYTES
# Server-minted retention window: admitted records always expire.
DEFAULT_DOCUMENT_RETENTION_SECONDS = 24 * 60 * 60
MAX_DOCUMENT_RETENTION_SECONDS = 7 * 24 * 60 * 60
_REF_ENTROPY_BYTES = 24
_REF_PREFIX = "doc_"
_REF_MINT_ATTEMPTS = 3

# Mirrors the base64 shape Core-style stores apply: encode(len) + padding
# headroom, derived from the byte ceiling, never a client value.
MAX_STORED_DOCUMENT_BASE64_CHARS = ((MAX_STORED_DOCUMENT_BYTES + 2) // 3) * 4 + 4

_TABLE_NAME = "padiem_engine_document_bytes"

# Same safe-id shape as the shared scope grammar; pinned by a drift test
# against app.attachment_authority._SAFE_ID_RE (scope ids, not byte stores).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

_STORE_ERROR_CODES = frozenset(
    {
        "invalid_document_reference",
        "invalid_scope",
        "unauthorized",
        "not_found",
        "integrity_mismatch",
        "unsupported_media_type",
        "document_too_large",
        "empty_payload",
        "invalid_expiry",
        "ref_conflict",
        "store_unavailable",
        "expired",
        "terminal",
    }
)


class DocumentByteStoreError(ValueError):
    """Fail-closed document byte store error safe for first-party products.

    Messages are static per code: they never echo document references,
    payload bytes, digests or storage state.
    """

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or code not in _STORE_ERROR_CODES:
            raise ValueError("document byte store error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _require_ref(value: object) -> str:
    if not isinstance(value, str) or not DOC_REFERENCE_PATTERN.fullmatch(value):
        raise DocumentByteStoreError(
            "invalid_document_reference",
            "Document reference is invalid.",
        )
    return value


def _require_scope_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise DocumentByteStoreError(
            "invalid_scope",
            f"Document {label} scope is invalid.",
        )
    return value


def _require_name(value: object) -> str:
    """Server-side name shape guard; normalization owns document semantics."""

    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > MAX_DOCUMENT_NAME_CHARS
        or _CONTROL_CHARS_RE.search(value)
    ):
        raise DocumentByteStoreError(
            "integrity_mismatch",
            "Document record is invalid.",
            status_code=503,
        )
    return value.strip()


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


def _size_ceiling_for(media_type: str) -> int:
    return _DOCUMENT_SIZE_BY_MEDIA[media_type]


@dataclass(frozen=True, slots=True)
class StoredDocumentRecord:
    """Scope-bound metadata for one admitted document payload.

    The record never carries bytes or storage coordinates; payload bytes are
    exchanged only through the port alongside this record. ``expires_at`` is
    mandatory: document byte retention is always bounded and server-minted.
    """

    document_ref: str
    app_id: str
    tenant_id: str
    subject_id: str
    media_type: str
    name: str
    byte_size: int
    created_at: datetime
    expires_at: datetime
    terminal: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_ref", _require_ref(self.document_ref))
        _require_scope_id(self.app_id, "application")
        _require_scope_id(self.tenant_id, "tenant")
        _require_scope_id(self.subject_id, "subject")
        if (
            not isinstance(self.media_type, str)
            or self.media_type.strip().lower() not in SUPPORTED_DOCUMENT_MEDIA_TYPES
        ):
            raise DocumentByteStoreError(
                "unsupported_media_type",
                "Document media type is not supported.",
                status_code=415,
            )
        object.__setattr__(self, "media_type", self.media_type.strip().lower())
        object.__setattr__(self, "name", _require_name(self.name))
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise DocumentByteStoreError(
                "integrity_mismatch", "Document record is invalid.", status_code=503
            )
        if not 0 < self.byte_size <= _size_ceiling_for(self.media_type):
            raise DocumentByteStoreError(
                "document_too_large",
                "Document exceeds the bounded per-media size limit.",
                status_code=413,
            )
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise DocumentByteStoreError(
                "invalid_expiry", "Document record time is invalid."
            )
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise DocumentByteStoreError("invalid_expiry", "Document expiry is invalid.")
        if self.expires_at <= self.created_at:
            raise DocumentByteStoreError(
                "invalid_expiry", "Document expiry is not in the future."
            )
        if (
            self.expires_at - self.created_at
            > timedelta(seconds=MAX_DOCUMENT_RETENTION_SECONDS)
        ):
            raise DocumentByteStoreError(
                "invalid_expiry", "Document expiry exceeds the retention ceiling."
            )

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now


class DocumentByteStorePort(Protocol):
    """Durable byte retention keyed only by the server-minted opaque ref.

    Implementations never expose storage locators; ``fetch`` returns the
    metadata record with its payload bytes, or ``None`` for unknown refs.
    """

    async def put(self, record: StoredDocumentRecord, data: bytes) -> None: ...

    async def fetch(self, document_ref: str) -> tuple[StoredDocumentRecord, bytes] | None: ...

    async def mark_terminal(self, document_ref: str) -> bool: ...


class InMemoryDocumentByteStore:
    """Deterministic in-memory port for tests and local composition.

    No network, filesystem or environment access. Records are append-only:
    a duplicate ref is rejected and terminal flags are the only mutation.
    """

    def __init__(self) -> None:
        self._records: dict[str, StoredDocumentRecord] = {}
        self._payloads: dict[str, bytes] = {}

    def __repr__(self) -> str:
        return f"InMemoryDocumentByteStore(records={len(self._records)})"

    async def put(self, record: StoredDocumentRecord, data: bytes) -> None:
        if not isinstance(record, StoredDocumentRecord):
            raise DocumentByteStoreError(
                "integrity_mismatch", "Document record is invalid.", status_code=503
            )
        if not isinstance(data, bytes) or not data:
            raise DocumentByteStoreError("empty_payload", "Document payload is empty.")
        if record.document_ref in self._records:
            raise DocumentByteStoreError(
                "ref_conflict", "Document reference already exists.", status_code=503
            )
        self._records[record.document_ref] = record
        self._payloads[record.document_ref] = bytes(data)

    async def fetch(self, document_ref: str) -> tuple[StoredDocumentRecord, bytes] | None:
        record = self._records.get(document_ref)
        if record is None:
            return None
        return record, bytes(self._payloads[document_ref])

    async def mark_terminal(self, document_ref: str) -> bool:
        record = self._records.get(document_ref)
        if record is None:
            return False
        self._records[document_ref] = replace(record, terminal=True)
        return True


class CloudflareD1DocumentByteStore:
    """Durable document byte retention backed by a trusted D1-like binding.

    Mirrors the image/evidence D1 adapters: the binding is deployment-owned,
    schema 0006 is provisioned by the deployment owner (never by app code),
    and payloads are stored base64-encoded in a bounded column. Since this
    addition the adapter has no composition-root importer: wiring the
    ``ENGINE_DOCUMENT_STORE`` alias into the worker is a later, separately
    gated composition slice, and manifest activation stays further behind it.
    """

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise DocumentByteStoreError(
                "store_unavailable",
                "Document byte store binding must provide prepare(sql).",
                status_code=503,
            )
        self._binding = binding

    def __repr__(self) -> str:
        return "CloudflareD1DocumentByteStore(configured)"

    async def _first(self, sql: str, *params: Any) -> Mapping[str, Any] | None:
        row = await _maybe_await(self._binding.prepare(sql).bind(*params).first())
        return dict(row) if isinstance(row, Mapping) else None

    async def _run(self, sql: str, *params: Any) -> Any:
        return await _maybe_await(self._binding.prepare(sql).bind(*params).run())

    @staticmethod
    def _record(row: Mapping[str, Any]) -> StoredDocumentRecord:
        try:
            return StoredDocumentRecord(
                document_ref=str(row["document_ref"]),
                app_id=str(row["app_id"]),
                tenant_id=str(row["tenant_id"]),
                subject_id=str(row["subject_id"]),
                media_type=str(row["media_type"]),
                name=str(row["name"]),
                byte_size=int(row["byte_size"]),
                created_at=_parse_time(row["created_at"]),
                expires_at=_parse_time(row["expires_at"]),
                terminal=bool(row["terminal"]),
            )
        except (KeyError, TypeError, ValueError, DocumentByteStoreError):
            raise DocumentByteStoreError(
                "integrity_mismatch",
                "Document byte store returned an invalid record.",
                status_code=503,
            ) from None

    async def put(self, record: StoredDocumentRecord, data: bytes) -> None:
        if not isinstance(record, StoredDocumentRecord):
            raise DocumentByteStoreError(
                "integrity_mismatch", "Document record is invalid.", status_code=503
            )
        if not isinstance(data, bytes) or not data:
            raise DocumentByteStoreError("empty_payload", "Document payload is empty.")
        if len(data) != record.byte_size:
            raise DocumentByteStoreError(
                "integrity_mismatch", "Document record is invalid.", status_code=503
            )
        payload_base64 = base64.b64encode(data).decode("ascii")
        if len(payload_base64) > MAX_STORED_DOCUMENT_BASE64_CHARS:
            raise DocumentByteStoreError(
                "document_too_large",
                "Document exceeds the bounded per-media size limit.",
                status_code=413,
            )
        existing = await self._first(
            f"SELECT document_ref FROM {_TABLE_NAME} WHERE document_ref=? LIMIT 1",
            record.document_ref,
        )
        if existing is not None:
            raise DocumentByteStoreError(
                "ref_conflict", "Document reference already exists.", status_code=503
            )
        await self._run(
            f"INSERT INTO {_TABLE_NAME} "
            "(document_ref,app_id,tenant_id,subject_id,media_type,name,byte_size,created_at,"
            "expires_at,terminal,payload_base64) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            record.document_ref,
            record.app_id,
            record.tenant_id,
            record.subject_id,
            record.media_type,
            record.name,
            record.byte_size,
            record.created_at.isoformat(),
            record.expires_at.isoformat(),
            1 if record.terminal else 0,
            payload_base64,
        )

    async def fetch(self, document_ref: str) -> tuple[StoredDocumentRecord, bytes] | None:
        row = await self._first(
            f"SELECT document_ref,app_id,tenant_id,subject_id,media_type,name,byte_size,"
            f"created_at,expires_at,terminal,payload_base64 FROM {_TABLE_NAME} "
            "WHERE document_ref=? LIMIT 1",
            document_ref,
        )
        if row is None:
            return None
        record = self._record(row)
        try:
            data = base64.b64decode(str(row["payload_base64"]), validate=True)
        except (binascii.Error, ValueError):
            raise DocumentByteStoreError(
                "integrity_mismatch",
                "Document byte store returned an invalid record.",
                status_code=503,
            ) from None
        if len(data) != record.byte_size:
            raise DocumentByteStoreError(
                "integrity_mismatch",
                "Document byte store returned an invalid record.",
                status_code=503,
            )
        return record, data

    async def mark_terminal(self, document_ref: str) -> bool:
        existing = await self._first(
            f"SELECT document_ref FROM {_TABLE_NAME} WHERE document_ref=? LIMIT 1",
            document_ref,
        )
        if existing is None:
            return False
        await self._run(
            f"UPDATE {_TABLE_NAME} SET terminal=1 WHERE document_ref=?",
            document_ref,
        )
        return True


class ScopedDocumentByteStore:
    """Authority facade: server-side ref minting and scope-checked retrieval.

    Callers can never choose or influence the document reference or the
    expiry; every read re-validates grammar, scope, expiry, terminal state
    and integrity fail-closed. The facade holds no storage knowledge beyond
    the port.
    """

    def __init__(
        self, *, port: DocumentByteStorePort, clock: Callable[[], datetime] | None = None
    ) -> None:
        if port is None:
            raise DocumentByteStoreError(
                "store_unavailable", "Document byte store port is unavailable.", status_code=503
            )
        self._port = port
        self._clock = clock if clock is not None else _utcnow

    def __repr__(self) -> str:
        return "ScopedDocumentByteStore(configured)"

    async def admit_document(
        self,
        *,
        data: bytes,
        media_type: str,
        name: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
    ) -> StoredDocumentRecord:
        """Store bounded bytes once; expiry is minted server-side, never by the caller."""

        _require_scope_id(app_id, "application")
        _require_scope_id(tenant_id, "tenant")
        _require_scope_id(subject_id, "subject")
        if (
            not isinstance(media_type, str)
            or media_type.strip().lower() not in SUPPORTED_DOCUMENT_MEDIA_TYPES
        ):
            raise DocumentByteStoreError(
                "unsupported_media_type",
                "Document media type is not supported.",
                status_code=415,
            )
        if not isinstance(data, bytes) or not data:
            raise DocumentByteStoreError("empty_payload", "Document payload is empty.")
        normalized_media = media_type.strip().lower()
        if len(data) > _size_ceiling_for(normalized_media):
            raise DocumentByteStoreError(
                "document_too_large",
                "Document exceeds the bounded per-media size limit.",
                status_code=413,
            )
        created = self._clock()
        record = None
        for _ in range(_REF_MINT_ATTEMPTS):
            candidate = _require_ref(_REF_PREFIX + secrets.token_urlsafe(_REF_ENTROPY_BYTES))
            try_candidate = StoredDocumentRecord(
                document_ref=candidate,
                app_id=app_id,
                tenant_id=tenant_id,
                subject_id=subject_id,
                media_type=normalized_media,
                name=name,
                byte_size=len(data),
                created_at=created,
                expires_at=created + timedelta(seconds=DEFAULT_DOCUMENT_RETENTION_SECONDS),
            )
            try:
                await self._port.put(try_candidate, data)
            except DocumentByteStoreError as exc:
                if exc.code == "ref_conflict":
                    continue
                raise
            record = try_candidate
            break
        if record is None:
            raise DocumentByteStoreError(
                "ref_conflict",
                "Document reference could not be minted.",
                status_code=503,
            )
        return record

    async def fetch_document(
        self,
        *,
        document_ref: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
    ) -> tuple[StoredDocumentRecord, bytes]:
        """Return scope-matched live bytes; every failure mode fails closed."""

        _require_ref(document_ref)
        _require_scope_id(app_id, "application")
        _require_scope_id(tenant_id, "tenant")
        _require_scope_id(subject_id, "subject")
        fetched = await self._port.fetch(document_ref)
        if fetched is None:
            raise DocumentByteStoreError(
                "not_found", "Document reference is not available.", status_code=404
            )
        record, data = fetched
        if not isinstance(record, StoredDocumentRecord) or record.document_ref != document_ref:
            raise DocumentByteStoreError(
                "integrity_mismatch",
                "Document byte store returned an invalid record.",
                status_code=503,
            )
        if record.app_id != app_id or record.tenant_id != tenant_id or record.subject_id != subject_id:
            raise DocumentByteStoreError(
                "unauthorized",
                "Document scope does not match the caller.",
                status_code=403,
            )
        if (
            record.media_type not in SUPPORTED_DOCUMENT_MEDIA_TYPES
            or not isinstance(data, bytes)
            or not data
            or len(data) != record.byte_size
            or record.byte_size > _size_ceiling_for(record.media_type)
        ):
            raise DocumentByteStoreError(
                "integrity_mismatch",
                "Document byte store returned an invalid record.",
                status_code=503,
            )
        if record.terminal:
            raise DocumentByteStoreError(
                "terminal", "Document reference is no longer active.", status_code=410
            )
        if record.is_expired(self._clock()):
            raise DocumentByteStoreError("expired", "Document has expired.", status_code=410)
        return record, data

    async def invalidate(
        self,
        *,
        document_ref: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
    ) -> bool:
        """Mark one scope-matched record terminal; reads after this fail closed."""

        _require_ref(document_ref)
        _require_scope_id(app_id, "application")
        _require_scope_id(tenant_id, "tenant")
        _require_scope_id(subject_id, "subject")
        fetched = await self._port.fetch(document_ref)
        if fetched is None:
            raise DocumentByteStoreError(
                "not_found", "Document reference is not available.", status_code=404
            )
        record, _ = fetched
        if (
            not isinstance(record, StoredDocumentRecord)
            or record.app_id != app_id
            or record.tenant_id != tenant_id
            or record.subject_id != subject_id
        ):
            raise DocumentByteStoreError(
                "unauthorized",
                "Document scope does not match the caller.",
                status_code=403,
            )
        return await self._port.mark_terminal(document_ref)
