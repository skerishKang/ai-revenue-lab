"""Resolve-to-projection pipeline for Engine E5B-S3 (#1750).

Connects the S2 trusted resolver and normalization bridge to the two S3
destinations without changing either contract:

    att_* --resolve--> (bytes, meta) --normalize--> NormalizedDocument
        |-> ContextWindowProjection   (bounded, body-free)
        |-> EvidenceStorageProjection (full retention, internal refs only)

There is no route and no durable storage yet. Evidence storage locators are
synthetic opaque tokens owned by the engine, not real object addresses.
"""

from __future__ import annotations

from padiem_ai_core.document_normalization import NormalizedDocument

from app.document_context_projection import (
    DEFAULT_CONTEXT_MAX_SEGMENTS,
    DEFAULT_CONTEXT_MAX_TEXT_CHARS,
    ContextWindowProjection,
)
from app.document_evidence_projection import EvidenceStorageProjection
from app.trusted_document_resolver import (
    ResolvedDocumentMeta,
    TrustedDocumentResolver,
    require_document_reference,
    resolve_and_normalize,
)


def project_to_context(
    document: NormalizedDocument,
    *,
    max_text_chars: int = DEFAULT_CONTEXT_MAX_TEXT_CHARS,
    max_segments: int = DEFAULT_CONTEXT_MAX_SEGMENTS,
) -> ContextWindowProjection:
    """Derive the context-window-safe projection of one normalized document."""

    return ContextWindowProjection.from_normalized(
        document,
        max_text_chars=max_text_chars,
        max_segments=max_segments,
    )


def project_to_evidence(
    att_ref: object,
    document: NormalizedDocument,
    meta: ResolvedDocumentMeta,
    storage_locator: str,
    *,
    evidence_id: str | None = None,
    created_at=None,
) -> EvidenceStorageProjection:
    """Derive the full-retention evidence projection behind an engine id."""

    return EvidenceStorageProjection.from_resolver_result(
        att_ref,
        document,
        meta,
        storage_locator,
        evidence_id=evidence_id,
        created_at=created_at,
    )


def att_to_context_evidence(
    resolver: TrustedDocumentResolver,
    att_ref: object,
    *,
    app_id: str,
    subject_id: str,
    tenant_id: str,
    context_max_text_chars: int = DEFAULT_CONTEXT_MAX_TEXT_CHARS,
    context_max_segments: int = DEFAULT_CONTEXT_MAX_SEGMENTS,
    evidence_storage: "object | None" = None,
) -> tuple[ContextWindowProjection, EvidenceStorageProjection]:
    """Run the S3 through-line: reference -> document -> both projections.

    Resolution/normalization reuse the S2 bridge verbatim. When an evidence
    storage port is supplied the projection is retained and its minted id is
    the storage handle; the synthetic ``evidence://`` token itself is opaque
    engine state and never a caller input.
    """

    document = resolve_and_normalize(
        resolver,
        att_ref,
        app_id=app_id,
        subject_id=subject_id,
        tenant_id=tenant_id,
    )
    _, meta = resolver.resolve(
        att_ref,
        app_id=app_id,
        subject_id=subject_id,
        tenant_id=tenant_id,
    )
    context_projection = project_to_context(
        document,
        max_text_chars=context_max_text_chars,
        max_segments=context_max_segments,
    )
    reference = require_document_reference(att_ref)
    evidence_projection = project_to_evidence(
        reference,
        document,
        meta,
        f"evidence://{reference}",
    )
    if evidence_storage is not None:
        evidence_storage.store(evidence_projection)
    return context_projection, evidence_projection
