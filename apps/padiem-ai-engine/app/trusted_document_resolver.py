"""Server-owned trusted document resolver for Engine E5B-S2 (#1750),
async durable seam modernized for E8C-B (#2741).

The wire carries only an opaque ``doc_*`` reference (grammar owned by
``app.document_reference``, shared with nothing else: image ``att_*``
references are a different namespace and can never resolve here). The
reference is never a storage locator: the durable document byte store
keys records by the minted ref itself, so no ref-to-locator map, no
deployment-side ``register()`` hook and no in-memory locator binding
remain on this path — the store IS the binding, owned by admission.
Text/binary decoding and document semantics stay in Core (HYBRID_C); this
module only resolves trusted inputs through the async storage seam, bridges
them into the canonical ``NormalizedDocument`` and projects a safe metadata
view. Raw bytes and storage state never appear in any projection.

The storage port is async end to end (mirroring the image lane); sync callers
cross it only via their own event loop (``asyncio.run`` in tests) — there is
no sync-over-async shim here.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from re import compile as _compile
from typing import Protocol

from padiem_ai_core.document_normalization import (
    BINARY_DOCUMENT_MEDIA,
    TEXT_DOCUMENT_MEDIA,
    NormalizedDocument,
    extract_binary_document,
    normalize_text_document,
)

from app.document_reference import (
    DOC_REFERENCE_PATTERN,
    RESOLUTION_ERROR_CODES,
    DocumentResolutionError,
    require_document_reference,
)

__all__ = [
    "DOC_REFERENCE_PATTERN",
    "DocumentResolutionError",
    "RESOLUTION_ERROR_CODES",
    "ResolvedDocumentMeta",
    "DurableDocumentStoragePort",
    "StoragePort",
    "TrustedDocumentResolver",
    "normalize_resolved_document",
    "require_document_reference",
    "resolve_and_normalize",
    "SafeDocumentProjection",
]


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
    """Deployment-owned async byte retention keyed by the opaque document ref.

    Implementations translate references into real storage reads. No storage
    locator ever crosses this boundary towards callers, and callers never
    reach this port without a prior scope-validated resolve.
    """

    async def fetch_document(
        self,
        *,
        document_ref: str,
        app_id: str,
        tenant_id: str,
        subject_id: str,
    ) -> tuple[ResolvedDocumentMeta, bytes]: ...


_SAFE_ID_RE = _compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

# Store failure codes mapped into the single resolver authority vocabulary
# (one language, no competing vocabularies — #2741 failure-semantics note).
_STORE_ERROR_CODES: dict[str, tuple[str, str, int]] = {
    "invalid_document_reference": (
        "invalid_reference",
        "Document reference is invalid.",
        400,
    ),
    "invalid_scope": ("invalid_scope", "Caller document scope is invalid.", 400),
    "not_found": ("not_found", "Document reference is unknown.", 404),
    "unauthorized": (
        "unauthorized",
        "Document scope does not match the request.",
        403,
    ),
    "expired": ("expired", "Document reference has expired.", 410),
    "terminal": ("terminal", "Document reference is no longer active.", 410),
    "integrity_mismatch": (
        "integrity_mismatch",
        "Document payload does not match its recorded size.",
        503,
    ),
    "store_unavailable": (
        "store_unavailable",
        "Document storage is unavailable.",
        503,
    ),
    "empty_payload": (
        "integrity_mismatch",
        "Document payload does not match its recorded size.",
        503,
    ),
    "ref_conflict": (
        "store_unavailable",
        "Document storage is unavailable.",
        503,
    ),
    "unsupported_media_type": (
        "unsupported_media_type",
        "Document media type is not supported for normalization.",
        415,
    ),
    "document_too_large": (
        "integrity_mismatch",
        "Document payload does not match its recorded size.",
        503,
    ),
}


class DurableDocumentStoragePort:
    """Adapt the #2741 scoped document byte store to the resolver's port.

    Records are keyed by their minted ``doc_*`` reference inside the store,
    so this adapter adds no binding state of its own: it translates the
    record into ``ResolvedDocumentMeta`` and maps the store's fail-closed
    errors into the resolver vocabulary above.
    """

    def __init__(self, store: object) -> None:
        if store is None or not callable(getattr(store, "fetch_document", None)):
            raise ValueError("store must expose async fetch_document")
        self._store = store

    def __repr__(self) -> str:
        return "DurableDocumentStoragePort(configured)"

    async def fetch_document(
        self, *, document_ref: str, app_id: str, tenant_id: str, subject_id: str
    ) -> tuple[ResolvedDocumentMeta, bytes]:
        from app.document_byte_store import DocumentByteStoreError

        try:
            record, raw = await self._store.fetch_document(  # type: ignore[attr-defined]
                document_ref=document_ref,
                app_id=app_id,
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except DocumentByteStoreError as exc:
            mapped = _STORE_ERROR_CODES.get(exc.code)
            if mapped is None:  # defensive: unknown store code stays closed
                raise DocumentResolutionError(
                    "store_unavailable",
                    "Document storage is unavailable.",
                    status_code=503,
                ) from None
            code, message, status = mapped
            raise DocumentResolutionError(code, message, status_code=status) from None
        meta = ResolvedDocumentMeta(
            media_type=record.media_type,
            name=record.name,
            byte_size=record.byte_size,
            app_id=record.app_id,
            subject_id=record.subject_id,
            tenant_id=record.tenant_id,
        )
        return meta, raw


class TrustedDocumentResolver:
    """Resolve an opaque ``doc_*`` reference into trusted bytes + meta."""

    def __init__(self, *, storage: StoragePort | DurableDocumentStoragePort) -> None:
        if storage is None or not callable(getattr(storage, "fetch_document", None)):
            raise ValueError("storage port must implement async fetch_document")
        self._storage = storage

    def __repr__(self) -> str:
        return "TrustedDocumentResolver(configured)"

    async def resolve(
        self,
        document_ref: object,
        *,
        app_id: str,
        subject_id: str,
        tenant_id: str,
    ) -> tuple[bytes, ResolvedDocumentMeta]:
        """Fail-closed resolve: grammar, existence, scope and integrity only."""

        reference = require_document_reference(document_ref)
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
        meta, raw = await self._storage.fetch_document(
            document_ref=reference,
            app_id=app_id,
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        if not isinstance(meta, ResolvedDocumentMeta) or not isinstance(raw, bytes):
            raise DocumentResolutionError(
                "integrity_mismatch",
                "Document payload does not match its recorded size.",
                status_code=503,
            )
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


async def resolve_and_normalize(
    resolver: TrustedDocumentResolver,
    document_ref: object,
    *,
    app_id: str,
    subject_id: str,
    tenant_id: str,
) -> NormalizedDocument:
    """Bridge trusted bytes into the canonical Core ``NormalizedDocument``.

    Thin wrapper: one fail-closed async resolve followed by the shared
    ``normalize_resolved_document`` dispatch. A failed resolve or decode
    raises — it never produces a degraded document.
    """

    raw, meta = await resolver.resolve(
        document_ref,
        app_id=app_id,
        subject_id=subject_id,
        tenant_id=tenant_id,
    )
    return normalize_resolved_document(raw, meta)


@dataclass(frozen=True, slots=True)
class SafeDocumentProjection:
    """Public-safe metadata view of a resolved document.

    Only Core-validated metadata appears here: never raw text, never bytes,
    never a ``doc_*``/``att_*`` reference and never a storage locator.
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
