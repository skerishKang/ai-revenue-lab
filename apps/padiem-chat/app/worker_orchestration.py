"""Optional B62 Worker composition for the Engine-owned orchestration client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from padiem_ai_engine_client import (
    ENGINE_HEALTH_PATH,
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_ORCHESTRATE_CANCEL_PATH,
    ENGINE_ORCHESTRATE_PATH,
    ENGINE_ORCHESTRATE_RESUME_PATH,
    EngineTransportResponse,
    PadiemAiEngineClient,
)

from .canonical_orchestration_bridge import CanonicalSubjectB62EngineOrchestrationBridge
from .orchestration_bridge import B62EngineOrchestrationBridge, D1OrchestrationStateStore
from .worker_config import binding_value

ENGINE_SERVICE_BINDING_NAME = "ENGINE_SERVICE"
ORCHESTRATION_ENABLED_ENV = "PADIEM_CHAT_ORCHESTRATION_ENABLED"
ENGINE_CALLER_ID_ENV = "PADIEM_CHAT_ENGINE_CALLER_ID"
ENGINE_CALLER_SECRET_ENV = "PADIEM_CHAT_ENGINE_CALLER_SECRET"
_MAX_ENGINE_RESPONSE_BYTES = 1_048_576
_ALLOWED_ENGINE_PATHS = frozenset(
    {
        ENGINE_HEALTH_PATH,
        ENGINE_ORCHESTRATE_PATH,
        ENGINE_ORCHESTRATE_RESUME_PATH,
        ENGINE_ORCHESTRATE_CANCEL_PATH,
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
        if body is not None and len(body) > 256 * 1024:
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
        encoded = str(await response.text()).encode("utf-8")
        if len(encoded) > _MAX_ENGINE_RESPONSE_BYTES:
            raise ValueError("Engine response exceeded the B62 transport safety limit")
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
