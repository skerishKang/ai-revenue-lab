"""Trusted document-byte admission boundary for Engine E8C-B (#2741).

This is the HTTP admission seam the Engine-owned document byte store was
missing while the document evidence lane kept only resolving references:
callers upload bounded base64 document bytes once and receive only the
server-minted opaque ``doc_*`` reference back. ``ScopedDocumentByteStore.
admit_document`` remains the single size/media/scope/grammar authority;
this module owns exactly the wire boundary and nothing else:

* the authenticated Engine caller is established by the shared
  service-identity boundary in ``worker_identity.py`` before this service
  is ever invoked;
* the tenant/subject scope is minted **only** from the resolved Control
  Plane auth session (``app_id`` plus the request's opaque ``session_id``;
  raw tenant/subject assertions are never read, and unsupported fields
  fail closed — this envelope carries no ``trace_id`` and no expiry,
  retention is a server-minted fact);
* the base64 payload is decoded strictly and bounded before the store
  sees any bytes; the store re-enforces its own per-media ceiling
  independently;
* media truth stays with the Core normalization allowlists via the store;
* one admission is one immutable append-only record; there is no
  client-chosen reference, filename-based locator, expiry or idempotency
  replay surface. A missing ``filename`` is filled with a server-derived
  neutral default, never echoed back raw.

When either authority input is absent the route fails closed 503 with
``document_admission_unavailable``, exactly as the image admission lane
does. Admission writes no model calls and reaches no provider: it is
storage-side source wiring only.

#5881 stage 3 adds the second source shape: an attachment that arrives as a
COM2 ``file_id`` plus its asserted ``sha256`` and Chat's signed read ticket.
The Engine then reads the lane's extracted-text window over the one
deployment-configured ``FILE_LANE_ORIGIN`` and admits that text through the
same ``admit_document`` authority, so the reference reaches the existing
document context path instead of travelling as inline bytes. Only the first
window is mounted; the receipt carries the continuation ``next_offset`` and
the document's ``total_chars`` from the lane's saved count. Without a
configured port the reference shape fails closed 503
``file_lane_unavailable`` and the inline path is untouched.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
import json
from pathlib import PurePath
import re
from typing import Any

from padiem_ai_core.document_normalization import (
    MAX_DOCUMENT_NAME_CHARS,
    BINARY_DOCUMENT_MEDIA,
    TEXT_DOCUMENT_MEDIA,
)

from app.auth_session_scope_authority import AuthSessionScopeAuthority
from app.document_byte_store import (
    DocumentByteStoreError,
    MAX_STORED_DOCUMENT_BASE64_CHARS,
    StoredDocumentRecord,
)
from app.document_context_service import DocumentAuthorityError
from app.file_lane_text_port import FileLaneTextError, FileLaneTextPort
from app.service import ServiceResponse, _service_error

DOCUMENT_ADMISSION_PATH = "/internal/v1/documents"

# Admission-only body ceiling: the canonical base64 payload bound plus headroom
# for the JSON envelope. The shared MAX_REQUEST_BODY_BYTES (1 MiB) is for
# text/reference routes and is far below one admitted document by design.
MAX_DOCUMENT_ADMISSION_REQUEST_BODY_BYTES = MAX_STORED_DOCUMENT_BASE64_CHARS + (8 * 1024)

# Tenant, subject, document_ref, locators and expiry are server-side facts;
# presenting any of them on this wire is a fail-closed request shape error.
# Unlike the image admission wire there is deliberately no trace_id field.
_REQUIRED = frozenset({"app_id", "session_id", "media_type", "document_base64"})
_ALLOWED = _REQUIRED | frozenset({"filename"})

# The COM2 reference shape carries no media type: what the lane returns is
# extracted text, so the Engine states the media itself rather than letting a
# caller pick how those bytes are later parsed.
_LANE_REQUIRED = frozenset({"app_id", "session_id", "file_id", "sha256", "file_ticket"})
_LANE_ALLOWED = _LANE_REQUIRED | frozenset({"filename"})
LANE_DOCUMENT_MEDIA_TYPE = "text/plain"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# Server-derived neutral filename when the caller sends none, built from the
# Core allow-lists themselves (one media truth source, no hand-copied table).
# The *shortest* extension is preferred for determinism (".md" over ".markdown").
_MEDIA_FILENAME_SUFFIX: dict[str, str] = {
    media: min(extensions, key=lambda e: (len(e), e)).lstrip(".")
    for media_map in (TEXT_DOCUMENT_MEDIA, BINARY_DOCUMENT_MEDIA)
    for media, extensions in media_map.items()
}


def _default_filename(media_type: str) -> str:
    suffix = _MEDIA_FILENAME_SUFFIX.get(media_type.strip().lower())
    return f"document.{suffix}" if suffix else "document"


def _filename_is_valid(filename: object) -> bool:
    return (
        isinstance(filename, str)
        and bool(filename.strip())
        and len(filename.strip()) <= MAX_DOCUMENT_NAME_CHARS
        and not _CONTROL_CHARS_RE.search(filename)
    )


def _lane_document_name(filename: object) -> str:
    """The caller's own name carrying the media truth the lane text has.

    The lane answers extracted text whatever the source was, so admitting a
    name still ending ``.pdf`` under ``text/plain`` would break the document
    context path: Core pins one media type per extension and fails closed on
    the mismatch. The stem survives, the suffix follows the admitted bytes.
    """

    if isinstance(filename, str) and filename.strip():
        candidate = f"{PurePath(filename.strip()).stem}.txt"
        if len(candidate) <= MAX_DOCUMENT_NAME_CHARS:
            return candidate
    return _default_filename(LANE_DOCUMENT_MEDIA_TYPE)


def _document_receipt(record: StoredDocumentRecord) -> dict[str, Any]:
    """The bounded four-field receipt every admitted document answers with."""

    return {
        "document_ref": record.document_ref,
        "media_type": record.media_type,
        "byte_size": record.byte_size,
        "expires_at": (
            record.expires_at.isoformat()
            if record.expires_at is not None
            else None
        ),
    }


class DocumentAdmissionAuthorityError(ValueError):
    """Fail-closed document admission authority error, safe for the wire."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("document admission error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


