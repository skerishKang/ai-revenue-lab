"""TEST-ONLY direct Poolside entrypoint for B62-1090-010.

Safety contract:
- canonical traffic is allowed only for the exact server-side test guard;
- ordinary Production traffic remains on the original Worker at 100%;
- the real Provider credential remains a Secrets Store binding and is resolved
  only inside the test client;
- the ordinary production ``worker.py`` and B14/Core execution path are untouched.

Upload this config with ``wrangler versions upload`` only. Never run
``wrangler deploy`` with the TEST-only config.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from app.config import Settings
from app.main import create_app
from app.poolside_ux_test import (
    PoolsideUXTestClient,
    TEST_TASK_BINDING_NAME,
    TEST_TASK_ID,
    is_canonical_test_host,
)
from app.worker_config import binding_value, response_headers_for_path

SECRET_BINDING_NAME = "PADIEM_POOLSIDE_API_KEY"
TEST_RUNTIME_LABEL = "test_direct"
_worker_app = None


def _test_guard_enabled(env: Any) -> bool:
    return binding_value(env, TEST_TASK_BINDING_NAME) == TEST_TASK_ID


def _candidate_health_response(path: str) -> Any:
    response = Response(
        json.dumps(
            {
                "status": "ok",
                "app": "padiem-chat",
                "runtime": TEST_RUNTIME_LABEL,
                "test_candidate": True,
                "test_task_id": TEST_TASK_ID,
            },
            separators=(",", ":"),
        ),
        status=200,
        headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
    )
    return _apply_headers(response, path)


def _blocked_test_response(path: str) -> Any:
    response = Response(
        "This bounded test Worker is not enabled for ordinary traffic.",
        status=403,
        headers={"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
    )
    return _apply_headers(response, path)


def _apply_headers(response: Any, path: str) -> Any:
    for name, value in response_headers_for_path(path).items():
        response.headers[name] = value
    return response


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

        global _worker_app
        parsed = urlparse(request.url)
        path = parsed.path

        # The version override is the only routing mechanism. This server-side
        # task binding prevents an accidentally promoted candidate from serving
        # ordinary canonical traffic without the exact authorized task guard.
        if not is_canonical_test_host(parsed.hostname) or not _test_guard_enabled(self.env):
            return _blocked_test_response(path)
        if path == "/health":
            return _candidate_health_response(path)

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
