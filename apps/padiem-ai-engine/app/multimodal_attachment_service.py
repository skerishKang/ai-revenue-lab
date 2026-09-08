"""Trusted one-image multimodal Engine projection for #1750 E5A.

The caller supplies an opaque server-issued attachment reference plus ordinary
text execution intent. Core's existing ``MultimodalExecutionRequest`` /
``MultimodalExecutionRuntime`` remain the sole image/media/model execution
authority.

#2182 S5 replaces the injected resolver object with the two real authority
inputs, so the resolver is never a caller-supplied object:

* ``image_byte_store`` is the deployment-owned scoped byte store behind the
  Engine D1 image-store binding;
* ``scope_authority`` mints the per-request ``TrustedCallerScope`` triple from
  the resolved Control Plane auth session (``app_id`` plus the request's opaque
  ``session_id`` only; raw tenant/subject assertions are never read).

A ``ByteStoreTrustedAttachmentResolver`` is then constructed **per request**
bound to that single trusted scope, on both the execute and stream paths. When
either authority input is absent the route fails closed exactly as before.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
import json
from typing import Any

from padiem_ai_core.execution_runtime import ExecutionResult, ExecutionRuntimeError
from padiem_ai_core.multimodal_execution_runtime import MultimodalExecutionRequest
from padiem_ai_core.streaming_runtime import StreamingExecutionEvent

from app.attachment_authority import (
    EngineAttachmentAuthorityError,
    TrustedImageAttachment,
    require_opaque_attachment_ref,
)
from app.attachment_resolver import ByteStoreTrustedAttachmentResolver
from app.auth_session_scope_authority import AuthSessionScopeAuthority
from app.document_context_service import DocumentAuthorityError
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceContractError,
    ServiceResponse,
    _service_error,
    _status_for_runtime_error,
    build_execution_request,
)
from app.streaming_service import PreparedStream, StreamingEngineService

MULTIMODAL_EXECUTE_PATH = "/internal/v1/multimodal/execute"
MULTIMODAL_STREAM_PATH = "/internal/v1/multimodal/stream"

# E5A is deliberately reference-only. Inline bytes/data URLs, paths, storage
# endpoints and remote URLs are not accepted by this wire.
_REQUIRED = frozenset({"app_id", "agent", "messages", "attachment_ref"})
_ALLOWED = _REQUIRED | frozenset(
    {"session_id", "additional_system_context", "trace_id"}
)


class MultimodalAttachmentEngineService:
    """Thin Engine boundary over trusted attachment resolution + Core runtime."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[str], Any],
        image_byte_store: Any | None = None,
        scope_authority: AuthSessionScopeAuthority | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if image_byte_store is not None and not callable(
            getattr(image_byte_store, "fetch_image", None)
        ):
            raise ValueError("image_byte_store must expose async fetch_image")
        if scope_authority is not None and not callable(
            getattr(scope_authority, "scope_for_request", None)
        ):
            raise ValueError("scope_authority must expose async scope_for_request")
        self._runtime_factory = runtime_factory
        self._image_byte_store = image_byte_store
        self._scope_authority = scope_authority

    async def _resolver(
        self, *, app_id: str, auth_session_id: str | None
    ) -> ByteStoreTrustedAttachmentResolver:
        """Build one request-bound resolver over one server-minted scope."""

        if self._image_byte_store is None or self._scope_authority is None:
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment resolver is unavailable.",
                status_code=503,
            )
        if not auth_session_id:
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment scope requires an authenticated session.",
                status_code=503,
            )
        try:
            scope = await self._scope_authority.scope_for_request(
                app_id=app_id,
                auth_session_id=auth_session_id,
            )
        except DocumentAuthorityError as exc:
            raise EngineAttachmentAuthorityError(
                exc.code, exc.safe_message, status_code=exc.status_code
            ) from exc
        except Exception as exc:
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment scope could not be resolved.",
                status_code=503,
            ) from exc
        return ByteStoreTrustedAttachmentResolver(
            store=self._image_byte_store,
            scope=scope,
        )

    async def _resolve(
        self,
        *,
        app_id: str,
        auth_session_id: str | None,
        attachment_ref: str,
    ) -> TrustedImageAttachment:
        resolver = await self._resolver(app_id=app_id, auth_session_id=auth_session_id)
        try:
            resolved = await resolver.resolve_image(
                app_id=app_id,
                attachment_ref=attachment_ref,
            )
        except EngineAttachmentAuthorityError:
            raise
        except Exception as exc:
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment resolution failed.",
                status_code=503,
            ) from exc
        if not isinstance(resolved, TrustedImageAttachment):
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment resolver returned an invalid result.",
                status_code=503,
            )
        if resolved.attachment_ref != attachment_ref or resolved.app_id != app_id:
            raise EngineAttachmentAuthorityError(
                "attachment_scope_mismatch",
                "Attachment is not authorized for this application scope.",
                status_code=403,
            )
        if resolved.expired:
            raise EngineAttachmentAuthorityError(
                "attachment_expired",
                "Attachment reference has expired.",
                status_code=410,
            )
        return resolved

    @staticmethod
    def _multimodal_messages(
        messages: tuple[Mapping[str, str], ...],
        attachment: TrustedImageAttachment,
    ) -> tuple[Mapping[str, Any], ...]:
        target = -1
        for index in range(len(messages) - 1, -1, -1):
            if messages[index]["role"] == "user":
                target = index
                break
        if target < 0:
            raise ServiceContractError(
                "invalid_request",
                "Multimodal execution requires a user message.",
            )

        data_url = (
            f"data:{attachment.media_type};base64,"
            + base64.b64encode(attachment.data).decode("ascii")
        )
        projected: list[Mapping[str, Any]] = []
        for index, message in enumerate(messages):
            if index != target:
                projected.append(
                    {"role": message["role"], "content": message["content"]}
                )
                continue
            projected.append(
                {
                    "role": "user",
                    "content": (
                        {"type": "text", "text": message["content"]},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ),
                }
            )
        return tuple(projected)

    async def execute_payload(self, payload: Any) -> ServiceResponse:
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
                "Multimodal request contains unsupported fields.",
                status_code=400,
            )
        if _REQUIRED - set(data):
            return _service_error(
                "invalid_request",
                "Multimodal request is missing required fields.",
                status_code=400,
            )

        try:
            attachment_ref = require_opaque_attachment_ref(data.get("attachment_ref"))
            base_payload = {
                key: value for key, value in data.items() if key != "attachment_ref"
            }
            app_id, text_request, _ = build_execution_request(base_payload)
            attachment = await self._resolve(
                app_id=app_id,
                auth_session_id=text_request.session_id,
                attachment_ref=attachment_ref,
            )
            request = MultimodalExecutionRequest(
                agent=text_request.agent,
                messages=self._multimodal_messages(text_request.messages, attachment),
                session_id=text_request.session_id,
                additional_system_context=text_request.additional_system_context,
                trace_id=text_request.trace_id,
            )
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineAttachmentAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except (TypeError, ValueError, OverflowError):
            # Core owns media/data-url/magic validation. Do not reflect parser
            # internals, raw bytes or private resolver state.
            return _service_error(
                "invalid_multimodal_input",
                "Resolved attachment is not valid for bounded multimodal execution.",
                status_code=400,
            )

        try:
            runtime = self._runtime_factory(app_id)
            result = await runtime.run(request)
        except ExecutionRuntimeError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=_status_for_runtime_error(exc),
                retryable=exc.retryable,
                metadata=exc.metadata.to_public_dict(),
            )
        except Exception:
            return _service_error(
                "engine_internal_error",
                "Multimodal execution failed.",
                status_code=500,
            )

        if not isinstance(result, ExecutionResult):
            return _service_error(
                "invalid_execution_result",
                "Multimodal execution returned an invalid result.",
                status_code=500,
            )
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "answer": result.answer,
                "route": result.route.to_public_dict(),
                "metadata": result.metadata.to_public_dict(),
                "attachment": attachment.to_public_dict(),
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
        if path != MULTIMODAL_EXECUTE_PATH:
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
        return await self.execute_payload(payload)


