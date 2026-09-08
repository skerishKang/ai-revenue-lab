"""Trusted document context Engine route for #1750 E5B-S4.

The wire carries one opaque server-issued ``att_*`` reference and nothing
else: application/subject/tenant scope is never a request field. A trusted,
deployment-owned scope authority resolves the authenticated first-party
caller into a server-minted ``TrustedCallerScope``; the S2 resolver and the
S3 context/evidence bridge then run the accepted through-line. Response is
the bounded ``ContextWindowProjection`` view plus the engine-minted
evidence id — never document body text beyond the bounded preview, never a
``DocumentLocator``, storage locator, raw ``att_*`` reference or scope triple.

Like E5A this is source wiring only: every trusted port is optional at
construction and the route fails closed until a later Production activation
gate injects the real resolver and durable evidence storage
(``EVIDENCE_RETENTION = IN_MEMORY_SEAM_ONLY``). Absent ports are never
substituted by request data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Protocol

from padiem_ai_core.document_semantics import DocumentNormalizationError

from app.context_evidence_bridge import att_to_context_evidence
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceResponse,
    _service_error,
)
from app.trusted_document_resolver import (
    DocumentResolutionError,
    TrustedDocumentResolver,
)

DOCUMENT_CONTEXT_PATH = "/internal/v1/document/context"

# Reference-only wire: scope identifiers, agent/message payloads, inline
# bytes, paths and storage coordinates are not accepted by this route.
_REQUIRED_FIELDS = frozenset({"document_ref"})

_MAX_IDENTIFIER_CHARS = 256
_MAX_AUTHORITY_ERROR_CODE_CHARS = 64


class DocumentAuthorityError(ValueError):
    """Fail-closed trust-authority error safe for first-party products."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 403) -> None:
        super().__init__(safe_message)
        if (
            not isinstance(code, str)
            or not code
            or len(code) > _MAX_AUTHORITY_ERROR_CODE_CHARS
        ):
            raise ValueError("document authority error code must be a bounded token")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TrustedCallerScope:
    """Server-minted scope triple for one authenticated Engine caller.

    Values come only from the trusted identity/session context behind
    ``TrustedCallerScopeAuthority`` — never from request wire content. The S2
    resolver independently re-validates every field and enforces an exact
    match against the stored document's own scope.
    """

    app_id: str
    subject_id: str
    tenant_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("app_id", self.app_id),
            ("subject_id", self.subject_id),
            ("tenant_id", self.tenant_id),
        ):
            if (
                not isinstance(value, str)
                or not value
                or len(value) > _MAX_IDENTIFIER_CHARS
                or any(character.isspace() for character in value)
            ):
                raise DocumentAuthorityError(
                    "invalid_trusted_scope",
                    "Trusted caller scope is invalid.",
                    status_code=503,
                )


class TrustedCallerScopeAuthority(Protocol):
    """Deployment-owned authority binding wire credentials to server scope.

    Implementations perform the actual first-party credential verification
    against the caller registry and map the authenticated session identity to
    the scope triple that owns the requested documents. A caller cannot
    influence the returned scope through request content.
    """

    def scope_for_caller(
        self, *, caller_id: str, credential: str
    ) -> TrustedCallerScope: ...


class DocumentContextEngineService:
    """Thin Engine boundary over the trusted S2/S3 document through-line."""

    def __init__(
        self,
        *,
        scope_authority: TrustedCallerScopeAuthority | None = None,
        document_resolver: TrustedDocumentResolver | None = None,
        evidence_storage: object | None = None,
    ) -> None:
        if scope_authority is not None and not callable(
            getattr(scope_authority, "scope_for_caller", None)
        ):
            raise ValueError("scope_authority must expose scope_for_caller")
        if document_resolver is not None and not callable(
            getattr(document_resolver, "resolve", None)
        ):
            raise ValueError("document_resolver must expose resolve")
        if evidence_storage is not None and not callable(
            getattr(evidence_storage, "store", None)
        ):
            raise ValueError("evidence_storage must expose store")
        self._scope_authority = scope_authority
        self._document_resolver = document_resolver
        self._evidence_storage = evidence_storage

    @staticmethod
    def _authenticate(
        caller_id: object, credential: object
    ) -> tuple[str, str] | ServiceResponse:
        if (
            not isinstance(caller_id, str)
            or not caller_id.strip()
            or not isinstance(credential, str)
            or not credential
        ):
            return _service_error(
                "service_authentication_failed",
                "Engine caller authentication failed.",
                status_code=401,
            )
        return caller_id.strip(), credential

    async def execute_document_context(
        self, payload: object, *, caller_id: str, credential: str
    ) -> ServiceResponse:
        if not isinstance(payload, Mapping):
            return _service_error(
                "invalid_request", "Request body must be an object.", status_code=400
            )
        data = dict(payload)
        unknown = set(data) - _REQUIRED_FIELDS
        if unknown:
            return _service_error(
                "invalid_request",
                "Document context request contains unsupported fields.",
                status_code=400,
            )
        if _REQUIRED_FIELDS - set(data):
            return _service_error(
                "invalid_request",
                "Document context request is missing required fields.",
                status_code=400,
            )
        if self._scope_authority is None:
            return _service_error(
                "document_authority_unavailable",
                "Trusted document scope authority is unavailable.",
                status_code=503,
            )
        if self._document_resolver is None:
            return _service_error(
                "document_resolver_unavailable",
                "Trusted document resolver is unavailable.",
                status_code=503,
            )
        if self._evidence_storage is None:
            return _service_error(
                "evidence_storage_unavailable",
                "Evidence retention storage is unavailable.",
                status_code=503,
            )

        try:
            scope = self._scope_authority.scope_for_caller(
                caller_id=caller_id, credential=credential
            )
        except DocumentAuthorityError as exc:
            return _service_error(
                exc.code, exc.safe_message, status_code=exc.status_code
            )
        except Exception:
            # The authority is trusted code; a failure there must not reflect
            # session internals to the wire.
            return _service_error(
                "document_authority_unavailable",
                "Trusted document scope authority failed.",
                status_code=503,
            )
        if not isinstance(scope, TrustedCallerScope):
            return _service_error(
                "document_authority_unavailable",
                "Trusted document scope authority returned an invalid scope.",
                status_code=503,
            )

        try:
            context_projection, evidence_projection = att_to_context_evidence(
                self._document_resolver,
                data["document_ref"],
                app_id=scope.app_id,
                subject_id=scope.subject_id,
                tenant_id=scope.tenant_id,
                evidence_storage=self._evidence_storage,
            )
        except DocumentResolutionError as exc:
            return _service_error(
                exc.code, exc.safe_message, status_code=exc.status_code
            )
        except DocumentNormalizationError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=400)
        except Exception:
            return _service_error(
                "document_context_failed",
                "Document context resolution failed.",
                status_code=500,
            )

        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "document": context_projection.to_dict(),
                "evidence": {"evidence_id": evidence_projection.evidence_id},
            },
        )

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
        caller_id: str = "",
        credential: str = "",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != DOCUMENT_CONTEXT_PATH:
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
        auth = self._authenticate(caller_id, credential)
        if isinstance(auth, ServiceResponse):
            return auth
        authenticated_caller_id, authenticated_credential = auth
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error(
                "invalid_request", "Request body is invalid.", status_code=400
            )
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
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
        return await self.execute_document_context(
            payload,
            caller_id=authenticated_caller_id,
            credential=authenticated_credential,
        )
