"""Deployment-owned trusted attachment resolver over the canonical byte store (#2137 S1).

This is the first concrete implementation of the existing
``app.attachment_authority.TrustedAttachmentResolver`` protocol. It consumes
the merged #2138 canonical scoped image-byte store
(``app.attachment_byte_store.ScopedImageByteStore``) and returns the existing
``TrustedImageAttachment`` contract; it deliberately does not create a second
attachment model.

Authority rules:

- the wire may carry only an opaque server-minted ``att_*`` reference; no URL,
  path, storage locator or key is ever accepted as resolver input;
- the full ``app_id + tenant_id + subject_id`` triple comes from a
  deployment-injected ``TrustedCallerScope`` (the same server-minted scope
  contract used by the document lane). The requested ``app_id`` is only ever
  honored when it exactly matches the trusted scope's own ``app_id``; a
  client-asserted identity never overrides or substitutes the injected scope;
- expiry, terminal invalidation, scope correlation, byte bounds and the image
  media allowlist are enforced fail-closed by the canonical store and mapped
  here into the ``EngineAttachmentAuthorityError`` vocabulary that
  ``MultimodalAttachmentEngineService`` already propagates;
- B14 remains the sole provider/model/media-magic authority: this resolver
  returns bounded bytes and never routes, calls or authenticates a provider.

Source-only in S1: nothing in the composition root or worker code imports this
module; production resolver wiring is a separate, explicitly gated later step.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import secrets
from typing import Any, Callable

from app.attachment_authority import (
    EngineAttachmentAuthorityError,
    TrustedImageAttachment,
    require_opaque_attachment_ref,
)
from app.attachment_byte_store import ImageByteStoreError, StoredImageRecord
from app.document_context_service import TrustedCallerScope

_PROVENANCE_PREFIX = "prov_"
_PROVENANCE_ENTROPY_BYTES = 16
_PROVENANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

# Canonical store failure codes mapped into the attachment authority
# vocabulary the consuming service already propagates fail-closed.
_STORE_ERROR_CODES: dict[str, tuple[str, str, int]] = {
    "invalid_attachment_reference": (
        "invalid_attachment_reference",
        "Attachment reference is invalid.",
        400,
    ),
    "not_found": (
        "attachment_not_found",
        "Attachment reference is unknown.",
        404,
    ),
    "unauthorized": (
        "attachment_scope_mismatch",
        "Attachment is not authorized for this application scope.",
        403,
    ),
    "attachment_expired": (
        "attachment_expired",
        "Attachment reference has expired.",
        410,
    ),
    "attachment_terminal": (
        "attachment_expired",
        "Attachment reference has expired.",
        410,
    ),
}


def _default_provenance(record: StoredImageRecord) -> str:
    return _PROVENANCE_PREFIX + secrets.token_urlsafe(_PROVENANCE_ENTROPY_BYTES)


@dataclass(frozen=True, slots=True)
class ByteStoreTrustedAttachmentResolver:
    """Resolve one opaque ``att_*`` reference inside one trusted caller scope.

    The instance is bound to a single deployment-minted ``TrustedCallerScope``;
    constructing it is a deployment responsibility (the later production
    composition gate), never a request-side one.
    """

    store: Any
    scope: TrustedCallerScope
    provenance_factory: Callable[[StoredImageRecord], str] = _default_provenance

    def __post_init__(self) -> None:
        if self.store is None or not callable(getattr(self.store, "fetch_image", None)):
            raise ValueError("store must expose async fetch_image")
        if not isinstance(self.scope, TrustedCallerScope):
            raise ValueError("scope must be a server-minted TrustedCallerScope")
        if not callable(self.provenance_factory):
            raise ValueError("provenance_factory must be callable")

    def __repr__(self) -> str:
        return "ByteStoreTrustedAttachmentResolver(configured)"

    async def resolve_image(self, *, app_id: str, attachment_ref: str) -> TrustedImageAttachment:
        """Return the trusted bounded attachment or fail closed via authority errors."""

        require_opaque_attachment_ref(attachment_ref)
        if not isinstance(app_id, str) or app_id != self.scope.app_id:
            raise EngineAttachmentAuthorityError(
                "attachment_scope_mismatch",
                "Attachment is not authorized for this application scope.",
                status_code=403,
            )
        try:
            record, data = await self.store.fetch_image(
                attachment_ref=attachment_ref,
                app_id=self.scope.app_id,
                tenant_id=self.scope.tenant_id,
                subject_id=self.scope.subject_id,
            )
        except ImageByteStoreError as exc:
            mapped = _STORE_ERROR_CODES.get(exc.code)
            if mapped is None:
                raise EngineAttachmentAuthorityError(
                    "attachment_resolver_unavailable",
                    "Trusted attachment resolution failed.",
                    status_code=503,
                ) from None
            raise EngineAttachmentAuthorityError(*mapped[:2], status_code=mapped[2]) from None
        except Exception:
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment resolution failed.",
                status_code=503,
            ) from None
        if not isinstance(record, StoredImageRecord) or not isinstance(data, bytes):
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment resolver returned an invalid result.",
                status_code=503,
            )
        provenance_id = self.provenance_factory(record)
        if not isinstance(provenance_id, str) or not _PROVENANCE_RE.fullmatch(provenance_id):
            raise EngineAttachmentAuthorityError(
                "invalid_attachment_authority",
                "Resolved attachment provenance is invalid.",
                status_code=503,
            )
        return TrustedImageAttachment(
            attachment_ref=record.attachment_ref,
            app_id=self.scope.app_id,
            media_type=record.media_type,
            data=data,
            provenance_id=provenance_id,
            expires_at=record.expires_at,
        )
