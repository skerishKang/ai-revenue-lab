"""Cloudflare VERSION-PREVIEW-ONLY entrypoint for B62 Issue #1091.

Safety contract:
- never promote this entrypoint to the canonical production Worker;
- only version/alias preview hosts under the known padiem-chat workers.dev name run;
- the real Provider credential remains a Secrets Store binding and is resolved
  only inside the test client;
- the ordinary production ``worker.py`` and B14/Core execution path are untouched.

Upload this config with ``wrangler versions upload`` only. ``wrangler deploy``
with the UX-test config is explicitly forbidden by Issue #1091.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from app.config import Settings
from app.main import create_app
from app.poolside_ux_test import PoolsideUXTestClient, is_version_preview_host
from app.worker_config import binding_value, response_headers_for_path

SECRET_BINDING_NAME = "PADIEM_POOLSIDE_API_KEY"
_worker_app = None


def _apply_headers(response: Any, path: str) -> Any:
    for name, value in response_headers_for_path(path).items():
        response.headers[name] = value
    return response


def _blocked_preview_response(path: str) -> Any:
    response = Response(
        "This B62 real-answer harness is available only on a Cloudflare Worker preview URL.",
        status=403,
        headers={"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
    )
    return _apply_headers(response, path)


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

        global _worker_app
        parsed = urlparse(request.url)
        path = parsed.path

        # This is the final fail-closed guard if the test config is accidentally
        # promoted. The canonical padiem-chat production hostname can never use
        # this direct Provider path.
        if not is_version_preview_host(parsed.hostname):
            return _blocked_preview_response(path)

        if _worker_app is None:
            secret_binding = binding_value(self.env, SECRET_BINDING_NAME)
            if secret_binding is None:
                response = Response(
                    "The bounded real-answer test credential binding is unavailable.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
                )
                return _apply_headers(response, path)

            # Keep the normal B62 Settings object in mock/safe mode so this test
            # cannot be mistaken for a production B14 live activation. Only the
            # explicit client replacement below performs the bounded test call.
            settings = Settings.from_values(
                runtime_mode="mock",
                timeout_seconds="60",
                live_enabled="false",
                web_provider="off",
                auth_mode="off",
            )
            _worker_app = create_app(settings=settings)
            _worker_app.state.b14_client = PoolsideUXTestClient(secret_binding)
            # Grounded/tool execution intentionally remains the create_app mock/off
            # implementation. Issue #1091 authorizes direct Provider execution only
            # for ordinary text + existing text-document reference context.
            _worker_app.state.usage_gate_enforced = False

        response = await asgi.fetch(_worker_app, request.js_object, self.env)
        return _apply_headers(response, path)
