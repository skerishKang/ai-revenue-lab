"""Optional B62 Worker composition for the Engine-owned orchestration client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from padiem_ai_engine_client import (
    ENGINE_HEALTH_PATH,
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
    ENGINE_ORCHESTRATE_CANCEL_PATH,
    ENGINE_ORCHESTRATE_PATH,
    ENGINE_ORCHESTRATE_STREAM_PATH,
    ENGINE_ORCHESTRATE_RESUME_PATH,
    EngineTransportResponse,
    EngineStreamTransportResponse,
    PadiemAiEngineClient,
)
from padiem_ai_core.b14_multimodal import MAX_B14_IMAGE_BYTES

from .canonical_orchestration_bridge import CanonicalSubjectB62EngineOrchestrationBridge
from .orchestration_bridge import B62EngineOrchestrationBridge, D1OrchestrationStateStore
from .service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
    read_bounded_service_binding_body,
    cloudflare_chunk_bytes,
)
from .worker_config import binding_value

ENGINE_SERVICE_BINDING_NAME = "ENGINE_SERVICE"
ORCHESTRATION_ENABLED_ENV = "PADIEM_CHAT_ORCHESTRATION_ENABLED"
ENGINE_CALLER_ID_ENV = "PADIEM_CHAT_ENGINE_CALLER_ID"
ENGINE_CALLER_SECRET_ENV = "PADIEM_CHAT_ENGINE_CALLER_SECRET"
_MAX_ENGINE_RESPONSE_BYTES = 1_048_576
# Text/reference routes keep the original 256 KiB request bound. The canonical
# multimodal admission route (#3210) carries one bounded base64 image, so it
# gets its own bound derived from the same core constant the Engine store uses.
_MAX_ENGINE_REQUEST_BYTES = 256 * 1024
_MAX_ATTACHMENT_BASE64_CHARS = ((MAX_B14_IMAGE_BYTES + 2) // 3) * 4 + 4
_MAX_ATTACHMENT_REQUEST_BYTES = _MAX_ATTACHMENT_BASE64_CHARS + (8 * 1024)
_ALLOWED_ENGINE_PATHS = frozenset(
    {
        ENGINE_HEALTH_PATH,
        ENGINE_ORCHESTRATE_PATH,
        ENGINE_ORCHESTRATE_RESUME_PATH,
        ENGINE_ORCHESTRATE_CANCEL_PATH,
        ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
    }
)


def _server_text(env: Any, name: str) -> str:
    value = binding_value(env, name)
    return value.strip() if isinstance(value, str) else ""


class CloudflareEngineServiceTransport:
    """Route Engine-owned client requests through one fixed Service Binding."""

    def __init__(self, binding: Any, *, request_factory: Any) -> None:
        if binding is None or not callable(request_factory):
            raise ValueError("Engine service binding and request factory are required")
        self._binding = binding
        self._request_factory = request_factory

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineTransportResponse:
        parsed = urlparse(url)
        expected = urlparse(ENGINE_INTERNAL_ORIGIN)
        normalized_method = method.upper() if isinstance(method, str) else ""
        if (
            parsed.scheme != expected.scheme
            or parsed.netloc != expected.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path not in _ALLOWED_ENGINE_PATHS
            or normalized_method not in {"GET", "POST"}
            or (parsed.path == ENGINE_HEALTH_PATH and normalized_method != "GET")
            or (parsed.path != ENGINE_HEALTH_PATH and normalized_method != "POST")
        ):
            raise ValueError("Engine client requested an unsupported internal target")
        if body is not None:
            body_limit = (
                _MAX_ATTACHMENT_REQUEST_BYTES
                if parsed.path == ENGINE_MULTIMODAL_ATTACHMENTS_PATH
                else _MAX_ENGINE_REQUEST_BYTES
            )
            if len(body) > body_limit:
                raise ValueError("Engine request exceeded the B62 transport safety limit")
        body_text = None
        if body is not None:
            try:
                body_text = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Engine request body must be UTF-8 JSON") from exc
        request = self._request_factory(
            url,
            method=normalized_method,
            headers=dict(headers),
            body=body_text,
        )
        response = await self._binding.fetch(request.js_object)
        try:
            encoded = await read_bounded_service_binding_body(
                response,
                max_bytes=_MAX_ENGINE_RESPONSE_BYTES,
            )
        except ServiceBindingResponseTooLarge:
            raise ValueError(
                "Engine response exceeded the B62 transport safety limit"
            ) from None
        except ServiceBindingResponseError as exc:
            raise ValueError("Engine response could not be read safely") from exc
        response_headers: dict[str, str] = {}
        try:
            content_type = response.headers.get("content-type")
        except Exception:
            content_type = None
        if content_type is not None:
            response_headers["content-type"] = str(content_type)
        return EngineTransportResponse(
            status=int(response.status),
            body=encoded,
            headers=response_headers,
        )


    async def stream_request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineStreamTransportResponse:
        """Narrow, opt-in NDJSON Engine stream over the existing Service Binding.

        Unlike request(), this never buffers the entire response. The HTTP
        target is fixed and size/cancel guards stay active while iterating.
        Existing completed Engine requests cannot silently select this route.
        """
        parsed = urlparse(url)
        expected = urlparse(ENGINE_INTERNAL_ORIGIN)
        if (
            parsed.scheme != expected.scheme
            or parsed.netloc != expected.netloc
            or parsed.path != ENGINE_ORCHESTRATE_STREAM_PATH
            or parsed.query or parsed.fragment
            or method != "POST"
            or body is None
            or not isinstance(body, bytes)
            or len(body) > _MAX_ENGINE_REQUEST_BYTES
        ):
            raise ValueError("Engine stream target or request is unsupported")
        try:
            payload = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Engine stream request must be UTF-8 JSON") from exc
        request = self._request_factory(
            url, method="POST", headers=dict(headers), body=payload,
        )
        response = await self._binding.fetch(request.js_object)
        stream = getattr(response, "body", None)
        get_reader = getattr(stream, "getReader", None)
        if not callable(get_reader):
            # Fail closed. Never fall back to buffered body()/text() and
            # misrepresent an already-completed answer as a live stream.
            raise ServiceBindingResponseError("Engine stream body is unavailable")

        async def iter_chunks():
            try:
                reader = get_reader()
            except Exception as exc:
                raise ServiceBindingResponseError("Engine stream reader unavailable") from exc
            finished = False
            received = 0
            try:
                while True:
                    result = await reader.read()
                    if bool(getattr(result, "done", False)):
                        finished = True
                        return
                    chunk = cloudflare_chunk_bytes(getattr(result, "value", None))
                    received += len(chunk)
                    if received > _MAX_ENGINE_RESPONSE_BYTES:
                        raise ServiceBindingResponseTooLarge("Engine stream exceeded bound")
                    if chunk:
                        yield chunk
            finally:
                if not finished:
                    cancel = getattr(reader, "cancel", None)
                    if callable(cancel):
                        try:
                            await cancel()
                        except Exception:
                            pass
                release = getattr(reader, "releaseLock", None)
                if callable(release):
                    try:
                        release()
                    except Exception:
                        pass

        content_type = response.headers.get("content-type")
        return EngineStreamTransportResponse(
            status=int(response.status),
            chunks=iter_chunks(),
            headers={"content-type": str(content_type or "")},
        )


def build_orchestration_bridge(
    env: Any,
    *,
    settings: Any,
    db_binding: Any,
    request_factory: Any,
    canonical_subject_resolver: Any | None = None,
) -> B62EngineOrchestrationBridge | None:
    """Fail closed unless every server-owned activation prerequisite is present.

    Supplying a canonical subject resolver opts this source composition into the
    #1228 Control Plane identity path. Ordinary Worker composition currently does
    not supply one, so Production behavior is unchanged until separately activated.
    """
    if _server_text(env, ORCHESTRATION_ENABLED_ENV).lower() != "true":
        return None
    if getattr(settings, "runtime_mode", "mock") != "b14":
        return None
    engine_binding = binding_value(env, ENGINE_SERVICE_BINDING_NAME)
    caller_id = _server_text(env, ENGINE_CALLER_ID_ENV)
    caller_secret = _server_text(env, ENGINE_CALLER_SECRET_ENV)
    if engine_binding is None or db_binding is None or not caller_id or not caller_secret:
        return None
    try:
        client = PadiemAiEngineClient(
            transport=CloudflareEngineServiceTransport(
                engine_binding,
                request_factory=request_factory,
            ),
            app_id="padiem-chat",
            caller_id=caller_id,
            credential=caller_secret,
        )
    except (TypeError, ValueError):
        return None
    store = D1OrchestrationStateStore(db_binding)
    if canonical_subject_resolver is not None:
        return CanonicalSubjectB62EngineOrchestrationBridge(
            client=client,
            store=store,
            canonical_subject_resolver=canonical_subject_resolver,
        )
    return B62EngineOrchestrationBridge(client=client, store=store)
