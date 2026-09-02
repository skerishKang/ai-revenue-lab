"""B62 Worker composition with optional Engine orchestration bridge.

This entrypoint preserves the existing Worker initialization and ordinary B14
chat path. Orchestration is instantiated only when an explicit server-side flag,
Engine Service Binding, caller credential and D1 store are all present.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from workers import Request, Response

import worker as legacy_worker
from app.orchestration_bridge import B62EngineOrchestrationBridge, D1OrchestrationStateStore
from app.orchestration_routes import install_orchestration_routes
from padiem_ai_engine_client import (
    ENGINE_HEALTH_PATH,
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_ORCHESTRATE_CANCEL_PATH,
    ENGINE_ORCHESTRATE_PATH,
    ENGINE_ORCHESTRATE_RESUME_PATH,
    EngineTransportResponse,
    PadiemAiEngineClient,
)

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
    value = legacy_worker.binding_value(env, name)
    return value.strip() if isinstance(value, str) else ""


def _enabled(env: Any) -> bool:
    return _server_text(env, ORCHESTRATION_ENABLED_ENV).lower() == "true"


class CloudflareEngineServiceTransport:
    """Engine-owned client transport over one fixed Cloudflare Service Binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("Engine service binding is required")
        self._binding = binding

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
        request = Request(
            url,
            method=normalized_method,
            headers=dict(headers),
            body=body_text,
        )
        response = await self._binding.fetch(request.js_object)
        text = str(await response.text())
        encoded = text.encode("utf-8")
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


def _orchestration_bridge_for_env(
    env: Any,
    *,
    settings: Any,
    db_binding: Any,
) -> B62EngineOrchestrationBridge | None:
    # Source-complete but fail-closed by default. Production activation requires
    # a separate owner-approved config/deploy change.
    if not _enabled(env) or getattr(settings, "runtime_mode", "mock") != "b14":
        return None
    engine_binding = legacy_worker.binding_value(env, ENGINE_SERVICE_BINDING_NAME)
    caller_id = _server_text(env, ENGINE_CALLER_ID_ENV)
    caller_secret = _server_text(env, ENGINE_CALLER_SECRET_ENV)
    if engine_binding is None or db_binding is None or not caller_id or not caller_secret:
        return None
    try:
        client = PadiemAiEngineClient(
            transport=CloudflareEngineServiceTransport(engine_binding),
            app_id="padiem-chat",
            caller_id=caller_id,
            credential=caller_secret,
        )
    except (TypeError, ValueError):
        return None
    return B62EngineOrchestrationBridge(
        client=client,
        store=D1OrchestrationStateStore(db_binding),
    )


def _build_app(env: Any) -> Any:
    settings = legacy_worker.apply_live_deadman_switch(
        legacy_worker.settings_from_worker_bindings(env)
    )
    db_binding = legacy_worker.binding_value(env, legacy_worker.D1_BINDING_NAME)
    b14_binding = legacy_worker.binding_value(env, legacy_worker.B14_SERVICE_BINDING_NAME)
    history_store = legacy_worker.D1HistoryStore(db_binding) if db_binding is not None else None
    project_file_store = legacy_worker.D1ProjectFileStore(db_binding) if db_binding is not None else None
    saved_output_store = legacy_worker.D1SavedOutputStore(db_binding) if db_binding is not None else None
    base_usage_store = legacy_worker.D1UsageCounterStore(db_binding) if db_binding is not None else None
    usage_store = (
        legacy_worker.DispatchAwareUsageCounterStore(base_usage_store)
        if base_usage_store is not None
        else None
    )
    service_transport = (
        legacy_worker.CloudflareB14ServiceTransport(b14_binding)
        if b14_binding is not None
        else None
    )
    stream_transport = (
        legacy_worker.CloudflareB14StreamingServiceTransport(b14_binding)
        if b14_binding is not None
        else None
    )

    app = legacy_worker.create_app(settings=settings, history_store=history_store)
    app.state.project_file_store = project_file_store
    app.state.saved_output_store = saved_output_store
    app.state.usage_gate = legacy_worker.UsageGate(settings, usage_store)
    app.state.usage_gate_enforced = True
    app.state.b14_client = legacy_worker.DispatchAwareB14Client(
        settings,
        service_transport=service_transport,
        stream_transport=stream_transport,
        require_service_binding=settings.runtime_mode == "b14",
    )
    app.state.grounded_chat = legacy_worker.GroundedChatService(
        app.state.b14_client,
        app.state.web_provider,
    )
    app.state.b14_service_bound = b14_binding is not None
    install_orchestration_routes(
        app,
        _orchestration_bridge_for_env(env, settings=settings, db_binding=db_binding),
    )
    return app


class Default(legacy_worker.Default):
    async def fetch(self, request: Any) -> Any:
        if legacy_worker._worker_app is None:
            try:
                legacy_worker._worker_app = _build_app(self.env)
            except legacy_worker.ConfigError:
                path = urlparse(request.url).path
                response = Response(
                    "Padiem Chat runtime configuration is invalid.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                return legacy_worker._apply_headers(response, path)
        return await super().fetch(request)
