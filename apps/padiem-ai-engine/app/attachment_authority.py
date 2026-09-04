"""Server-owned attachment reference authority for Engine E5 (#1750).

The wire may carry only an opaque reference. Storage locations, credentials,
filesystem paths and remote URLs never become request authority. A deployment-
owned resolver validates scope/expiry and returns bounded bytes privately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Protocol

from padiem_ai_core.b14_multimodal import MAX_B14_IMAGE_BYTES

_ATTACHMENT_REF_RE = re.compile(r"^att_[A-Za-z0-9_-]{16,120}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class EngineAttachmentAuthorityError(ValueError):
    """Fail-closed attachment authority error safe for first-party products."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("attachment authority error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def require_opaque_attachment_ref(value: object) -> str:
    """Accept only non-locator opaque references minted by trusted server code."""

    if not isinstance(value, str) or not _ATTACHMENT_REF_RE.fullmatch(value):
        raise EngineAttachmentAuthorityError(
            "invalid_attachment_reference",
            "Attachment reference is invalid.",
        )
    return value


@dataclass(frozen=True, slots=True)
class TrustedImageAttachment:
    """Private resolver output consumed by Core multimodal validation.

    ``data`` is never projected. Media magic/type correctness is deliberately
    revalidated by the existing Core B14 multimodal contract rather than by a
    second Engine image validator.
    """

    attachment_ref: str
    app_id: str
    media_type: str
    data: bytes
    provenance_id: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attachment_ref", require_opaque_attachment_ref(self.attachment_ref))
        if not isinstance(self.app_id, str) or not _SAFE_ID_RE.fullmatch(self.app_id):
            raise EngineAttachmentAuthorityError(
                "invalid_attachment_authority",
                "Resolved attachment application scope is invalid.",
                status_code=503,
            )
        if not isinstance(self.media_type, str) or not self.media_type.strip() or len(self.media_type) > 127:
            raise EngineAttachmentAuthorityError(
                "invalid_attachment_authority",
                "Resolved attachment media type is invalid.",
                status_code=503,
            )
        object.__setattr__(self, "media_type", self.media_type.strip().lower())
        if not isinstance(self.data, bytes) or not self.data:
            raise EngineAttachmentAuthorityError(
                "invalid_attachment_authority",
                "Resolved attachment bytes are unavailable.",
                status_code=503,
            )
        # Reuse Core's existing byte ceiling. Core still validates data URL,
        # supported media type and image magic before any Provider invocation.
        if len(self.data) > MAX_B14_IMAGE_BYTES:
            raise EngineAttachmentAuthorityError(
                "attachment_too_large",
                "Resolved image exceeds the bounded multimodal size.",
                status_code=413,
            )
        if not isinstance(self.provenance_id, str) or not _SAFE_ID_RE.fullmatch(self.provenance_id):
            raise EngineAttachmentAuthorityError(
                "invalid_attachment_authority",
                "Resolved attachment provenance is invalid.",
                status_code=503,
            )
        if self.expires_at is not None:
            if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
                raise EngineAttachmentAuthorityError(
                    "invalid_attachment_authority",
                    "Resolved attachment expiry is invalid.",
                    status_code=503,
                )

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(timezone.utc)

    def to_public_dict(self) -> dict[str, object]:
        """Expose provenance only; never expose bytes, ref locator or storage state."""

        return {
            "kind": "image",
            "media_type": self.media_type,
            "byte_size": len(self.data),
            "provenance_id": self.provenance_id,
        }


class TrustedAttachmentResolver(Protocol):
    """Deployment authority for private attachment scope and storage lookup.

    Implementations must validate app/tenant/subject scope and expiry before
    returning bytes. The caller cannot provide storage coordinates or scope
    assertions to this interface.
    """

    async def resolve_image(
        self,
        *,
        app_id: str,
        attachment_ref: str,
    ) -> TrustedImageAttachment: ...
