"""Trusted one-image multimodal Engine projection for #1750 E5A.

The caller supplies an opaque server-issued attachment reference plus ordinary
text execution intent. A trusted resolver privately returns image bytes. Core's
existing ``MultimodalExecutionRequest`` / ``MultimodalExecutionRuntime`` remain
the sole image/media/model execution authority.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
import json
from typing import Any

from padiem_ai_core.execution_runtime import ExecutionResult, ExecutionRuntimeError
from padiem_ai_core.multimodal_execution_runtime import MultimodalExecutionRequest

from app.attachment_authority import (
    EngineAttachmentAuthorityError,
    TrustedAttachmentResolver,
    TrustedImageAttachment,
    require_opaque_attachment_ref,
)
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceContractError,
    ServiceResponse,
    _service_error,
    _status_for_runtime_error,
    build_execution_request,
)

MULTIMODAL_EXECUTE_PATH = "/internal/v1/multimodal/execute"

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
        attachment_resolver: TrustedAttachmentResolver | None = None,
    ) -> None:
        if not callable(runtime_factory):
            raise ValueError("runtime_factory must be callable")
        if attachment_resolver is not None and not callable(
            getattr(attachment_resolver, "resolve_image", None)
        ):
            raise ValueError("attachment_resolver must expose async resolve_image")
        self._runtime_factory = runtime_factory
        self._attachment_resolver = attachment_resolver

    async def _resolve(self, *, app_id: str, attachment_ref: str) -> TrustedImageAttachment:
        if self._attachment_resolver is None:
            raise EngineAttachmentAuthorityError(
                "attachment_resolver_unavailable",
                "Trusted attachment resolver is unavailable.",
                status_code=503,
            )
        try:
            resolved = await self._attachment_resolver.resolve_image(
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
