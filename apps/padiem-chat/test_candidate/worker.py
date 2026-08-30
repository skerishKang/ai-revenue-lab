"""TEST-only Worker wrapper for the B62-1090-011 lightweight candidate."""

from __future__ import annotations

import asgi
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from candidate_app import (
    CANONICAL_HOST,
    TEST_GUARD_DIGEST_BINDING,
    TEST_GUARD_HEADER,
    create_app,
    request_guard_matches,
)

SECRET_BINDING_NAME = "PADIEM_POOLSIDE_API_KEY"


def _binding(env, name: str):
    if isinstance(env, dict):
        return env.get(name)
    return getattr(env, name, None)


def _guard_ok(request, env) -> bool:
    hostname = (urlparse(request.url).hostname or "").strip().lower().rstrip(".")
    if hostname != CANONICAL_HOST:
        return False
    return request_guard_matches(
        hostname,
        request.headers.get(TEST_GUARD_HEADER),
        _binding(env, TEST_GUARD_DIGEST_BINDING),
    )


class Default(WorkerEntrypoint):
    _app = None

    async def fetch(self, request, env=None):
        # This check must remain before health handling, secret binding access,
        # client construction, and any provider-side work.
        runtime_env = env if env is not None else self.env
        if not _guard_ok(request, runtime_env):
            return Response(
                "This bounded test Worker is not enabled for this request.",
                status=403,
                headers={"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
            )

        path = urlparse(request.url).path
        if path == "/health":
            app = create_app(None, _binding(runtime_env, TEST_GUARD_DIGEST_BINDING))
        else:
            secret_binding = _binding(runtime_env, SECRET_BINDING_NAME)
            if secret_binding is None:
                return Response(
                    "The bounded test credential binding is unavailable.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
                )
            app = create_app(
                secret_binding,
                _binding(runtime_env, TEST_GUARD_DIGEST_BINDING),
            )

        return await asgi.fetch(app, request.js_object, runtime_env)