class MultimodalStreamingEngineService(MultimodalAttachmentEngineService):
    """Reference-only multimodal input adapter over the shared stream service."""

    def __init__(self, *, runtime_factory: Callable[[str], Any], image_byte_store: Any | None = None, scope_authority: AuthSessionScopeAuthority | None = None) -> None:
        super().__init__(
            runtime_factory=runtime_factory,
            image_byte_store=image_byte_store,
            scope_authority=scope_authority,
        )
        self._streaming = StreamingEngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
        )

    async def prepare(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> PreparedStream | ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != MULTIMODAL_STREAM_PATH:
            return _service_error("not_found", "Internal Engine route not found.", status_code=404)
        if normalized_method != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
            return _service_error("unsupported_media_type", "Content-Type must be application/json.", status_code=415)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return _service_error("request_too_large", "Request body exceeds the internal Engine safety limit.", status_code=413)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error("invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400)
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)

        data = dict(payload)
        unknown = set(data) - _ALLOWED
        if unknown or _REQUIRED - set(data):
            return _service_error("invalid_request", "Multimodal request shape is invalid.", status_code=400)
        try:
            attachment_ref = require_opaque_attachment_ref(data.get("attachment_ref"))
            base_payload = {key: value for key, value in data.items() if key != "attachment_ref"}
            app_id, text_request, context = build_execution_request(base_payload)
            if context is not None:
                return _service_error("invalid_request", "Multimodal streaming does not support execution context.", status_code=400)
            attachment = await self._resolve(
                app_id=app_id,
                auth_session_id=text_request.session_id,
                attachment_ref=attachment_ref,
            )
            request = MultimodalExecutionRequest(
                agent=text_request.agent,
                messages=self._multimodal_messages(text_request.messages, attachment),
                session_id=text_request.session_id,
                additional_system_context=text_request.additional_system_context,
                trace_id=text_request.trace_id,
            )
            runtime = self._runtime_factory(app_id)
            iterator = runtime.stream(request)
            first_event = await anext(iterator)
        except ServiceContractError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except EngineAttachmentAuthorityError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except ExecutionRuntimeError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=_status_for_runtime_error(exc), retryable=exc.retryable, metadata=exc.metadata.to_public_dict())
        except (TypeError, ValueError, OverflowError):
            return _service_error("invalid_multimodal_input", "Multimodal input is not valid for bounded streaming execution.", status_code=400)
        except StopAsyncIteration:
            return _service_error("malformed_upstream", "Model streaming execution ended before producing an event.", status_code=502)
        except Exception:
            return _service_error("engine_internal_error", "Multimodal streaming execution failed.", status_code=500)

        if not isinstance(first_event, StreamingExecutionEvent):
            return _service_error("invalid_stream_event", "Padiem AI Engine returned an invalid streaming event.", status_code=502)
        return PreparedStream(first_event=first_event, iterator=iterator)

    async def iter_ndjson(self, prepared: PreparedStream):
        iterator = self._streaming.iter_ndjson(prepared)
        try:
            async for line in iterator:
                yield line
        finally:
            await iterator.aclose()
