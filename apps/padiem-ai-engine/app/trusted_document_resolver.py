"""Server-owned trusted document resolver for Engine E5B-S2 (#1750).

The wire carries only an opaque ``att_*`` reference. The reference is never a
storage locator: a deployment-owned ref-to-locator map plus a storage port
resolve real bytes privately behind a scope check. Text/binary decoding and
document semantics stay in Core (HYBRID_C); this module only resolves trusted
inputs, bridges them into the canonical ``NormalizedDocument`` and projects a
safe metadata view. Raw bytes and locators never appear in any projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
import re
from typing import Protocol

from padiem_ai_core.document_normalization import (
    BINARY_DOCUMENT_MEDIA,
    TEXT_DOCUMENT_MEDIA,
    NormalizedDocument,
    extract_binary_document,
    normalize_text_document,
)

ATT_REFERENCE_PATTERN = re.compile(r"^att_[a-zA-Z0-9_\-]{8,128}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

RESOLUTION_ERROR_CODES = frozenset(
    {
        "invalid_reference",
        "invalid_scope",
        "unauthorized",
        "not_found",
        "integrity_mismatch",
        "decode_failed",
        "unsupported_media_type",
    }
)


class DocumentResolutionError(ValueError):
    """Fail-closed document resolution error safe for first-party products."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or code not in RESOLUTION_ERROR_CODES:
            raise ValueError("document resolution error code must be a known safe code")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ResolvedDocumentMeta:
    """Server-owned storage metadata for one document blob.

    The scope triple (app/tenant/subject) is minted by trusted storage
    admission code; callers can only assert it, never supply coordinates.
    """

    media_type: str
    name: str
    byte_size: int
    app_id: str
    subject_id: str
    tenant_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.media_type, str) or not self.media_type.strip() or len(self.media_type) > 127:
            raise DocumentResolutionError(
                "integrity_mismatch",
                "Resolved document media type is invalid.",
                status_code=503,
            )
        object.__setattr__(self, "media_type", self.media_type.strip().lower())
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 120:
            raise DocumentResolutionError(
                "integrity_mismatch",
                "Resolved document name is invalid.",
                status_code=503,
            )
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise DocumentResolutionError(
                "integrity_mismatch",
                "Resolved document size is invalid.",
                status_code=503,
            )
        for label, value in (
            ("app_id", self.app_id),
            ("subject_id", self.subject_id),
            ("tenant_id", self.tenant_id),
        ):
            if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
                raise DocumentResolutionError(
                    "integrity_mismatch",
                    f"Resolved document {label} scope is invalid.",
                    status_code=503,
                )


class StoragePort(Protocol):
    """Deployment-owned blob storage behind opaque locators.

    Implementations translate locators into real storage addresses. Locators
    never cross this boundary towards callers, and callers never reach this
    port without a prior scope-validated resolve.
    """

    def fetch_meta(self, locator: str) -> "ResolvedDocumentMeta | None": ...

    def fetch_bytes(self, locator: str) -> bytes | None: ...


class InMemoryStoragePort:
    """Test/demo storage port; no network, filesystem or provider access."""

    def __init__(self) -> None:
        self._payloads: dict[str, bytes] = {}
        self._metas: dict[str, ResolvedDocumentMeta] = {}

    def store(self, locator: str, payload: bytes, meta: ResolvedDocumentMeta) -> None:
        if not isinstance(locator, str) or not locator or len(locator) > 256:
            raise ValueError("storage locator must be a non-empty bounded server token")
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("stored document payload must be non-empty bytes")
        if not isinstance(meta, ResolvedDocumentMeta):
            raise ValueError("stored document meta must be a ResolvedDocumentMeta")
        self._payloads[locator] = payload
        self._metas[locator] = meta

    def fetch_meta(self, locator: str) -> ResolvedDocumentMeta | None:
        return self._metas.get(locator)

    def fetch_bytes(self, locator: str) -> bytes | None:
        return self._payloads.get(locator)


