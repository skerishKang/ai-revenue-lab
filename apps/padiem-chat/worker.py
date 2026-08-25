"""Cloudflare Python Worker entrypoint for Padiem Chat (Business 62).

The deployed Starlette application is built from Cloudflare Worker bindings,
not from browser input and not from stale import-time process environment.
Provider/model execution remains Business 14 authority.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from app.config import ConfigError
from app.history import D1HistoryStore
from app.main import create_app
from app.worker_config import D1_BINDING_NAME, binding_value, response_headers_for_path, settings_from_worker_bindings

_worker_app = None


def _apply_headers(response: Any, path: str) -> Any:
    for name, value in response_headers_for_path(path).items():
        response.headers[name] = value
    return response


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

        global _worker_app
        path = urlparse(request.url).path

        if _worker_app is None:
            try:
                settings = settings_from_worker_bindings(self.env)
                db_binding = binding_value(self.env, D1_BINDING_NAME)
                history_store = D1HistoryStore(db_binding) if db_binding is not None else None
                _worker_app = create_app(settings=settings, history_store=history_store)
            except ConfigError:
                response = Response(
                    "Padiem Chat runtime configuration is invalid.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                return _apply_headers(response, path)

        response = await asgi.fetch(_worker_app, request.js_object, self.env)
        return _apply_headers(response, path)