class DocumentAdmissionEngineService:
    """Thin Engine boundary over the canonical scoped document byte store."""

    def __init__(
        self,
        *,
        document_byte_store: Any | None = None,
        scope_authority: AuthSessionScopeAuthority | None = None,
        file_lane_text_port: FileLaneTextPort | None = None,
    ) -> None:
        if document_byte_store is not None and not callable(
            getattr(document_byte_store, "admit_document", None)
        ):
            raise ValueError("document_byte_store must expose async admit_document")
        if scope_authority is not None and not callable(
            getattr(scope_authority, "scope_for_request", None)
        ):
            raise ValueError("scope_authority must expose async scope_for_request")
        if file_lane_text_port is not None and not callable(
            getattr(file_lane_text_port, "read_window", None)
        ):
            raise ValueError("file_lane_text_port must expose async read_window")
        self._document_byte_store = document_byte_store
        self._scope_authority = scope_authority
        self._file_lane_text_port = file_lane_text_port

    async def _scope_for(self, *, app_id: str, session_id: str) -> Any:
        if self._document_byte_store is None or self._scope_authority is None:
            raise DocumentAdmissionAuthorityError(
                "document_admission_unavailable",
                "Trusted document admission authority is unavailable.",
                status_code=503,
            )
        try:
            return await self._scope_authority.scope_for_request(
                app_id=app_id,
                auth_session_id=session_id,
            )
        except DocumentAuthorityError as exc:
            raise DocumentAdmissionAuthorityError(
                exc.code, exc.safe_message, status_code=exc.status_code
            ) from exc
        except Exception as exc:
            raise DocumentAdmissionAuthorityError(
                "document_admission_unavailable",
                "Trusted document scope could not be resolved.",
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
        if "file_id" in data:
            return await self._admit_file_lane_reference(data)
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
        document_base64 = data["document_base64"]
        filename = data.get("filename")
        for value, name in (
            (app_id, "app_id"),
            (session_id, "session_id"),
            (media_type, "media_type"),
            (document_base64, "document_base64"),
        ):
            if not isinstance(value, str):
                return _service_error(
                    "invalid_request",
                    f"Admission request field {name} is invalid.",
                    status_code=400,
                )
        if filename is not None and not _filename_is_valid(filename):
            return _service_error(
                "invalid_request",
                "Admission request field filename is invalid.",
                status_code=400,
            )

        if len(document_base64) > MAX_STORED_DOCUMENT_BASE64_CHARS:
            return _service_error(
                "document_too_large",
                "Document payload exceeds the bounded document base64 size.",
                status_code=413,
            )
        try:
            decoded = base64.b64decode(document_base64.encode("ascii"), validate=True)
        except (binascii.Error, ValueError, UnicodeEncodeError):
            return _service_error(
                "invalid_document_payload",
                "Document payload is not valid base64.",
                status_code=400,
            )

        try:
            scope = await self._scope_for(app_id=app_id, session_id=session_id)
            record: StoredDocumentRecord = await self._document_byte_store.admit_document(
                data=decoded,
                media_type=media_type,
                name=filename.strip() if isinstance(filename, str) else _default_filename(media_type),
                app_id=scope.app_id,
                tenant_id=scope.tenant_id,
                subject_id=scope.subject_id,
            )
        except DocumentAdmissionAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except DocumentByteStoreError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        return ServiceResponse(
            status_code=200,
            body={"ok": True, "document": _document_receipt(record)},
        )

    async def _admit_file_lane_reference(
        self, data: dict[str, Any]
    ) -> ServiceResponse:
        """Admit one COM2 text window: the lane keeps the bytes, Engine the context."""

        unknown = set(data) - _LANE_ALLOWED
        if unknown:
            return _service_error(
                "invalid_request",
                "Admission request contains unsupported fields.",
                status_code=400,
            )
        if _LANE_REQUIRED - set(data):
            return _service_error(
                "invalid_request",
                "Admission request is missing required fields.",
                status_code=400,
            )
        app_id = data["app_id"]
        session_id = data["session_id"]
        for value, name in ((app_id, "app_id"), (session_id, "session_id")):
            if not isinstance(value, str):
                return _service_error(
                    "invalid_request",
                    f"Admission request field {name} is invalid.",
                    status_code=400,
                )
        filename = data.get("filename")
        if filename is not None and not _filename_is_valid(filename):
            return _service_error(
                "invalid_request",
                "Admission request field filename is invalid.",
                status_code=400,
            )
        port = self._file_lane_text_port
        if port is None:
            # No configured origin means no outbound read, ever; the caller
            # retries inline bytes or waits for the deployment to connect it.
            return _service_error(
                "file_lane_unavailable",
                "COM2 file lane origin is not configured.",
                status_code=503,
            )

        try:
            # The session is resolved before any external request leaves the
            # Engine, so an unreadable session never drives a file-lane read.
            scope = await self._scope_for(app_id=app_id, session_id=session_id)
            window = await port.read_window(
                file_id=data["file_id"],
                sha256=data["sha256"],
                ticket=data["file_ticket"],
            )
            record = await self._document_byte_store.admit_document(
                data=window.text.encode("utf-8"),
                media_type=LANE_DOCUMENT_MEDIA_TYPE,
                name=_lane_document_name(filename),
                app_id=scope.app_id,
                tenant_id=scope.tenant_id,
                subject_id=scope.subject_id,
            )
        except DocumentAdmissionAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except DocumentByteStoreError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except FileLaneTextError as exc:
            if exc.status_code == 400:
                # A malformed reference/ticket is the same wire error the inline
                # shape answers with; the route keeps one error taxonomy.
                return _service_error(
                    "invalid_request",
                    "Admission request field file reference is invalid.",
                    status_code=400,
                )
            return _service_error(
                exc.code,
                "Document text could not be read from the COM2 file lane.",
                status_code=exc.status_code,
            )

        document = _document_receipt(record)
        document["total_chars"] = window.total_chars
        document["next_offset"] = window.next_offset
        document["window_eof"] = window.eof
        return ServiceResponse(status_code=200, body={"ok": True, "document": document})

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != DOCUMENT_ADMISSION_PATH:
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
        if len(raw) > MAX_DOCUMENT_ADMISSION_REQUEST_BODY_BYTES:
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