class TrustedDocumentResolver:
    """Resolve an opaque ``att_*`` reference into trusted local bytes + meta."""

    def __init__(
        self,
        *,
        storage: StoragePort,
        locators: Mapping[str, str] | None = None,
    ) -> None:
        if not hasattr(storage, "fetch_meta") or not hasattr(storage, "fetch_bytes"):
            raise ValueError("storage port must implement fetch_meta and fetch_bytes")
        self._storage = storage
        self._locators: dict[str, str] = dict(locators or {})

    def register(self, att_ref: str, locator: str) -> None:
        """Server-side admission hook: bind a minted ref to a storage locator."""

        reference = require_document_reference(att_ref)
        if not isinstance(locator, str) or not locator or len(locator) > 256:
            raise ValueError("storage locator must be a non-empty bounded server token")
        self._locators[reference] = locator

    def resolve(
        self,
        att_ref: object,
        *,
        app_id: str,
        subject_id: str,
        tenant_id: str,
    ) -> tuple[bytes, ResolvedDocumentMeta]:
        """Fail-closed resolve: grammar, existence, scope and integrity only."""

        reference = require_document_reference(att_ref)
        for label, value in (
            ("app_id", app_id),
            ("subject_id", subject_id),
            ("tenant_id", tenant_id),
        ):
            if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
                raise DocumentResolutionError(
                    "invalid_scope",
                    f"Caller {label} is invalid.",
                )
        locator = self._locators.get(reference)
        if locator is None:
            raise DocumentResolutionError("not_found", "Document reference is unknown.", status_code=404)
        meta = self._storage.fetch_meta(locator)
        if meta is None:
            raise DocumentResolutionError("not_found", "Document reference is unknown.", status_code=404)
        raw = self._storage.fetch_bytes(locator)
        if raw is None:
            raise DocumentResolutionError("not_found", "Document payload is unavailable.", status_code=404)
        if (app_id, subject_id, tenant_id) != (meta.app_id, meta.subject_id, meta.tenant_id):
            raise DocumentResolutionError(
                "unauthorized",
                "Document scope does not match the request.",
                status_code=403,
            )
        if not raw or len(raw) != meta.byte_size:
            raise DocumentResolutionError(
                "integrity_mismatch",
                "Document payload does not match its recorded size.",
                status_code=503,
            )
        return raw, meta


def require_document_reference(value: object) -> str:
    """Accept only non-locator opaque references matching the ``att_*`` grammar."""

    if not isinstance(value, str) or not ATT_REFERENCE_PATTERN.fullmatch(value):
        raise DocumentResolutionError(
            "invalid_reference",
            "Document reference is invalid.",
        )
    return value


def normalize_resolved_document(
    raw: bytes,
    meta: ResolvedDocumentMeta,
) -> NormalizedDocument:
    """Normalize already-resolved trusted bytes into the canonical Core document.

    Semantic dispatch is the Core allow-lists only: text/* and JSON go through
    ``normalize_text_document`` after a private UTF-8 decode; PDF/DOCX/PPTX/
    XLSX go through ``extract_binary_document``. A failed decode raises — it
    never produces a degraded document. Callers must have completed the
    fail-closed resolve (scope + integrity) before handing bytes over.
    """

    if not isinstance(raw, bytes):
        raise DocumentResolutionError(
            "decode_failed",
            "Document payload must be bytes before normalization.",
            status_code=503,
        )
    if not isinstance(meta, ResolvedDocumentMeta):
        raise DocumentResolutionError(
            "integrity_mismatch",
            "Document metadata must be a ResolvedDocumentMeta before normalization.",
            status_code=503,
        )
    if meta.media_type in TEXT_DOCUMENT_MEDIA:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentResolutionError(
                "decode_failed",
                "Document bytes are not valid UTF-8 text.",
            ) from exc
        return normalize_text_document(name=meta.name, media_type=meta.media_type, text=text)
    if meta.media_type in BINARY_DOCUMENT_MEDIA:
        return extract_binary_document(name=meta.name, media_type=meta.media_type, payload=raw)
    raise DocumentResolutionError(
        "unsupported_media_type",
        "Document media type is not supported for normalization.",
    )


def resolve_and_normalize(
    resolver: TrustedDocumentResolver,
    att_ref: object,
    *,
    app_id: str,
    subject_id: str,
    tenant_id: str,
) -> NormalizedDocument:
    """Bridge trusted bytes into the canonical Core ``NormalizedDocument``.

    Thin wrapper: one fail-closed resolve followed by the shared
    ``normalize_resolved_document`` dispatch. A failed resolve or decode
    raises — it never produces a degraded document.
    """

    raw, meta = resolver.resolve(
        att_ref,
        app_id=app_id,
        subject_id=subject_id,
        tenant_id=tenant_id,
    )
    return normalize_resolved_document(raw, meta)


@dataclass(frozen=True, slots=True)
class SafeDocumentProjection:
    """Public-safe metadata view of a resolved document.

    Only Core-validated metadata appears here: never raw text, never bytes,
    never an ``att_*`` reference and never a storage locator.
    """

    kind: str | None
    name: str
    media_type: str
    byte_size: int
    text_chars: int
    segment_count: int
    status: str
    content_trust_class: str

    @classmethod
    def from_document(cls, document: NormalizedDocument) -> "SafeDocumentProjection":
        if not isinstance(document, NormalizedDocument):
            raise ValueError("projection requires a canonical NormalizedDocument")
        return cls(
            kind=document.kind.value if document.kind is not None else None,
            name=document.name,
            media_type=document.media_type,
            byte_size=document.byte_size,
            text_chars=document.text_chars,
            segment_count=document.segment_count,
            status=document.status.value,
            content_trust_class=document.content_trust_class,
        )

    def to_dict(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}
