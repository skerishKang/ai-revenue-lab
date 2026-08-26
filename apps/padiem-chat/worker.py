"""Cloudflare Python Worker entrypoint for Padiem Chat (Business 62).

The deployed Starlette application is built from Cloudflare Worker bindings,
not from browser input and not from stale import-time process environment.
Provider/model execution remains Business 14 authority.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from workers import Request, Response, WorkerEntrypoint

from app.config import ConfigError
from app.dispatch_quota import DispatchAwareB14Client, DispatchAwareUsageCounterStore
from app.grounding import GroundedChatService
from app.history import D1HistoryStore
from app.main import create_app
from app.project_files import D1ProjectFileStore
from app.saved_outputs import D1SavedOutputStore
from app.usage_gate import D1UsageCounterStore, UsageGate
from app.worker_config import (
    B14_SERVICE_BINDING_NAME,
    D1_BINDING_NAME,
    apply_live_deadman_switch,
    binding_value,
    response_headers_for_path,
    settings_from_worker_bindings,
)

_worker_app = None


def _apply_headers(response: Any, path: str) -> Any:
    for name, value in response_headers_for_path(path).items():
        response.headers[name] = value
    return response


class CloudflareB14ServiceTransport:
    """HTTP-shaped adapter over a Cloudflare Worker Service Binding.

    Routing authority is the fixed `B14_SERVICE` binding. The URL is still fully
    qualified because the Fetcher API expects an absolute URL, but service-binding
    configuration — not the hostname — selects the target Worker.
    """

    def __init__(self, binding: Any):
        if binding is None:
            raise ValueError("B14 service binding is required")
        self.binding = binding

    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, bytes]:
        request = Request(
            url,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False),
        )
        response = await self.binding.fetch(request.js_object)
        text = await response.text()
        return int(response.status), str(text).encode("utf-8")


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
                _worker_app = create_app(settings=settings, history_store=history_store)
                _worker_app.state.project_file_store = project_file_store
                _worker_app.state.saved_output_store = saved_output_store
                _worker_app.state.usage_gate = UsageGate(settings, usage_store)
                _worker_app.state.usage_gate_enforced = True
                _worker_app.state.b14_client = DispatchAwareB14Client(
                    settings,
                    service_transport=service_transport,
                    require_service_binding=settings.runtime_mode == "b14",
                )
                _worker_app.state.grounded_chat = GroundedChatService(
                    _worker_app.state.b14_client,
                    _worker_app.state.web_provider,
                )
                _worker_app.state.b14_service_bound = b14_binding is not None
            except ConfigError:
                response = Response(
                    "Padiem Chat runtime configuration is invalid.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                return _apply_headers(response, path)

        response = await asgi.fetch(_worker_app, request.js_object, self.env)
        return _apply_headers(response, path)
