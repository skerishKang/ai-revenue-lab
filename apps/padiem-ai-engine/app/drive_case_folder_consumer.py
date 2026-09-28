"""Internal Engine bridge: case-folder-authorized Drive text -> canonical
document/context/evidence pipeline (#3178, parent #3138).

This composes existing authorities only; it introduces no second Drive
runtime, no second document pipeline and no second Evidence model:

    canonical Drive READ content result  (padiem_ai_core.drive_capability)
        -> Engine case-folder gate        (app.drive_case_folder_scope_projection)
        -> canonical scoped document store (app.document_byte_store)
        -> canonical resolver + normalize  (app.trusted_document_resolver)
        -> canonical context + evidence    (app.context_evidence_bridge)

Hard ordering invariant: the case-folder gate runs **before** any document
admission. On any authorization or envelope denial the canonical document
store and the evidence store are never touched, so no ``doc_*`` reference is
minted for content that was not authorized.

Trust rules:

* the bridge accepts only canonical server-side objects (``DriveCaseFolderScope``,
  ``DriveCaseResource``, optional ``DriveTrustedAncestryProof``, a
  ``TrustedCallerScope``, the canonical stores); caller JSON can never supply a
  folder id, binding ref, tenant/subject id or an ``allowed`` decision;
* the Core decision-projection helper is not an authorization entrypoint and
  is never called directly here: authorization goes through
  ``admit_case_folder_resource()``, whose bounded projection is reused as
  provenance;
* the Drive content envelope must be the canonical Core READ envelope and its
  resource id must equal the authorized resource id;
* Drive content stays untrusted input.

Not in this slice: public route, product wiring, Production composition, live
Google call, live ancestry resolver (``ADMIT_PUBLIC_ROUTE = False``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from padiem_ai_core.document_normalization import (
    MAX_DOCUMENT_NAME_CHARS,
    MAX_TEXT_DOCUMENT_BYTES,
    TEXT_DOCUMENT_MEDIA,
)
from padiem_ai_core.drive_case_folder_scope import (
    DriveCaseFolderScope,
    DriveCaseResource,
    DriveCaseResourceKind,
    DriveTrustedAncestryProof,
)

from app.context_evidence_bridge import att_to_context_evidence
from app.document_byte_store import ScopedDocumentByteStore
from app.document_context_projection import (
    DEFAULT_CONTEXT_MAX_SEGMENTS,
    DEFAULT_CONTEXT_MAX_TEXT_CHARS,
    ContextWindowProjection,
)
from app.document_context_service import TrustedCallerScope
from app.document_evidence_projection import EvidenceStorageProjection
from app.drive_case_folder_scope_projection import admit_case_folder_resource
from app.trusted_document_resolver import (
    TrustedDocumentResolver,
    require_document_reference,
)

DRIVE_CASE_FOLDER_CONSUMER_VERSION = "engine-drive-case-folder-consumer.v1"

# The canonical Core Drive READ envelope provider marker.
DRIVE_CONTENT_PROVIDER = "google_drive"
DRIVE_SOURCE_TYPE = "drive"

# Only content the canonical Drive READ already classified as text-readable is
# eligible in this first bridge slice.
ELIGIBLE_DRIVE_CLASSIFICATIONS = frozenset({"text_read", "google_native_export"})

# Export/provider mime -> Core text media allow-list member.
_TEXT_MEDIA_BY_MIME: dict[str, str] = {
    "text/plain": "text/plain",
    "text/markdown": "text/markdown",
    "text/csv": "text/csv",
    "application/json": "application/json",
}
DEFAULT_DRIVE_TEXT_MEDIA_TYPE = "text/plain"

_FALLBACK_DOCUMENT_NAME = "drive-document.txt"
_MAX_ERROR_CODE_CHARS = 64

# Explicitly denied: this slice wires no product surface.
ADMIT_PUBLIC_ROUTE = False
ADMIT_PRODUCTION_COMPOSITION = False
ADMIT_LIVE_PROVIDER_CALL = False
ADMIT_LIVE_ANCESTRY_RESOLVER = False


class DriveCaseFolderConsumerError(ValueError):
    """Fail-closed bridge error safe for first-party products.

    Messages are static per code and never echo content, references, scope
    values or provider payloads.
    """

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if (
            not isinstance(code, str)
            or not code
            or len(code) > _MAX_ERROR_CODE_CHARS
            or not code[0].islower()
        ):
            raise ValueError("drive consumer error code must be a bounded lowercase token")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True, repr=False)
class DriveCaseFolderConsumerResult:
    """Bounded internal result of one case-folder-authorized Drive admission.

    Internal provenance linkage is retained for later Legal citation wiring but
    is excluded from the public projection and the repr: raw binding refs, the
    scope ref, the Drive resource ref, the canonical ``doc_*`` ref and the
    storage locator never appear on the public side.
    """

    evidence_id: str
    document_ref: str = field(repr=False)
    context_projection: ContextWindowProjection = field(repr=False)
    evidence_projection: EvidenceStorageProjection = field(repr=False)
    provenance: dict[str, Any] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Public-safe projection: no refs, scope ids, locators or credentials."""

        return {
            "ok": True,
            "source": {"source_type": DRIVE_SOURCE_TYPE, "content_trusted": False},
            "document": self.context_projection.to_dict(),
            "evidence": {"evidence_id": self.evidence_id},
        }

    def __repr__(self) -> str:
        return (
            "DriveCaseFolderConsumerResult("
            f"evidence_id={self.evidence_id}, "
            f"segment_count={self.evidence_projection.normalized_document.segment_count}, "
            "document_ref=redacted, binding_ref=redacted, resource_ref=redacted, "
            "scope_ref=redacted, storage_locator=redacted)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class _ValidatedDriveText:
    payload: bytes = field(repr=False)
    media_type: str
    name: str
    version_evidence: dict[str, Any] | None = field(default=None, repr=False)
    shared_drive_ref: str | None = None
    resource_classification: str = ""


def _bounded_document_name(value: object) -> str:
    """Server-side name shape guard; semantics stay with Core normalization."""

    if isinstance(value, str):
        cleaned = "".join(ch for ch in value.strip() if ch >= " " and ch != "\x7f")
        cleaned = cleaned.strip()[:MAX_DOCUMENT_NAME_CHARS]
        if cleaned:
            return cleaned
    return _FALLBACK_DOCUMENT_NAME


def _resolve_media_type(explicit: object, envelope: Mapping[str, Any], resource: DriveCaseResource) -> str:
    if explicit is not None:
        if not isinstance(explicit, str) or explicit.strip().lower() not in TEXT_DOCUMENT_MEDIA:
            raise DriveCaseFolderConsumerError(
                "unsupported_media_type",
                "Drive content media type is not a supported text document type.",
                status_code=415,
            )
        return explicit.strip().lower()
    export_mime = envelope.get("export_mime_type")
    if isinstance(export_mime, str):
        mapped = _TEXT_MEDIA_BY_MIME.get(export_mime.strip().lower())
        if mapped is not None:
            return mapped
    if resource.mime_type in TEXT_DOCUMENT_MEDIA:
        return resource.mime_type
    return DEFAULT_DRIVE_TEXT_MEDIA_TYPE


def _validate_drive_text_envelope(
    envelope: Mapping[str, Any],
    resource: DriveCaseResource,
    *,
    explicit_media_type: object,
) -> _ValidatedDriveText:
    """Validate the canonical Drive READ content envelope, fail closed.

    Runs only after the case-folder gate passed, and never touches a store.
    """

    if envelope.get("provider") != DRIVE_CONTENT_PROVIDER:
        raise DriveCaseFolderConsumerError(
            "wrong_provider", "Drive content did not come from the canonical Drive provider."
        )
    if envelope.get("result_status") != "OK":
        # REVIEW_REQUIRED covers the bounded-envelope overflow marker and any
        # provider status that is not a complete, reviewed read.
        raise DriveCaseFolderConsumerError(
            "drive_content_not_complete",
            "Drive content is not a complete reviewed read.",
        )
    if envelope.get("content_truncated") is not False:
        # Legal accuracy: a size-truncated Drive read is never admitted as a
        # complete evidence document in this slice.
        raise DriveCaseFolderConsumerError(
            "truncated_drive_content",
            "Truncated Drive content is not admitted as a complete document.",
        )

    classification = envelope.get("resource_classification")
    if not isinstance(classification, str) or classification not in ELIGIBLE_DRIVE_CLASSIFICATIONS:
        raise DriveCaseFolderConsumerError(
            "ineligible_drive_content",
            "Drive content class is not eligible for document admission.",
        )

    projection = envelope.get("projection")
    if not isinstance(projection, Mapping):
        raise DriveCaseFolderConsumerError(
            "malformed_drive_envelope",
            "Drive content envelope is missing a bounded resource projection.",
        )
    if projection.get("file_id") != resource.resource_id:
        raise DriveCaseFolderConsumerError(
            "drive_resource_id_mismatch",
            "Drive content does not belong to the authorized resource.",
        )
    if projection.get("shortcut_target_id") is not None:
        raise DriveCaseFolderConsumerError(
            "shortcut_content_not_eligible",
            "Drive shortcut content requires independently authorized resolution.",
        )
    if resource.kind is DriveCaseResourceKind.SHORTCUT:
        raise DriveCaseFolderConsumerError(
            "shortcut_content_not_eligible",
            "Drive shortcut content requires independently authorized resolution.",
        )
    if projection.get("shared_drive_id") != resource.shared_drive_id:
        raise DriveCaseFolderConsumerError(
            "drive_shared_drive_mismatch",
            "Drive content space identity does not match the authorized resource.",
        )

    content = envelope.get("content")
    if not isinstance(content, str) or not content.strip():
        raise DriveCaseFolderConsumerError(
            "empty_drive_content", "Drive content is empty."
        )
    payload = content.encode("utf-8")
    if not payload:
        raise DriveCaseFolderConsumerError(
            "empty_drive_content", "Drive content is empty."
        )
    if len(payload) > MAX_TEXT_DOCUMENT_BYTES:
        raise DriveCaseFolderConsumerError(
            "document_too_large",
            "Drive content exceeds the bounded text document size.",
            status_code=413,
        )

    version_evidence = projection.get("version_evidence")
    return _ValidatedDriveText(
        payload=payload,
        media_type=_resolve_media_type(explicit_media_type, envelope, resource),
        name=_bounded_document_name(projection.get("name")),
        version_evidence=dict(version_evidence) if isinstance(version_evidence, Mapping) else None,
        shared_drive_ref=resource.shared_drive_id,
        resource_classification=classification,
    )


async def bridge_case_folder_drive_text(
    *,
    scope: DriveCaseFolderScope,
    resource: DriveCaseResource,
    drive_content_result: Mapping[str, Any],
    caller_scope: TrustedCallerScope,
    document_store: ScopedDocumentByteStore,
    document_resolver: TrustedDocumentResolver,
    evidence_storage: object | None = None,
    ancestry: DriveTrustedAncestryProof | None = None,
    media_type: str | None = None,
    context_max_text_chars: int = DEFAULT_CONTEXT_MAX_TEXT_CHARS,
    context_max_segments: int = DEFAULT_CONTEXT_MAX_SEGMENTS,
) -> DriveCaseFolderConsumerResult:
    """Admit one authorized Drive text resource into the canonical pipeline.

    Ordering is the contract: case-folder authorization -> envelope validation
    -> canonical document admission -> canonical context/evidence projections.
    Raises :class:`EngineDriveCaseFolderScopeError` on an authorization denial
    and :class:`DriveCaseFolderConsumerError` on an envelope/content denial;
    in both cases the stores have not been touched.
    """

    if not isinstance(scope, DriveCaseFolderScope):
        raise DriveCaseFolderConsumerError(
            "invalid_scope", "Case-folder scope must be a canonical DriveCaseFolderScope."
        )
    if not isinstance(resource, DriveCaseResource):
        raise DriveCaseFolderConsumerError(
            "invalid_resource", "Drive resource must be a canonical DriveCaseResource."
        )
    if ancestry is not None and not isinstance(ancestry, DriveTrustedAncestryProof):
        raise DriveCaseFolderConsumerError(
            "invalid_ancestry",
            "Ancestry proof must be a canonical DriveTrustedAncestryProof.",
        )
    if not isinstance(caller_scope, TrustedCallerScope):
        raise DriveCaseFolderConsumerError(
            "invalid_trusted_scope",
            "Caller scope must be a server-minted TrustedCallerScope.",
            status_code=503,
        )
    if not isinstance(drive_content_result, Mapping):
        raise DriveCaseFolderConsumerError(
            "malformed_drive_envelope", "Drive content result must be an object."
        )
    if not isinstance(document_store, ScopedDocumentByteStore):
        raise DriveCaseFolderConsumerError(
            "document_store_unavailable",
            "Canonical document byte store is unavailable.",
            status_code=503,
        )
    if not callable(getattr(document_resolver, "resolve", None)):
        raise DriveCaseFolderConsumerError(
            "document_resolver_unavailable",
            "Canonical trusted document resolver is unavailable.",
            status_code=503,
        )
    if evidence_storage is None or not callable(getattr(evidence_storage, "store", None)):
        raise DriveCaseFolderConsumerError(
            "evidence_storage_unavailable",
            "Evidence retention storage is unavailable.",
            status_code=503,
        )

    # (1) Case-folder authorization gate. Must precede every store interaction.
    authorization = admit_case_folder_resource(scope, resource, ancestry=ancestry)

    # (2) Canonical Drive envelope validation. Still no store interaction.
    validated = _validate_drive_text_envelope(
        drive_content_result, resource, explicit_media_type=media_type
    )

    # (3) Canonical document admission mints the server-owned doc_* reference.
    record = await document_store.admit_document(
        data=validated.payload,
        media_type=validated.media_type,
        name=validated.name,
        app_id=caller_scope.app_id,
        tenant_id=caller_scope.tenant_id,
        subject_id=caller_scope.subject_id,
    )
    reference = require_document_reference(record.document_ref)

    # (4) Canonical resolver -> normalization -> context + evidence projections.
    context_projection, evidence_projection = await att_to_context_evidence(
        document_resolver,
        reference,
        app_id=caller_scope.app_id,
        subject_id=caller_scope.subject_id,
        tenant_id=caller_scope.tenant_id,
        context_max_text_chars=context_max_text_chars,
        context_max_segments=context_max_segments,
        evidence_storage=evidence_storage,
    )
    if not isinstance(evidence_projection, EvidenceStorageProjection):
        raise DriveCaseFolderConsumerError(
            "evidence_projection_unavailable",
            "Canonical evidence projection is unavailable.",
            status_code=503,
        )

    provenance: dict[str, Any] = {
        "bridge_version": DRIVE_CASE_FOLDER_CONSUMER_VERSION,
        "source_type": DRIVE_SOURCE_TYPE,
        "case_folder_scope_ref": scope.scope_ref,
        "drive_resource_ref": resource.resource_id,
        "drive_binding_ref": scope.binding_ref,
        "shared_drive_ref": validated.shared_drive_ref,
        "drive_resource_classification": validated.resource_classification,
        "drive_resource_version_evidence": validated.version_evidence,
        "authorization_decision": authorization.get("decision"),
        "authorization_scope_ref": authorization.get("scope_ref"),
        "authorization_proof_trusted": authorization.get("ancestry_proof_trusted"),
        "canonical_document_ref": reference,
        "canonical_evidence_id": evidence_projection.evidence_id,
        "content_truncated": False,
        "partial_document": False,
        "complete_document": True,
        # No exact locator exists for a Drive text bridge: preserve the gap
        # honestly instead of inventing a page/section.
        "page_or_section": "UNAVAILABLE",
        "exact_locator_available": False,
    }
    return DriveCaseFolderConsumerResult(
        evidence_id=evidence_projection.evidence_id,
        document_ref=reference,
        context_projection=context_projection,
        evidence_projection=evidence_projection,
        provenance=provenance,
    )


def drive_case_folder_consumer_snapshot() -> dict[str, Any]:
    """Deterministic, network-free snapshot of this bridge's posture."""

    return {
        "bridge_version": DRIVE_CASE_FOLDER_CONSUMER_VERSION,
        "reuses_canonical_drive_read": True,
        "reuses_canonical_document_store": True,
        "reuses_canonical_normalization": True,
        "reuses_canonical_context_projection": True,
        "reuses_canonical_evidence_storage": True,
        "gate_before_document_admission": True,
        "second_drive_runtime": False,
        "second_document_pipeline": False,
        "second_evidence_model": False,
        "drive_write": False,
        "public_route": ADMIT_PUBLIC_ROUTE,
        "production_composition": ADMIT_PRODUCTION_COMPOSITION,
        "live_provider_calls": 0,
        "live_ancestry_resolver": ADMIT_LIVE_ANCESTRY_RESOLVER,
        "raw_credentials_present": False,
    }


__all__ = [
    "DRIVE_CASE_FOLDER_CONSUMER_VERSION",
    "DRIVE_CONTENT_PROVIDER",
    "DRIVE_SOURCE_TYPE",
    "ELIGIBLE_DRIVE_CLASSIFICATIONS",
    "DEFAULT_DRIVE_TEXT_MEDIA_TYPE",
    "ADMIT_PUBLIC_ROUTE",
    "ADMIT_PRODUCTION_COMPOSITION",
    "ADMIT_LIVE_PROVIDER_CALL",
    "ADMIT_LIVE_ANCESTRY_RESOLVER",
    "DriveCaseFolderConsumerError",
    "DriveCaseFolderConsumerResult",
    "bridge_case_folder_drive_text",
    "drive_case_folder_consumer_snapshot",
]
