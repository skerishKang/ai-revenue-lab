"""Guarded Cloudflare Python Worker entrypoint for Padiem Chat.

This entrypoint preserves the existing Worker transports and deployment locks,
while forcing public chat requests through ProfileGuard before the Starlette
application can dispatch to Padiem AI Core / Business 14.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from app.config import ConfigError
from app.dispatch_quota import DispatchAwareB14Client, DispatchAwareUsageCounterStore
from app.grounding import GroundedChatService
from app.history import D1HistoryStore
from app.main import create_app
from app.profile_guard import guard_app
from app.project_files import D1ProjectFileStore
from app.saved_outputs import D1SavedOutputStore
from app.usage_gate import D1UsageCounterStore, UsageGate
from app.worker_config import (
    B14_SERVICE_BINDING_NAME,
    D1_BINDING_NAME,
    apply_live_deadman_switch,
    binding_value,
    settings_from_worker_bindings,
)
from worker import (
    CloudflareB14ServiceTransport,
    CloudflareB14StreamingServiceTransport,
    _apply_headers,
)

_worker_app = None


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

        global _worker_app
        path = urlparse(request.url).path

        if _worker_app is None:
            try:
                settings = apply_live_deadman_switch(settings_from_worker_bindings(self.env))
                db_binding = binding_value(self.env, D1_BINDING_NAME)
                b14_binding = binding_value(self.env, B14_SERVICE_BINDING_NAME)
                history_store = D1HistoryStore(db_binding) if db_binding is not None else None
                project_file_store = D1ProjectFileStore(db_binding) if db_binding is not None else None
                saved_output_store = D1SavedOutputStore(db_binding) if db_binding is not None else None
                base_usage_store = D1UsageCounterStore(db_binding) if db_binding is not None else None
                usage_store = (
                    DispatchAwareUsageCounterStore(base_usage_store)
                    if base_usage_store is not None
                    else None
                )
                service_transport = (
                    CloudflareB14ServiceTransport(b14_binding)
                    if b14_binding is not None
                    else None
                )
                stream_transport = (
                    CloudflareB14StreamingServiceTransport(b14_binding)
                    if b14_binding is not None
                    else None
                )

                starlette_app = create_app(settings=settings, history_store=history_store)
                starlette_app.state.project_file_store = project_file_store
                starlette_app.state.saved_output_store = saved_output_store
                starlette_app.state.usage_gate = UsageGate(settings, usage_store)
                starlette_app.state.usage_gate_enforced = True
                starlette_app.state.b14_client = DispatchAwareB14Client(
                    settings,
                    service_transport=service_transport,
                    stream_transport=stream_transport,
                    require_service_binding=settings.runtime_mode == "b14",
                )
                starlette_app.state.grounded_chat = GroundedChatService(
                    starlette_app.state.b14_client,
                    starlette_app.state.web_provider,
                )
                starlette_app.state.b14_service_bound = b14_binding is not None
                _worker_app = guard_app(starlette_app)
            except ConfigError:
                response = Response(
                    "Padiem Chat runtime configuration is invalid.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                return _apply_headers(response, path)

        response = await asgi.fetch(_worker_app, request.js_object, self.env)
        return _apply_headers(response, path)
