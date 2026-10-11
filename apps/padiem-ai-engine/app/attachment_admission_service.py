"""Trusted image-byte admission boundary for Engine E5C (#2727).

This is the HTTP admission seam the scoped byte store has been missing since
#2137/#2138: callers upload bounded base64 image bytes once and receive only
the server-minted opaque ``att_*`` reference back. ``ScopedImageByteStore.
admit_image`` remains the single size/media/scope/grammar authority; this
module owns exactly the wire boundary and nothing else:

* the authenticated Engine caller is established by the shared service-identity
  boundary in ``worker_identity.py`` before this service is ever invoked;
* the tenant/subject scope is minted **only** from the resolved Control Plane
  auth session (``app_id`` plus the request's opaque ``session_id``; raw
  tenant/subject assertions are never read, and unsupported fields fail
  closed);
* the base64 payload is decoded strictly and bounded before the store sees
  any bytes; the store re-enforces its own decoded ceiling independently;
* media magic stays deliberately validated by Core B14 downstream (same
  convention as ``app/attachment_byte_store.py``), not a second Engine image
  validator;
* one admission is one immutable append-only record; there is no client-
  chosen reference, expiry, locator or idempotency replay surface.

When either authority input is absent the route fails closed 503, exactly as
the E5A reference routes do. Admission writes no model calls and reaches no
provider: it is storage-side source wiring only.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
import json
from typing import Any

from app.attachment_authority import EngineAttachmentAuthorityError
from app.attachment_byte_store import (
    ImageByteStoreError,
    MAX_STORED_IMAGE_BASE64_CHARS,
    StoredImageRecord,
)
from app.auth_session_scope_authority import AuthSessionScopeAuthority
from app.document_context_service import DocumentAuthorityError
from app.service import ServiceResponse, _service_error

ATTACHMENT_ADMISSION_PATH = "/internal/v1/multimodal/attachments"

# Admission-only body ceiling: the canonical base64 payload bound plus headroom
# for the JSON envelope. The shared MAX_REQUEST_BODY_BYTES (128 KiB) is for
# text/reference routes and is far below one admitted image by design.
MAX_ADMISSION_REQUEST_BODY_BYTES = MAX_STORED_IMAGE_BASE64_CHARS + (8 * 1024)

# Tenant, subject, attachment_ref, locators and expiry are server-side facts;
# presenting any of them on this wire is a fail-closed request shape error.
_REQUIRED = frozenset({"app_id", "session_id", "media_type", "image_base64"})
_ALLOWED = _REQUIRED | frozenset({"trace_id"})


def _bounded_b64_chars() -> str:
    return (
        "Image attachment payload exceeds the bounded multimodal base64 size."
    )


class AttachmentAdmissionEngineService:
    """Thin Engine boundary over the canonical scoped image byte store."""

    def __init__(
        self,
        *,
        image_byte_store: Any | None = None,
        scope_authority: AuthSessionScopeAuthority | None = None,
    ) -> None:
        if image_byte_store is not None and not callable(
            getattr(image_byte_store, "admit_image", None)
        ):
            raise ValueError("image_byte_store must expose async admit_image")
        if scope_authority is not None and not callable(
            getattr(scope_authority, "scope_for_request", None)
        ):
            raise ValueError("scope_authority must expose async scope_for_request")
        self._image_byte_store = image_byte_store
        self._scope_authority = scope_authority

    async def _scope_for(self, *, app_id: str, session_id: str) -> Any:
        if self._image_byte_store is None or self._scope_authority is None:
            raise EngineAttachmentAuthorityError(
                "attachment_admission_unavailable",
                "Trusted attachment admission authority is unavailable.",
                status_code=503,
            )
        try:
            return await self._scope_authority.scope_for_request(
                app_id=app_id,
                auth_session_id=session_id,
            )
        except DocumentAuthorityError as exc:
            raise EngineAttachmentAuthorityError(
                exc.code, exc.safe_message, status_code=exc.status_code
            ) from exc
        except Exception as exc:
            raise EngineAttachmentAuthorityError(
                "attachment_admission_unavailable",
                "Trusted attachment scope could not be resolved.",
                status_code=503,
            ) from exc

    async def admit_payload(self, payload: Any) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error(
                "invalid_request",
                "Request body must be an object.",
                status_code=400,
            )
        data = dict(payload)
        unknown = set(data) - _ALLOWED
        if unknown:
            return _service_error(
                "invalid_request",
                "Admission request contains unsupported fields.",
                status_code=400,
            )
        if _REQUIRED - set(data):
            return _service_error(
                "invalid_request",
                "Admission request is missing required fields.",
                status_code=400,
            )

        app_id = data["app_id"]
        session_id = data["session_id"]
        media_type = data["media_type"]
        image_base64 = data["image_base64"]
        trace_id = data.get("trace_id")
        for value, name in (
            (app_id, "app_id"),
            (session_id, "session_id"),
            (media_type, "media_type"),
            (image_base64, "image_base64"),
        ):
            if not isinstance(value, str):
                return _service_error(
                    "invalid_request",
                    f"Admission request field {name} is invalid.",
                    status_code=400,
                )
        if trace_id is not None and not isinstance(trace_id, str):
            return _service_error(
                "invalid_request",
                "Admission request field trace_id is invalid.",
                status_code=400,
            )

        if len(image_base64) > MAX_STORED_IMAGE_BASE64_CHARS:
            return _service_error(
                "attachment_too_large",
                _bounded_b64_chars(),
                status_code=413,
            )
        try:
            decoded = base64.b64decode(image_base64.encode("ascii"), validate=True)
        except (binascii.Error, ValueError, UnicodeEncodeError):
            return _service_error(
                "invalid_attachment_base64",
                "Image attachment payload is not valid base64.",
                status_code=400,
            )

        try:
            scope = await self._scope_for(app_id=app_id, session_id=session_id)
            record: StoredImageRecord = await self._image_byte_store.admit_image(
                data=decoded,
                media_type=media_type,
                app_id=scope.app_id,
                tenant_id=scope.tenant_id,
                subject_id=scope.subject_id,
            )
        except EngineAttachmentAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except ImageByteStoreError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "attachment": {
                    "attachment_ref": record.attachment_ref,
                    "media_type": record.media_type,
                    "byte_size": record.byte_size,
                    "expires_at": (
                        record.expires_at.isoformat()
                        if record.expires_at is not None
                        else None
                    ),
                },
            },
        )

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != ATTACHMENT_ADMISSION_PATH:
            return _service_error(
                "not_found", "Internal Engine route not found.", status_code=404
            )
        if normalized_method != "POST":
            return _service_error(
                "method_not_allowed", "Method not allowed.", status_code=405
            )
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                status_code=415,
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error(
                "invalid_request", "Request body is invalid.", status_code=400
            )
        raw = bytes(body)
        if len(raw) > MAX_ADMISSION_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large",
                "Request body exceeds the internal Engine safety limit.",
                status_code=413,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json",
                "Request body must contain valid UTF-8 JSON.",
                status_code=400,
            )
        return await self.admit_payload(payload)
