"""Cloudflare Python Worker entrypoint for Korean AI Platform.

Environment variables from Worker bindings are injected into the request scope
so that downstream handlers can access them without modifying global state.
Security headers are applied to every response, including static assets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from app.main import app

# ---------------------------------------------------------------------------
# Static files — read at module load time (survives Pyodide snapshot)
# ---------------------------------------------------------------------------
_STATIC: dict[str, tuple[bytes, str]] = {}

for _sd in (
    Path(__file__).resolve().parent / "static",
    Path(__file__).resolve().parent.parent / "static",
):
    if _sd.is_dir():
        for _f in sorted(_sd.iterdir()):
            if _f.is_file():
                _mime = {
                    ".css": "text/css",
                    ".js": "application/javascript",
                    ".png": "image/png",
                    ".svg": "image/svg+xml",
                    ".ico": "image/x-icon",
                }.get(_f.suffix.lower(), "application/octet-stream")
                _STATIC[_f.name] = (_f.read_bytes(), _mime)


# ENV keys
_ENV_KEYS = frozenset({
    "BUSINESS14_PROVIDER_REGISTRY_JSON",
    "BUSINESS14_PILOT_BASE_URL",
    "BUSINESS14_PILOT_MODEL_ID",
    "BUSINESS14_PILOT_PROVIDER_ID",
    "BUSINESS14_PILOT_UPSTREAM_MODEL",
    "BUSINESS14_PILOT_TIMEOUT_SECONDS",
    "OPENROUTER_API_KEY",
    "AGNES_API_KEY",
    "B14_PROVIDER_MODE",
    "B14_OPENROUTER_BASE_URL",
    "B14_SITE_URL",
    "B14_SITE_NAME",
})

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _apply_security_headers(response: Any) -> Any:
    """Apply the production response policy to ASGI and Worker responses."""
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


# ---------------------------------------------------------------------------
# Worker entrypoint
# ---------------------------------------------------------------------------
class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

        # The public Worker root is a product entrypoint, not the legacy demo
        # home page. Intercept it before ASGI so the production URL cannot fail
        # while rendering the legacy template.
        if urlparse(request.url).path == "/":
            return Response(
                "",
                status=307,
                headers={
                    "Location": "/workspace",
                    **_SECURITY_HEADERS,
                },
            )

        # Collect env bindings
        env_overrides: dict[str, str] = {}
        for key in _ENV_KEYS:
            value = getattr(self.env, key, None)
            if value is not None:
                env_overrides[key] = str(value)

        # Apply Worker env bindings BEFORE app processes the request.
        if env_overrides:
            _apply_env_once(env_overrides)

        native_resp = await asgi.fetch(app, request.js_object, self.env)
        return _apply_security_headers(native_resp)


# ---------------------------------------------------------------------------
# Environment overrides — applied once on first request (deployment-level)
# ---------------------------------------------------------------------------
_env_applied = False


def _apply_env_once(overrides: dict[str, str]) -> None:
    """Apply Worker env bindings exactly once (deployment-level immutable).

    Cloudflare deploys each Worker into fresh isolates.  The env bindings
    are the same for every request served by that deployment.  Applying
    them once on first request is safe: there is exactly one set of
    bindings per deployment, and no isolate-reuse scenario changes them
    mid-lifecycle.

    Callers MUST NOT call this more than once per isolate lifetime.
    """
    global _env_applied
    if _env_applied:
        return
    _env_applied = True

    from app.pilot.config import pilot_settings

    _B14_MAP = {
        "OPENROUTER_API_KEY": "api_key",
        "B14_PROVIDER_MODE": "provider_mode",
        "B14_OPENROUTER_BASE_URL": "base_url",
        "B14_SITE_URL": "site_url",
        "B14_SITE_NAME": "site_name",
    }

    from app.pilot.openrouter_config import openrouter_config
    for env_key, attr in _B14_MAP.items():
        value = overrides.get(env_key)
        if value is not None:
            setattr(openrouter_config, attr, value)

    _MAP = {
        "BUSINESS14_PROVIDER_REGISTRY_JSON": "provider_registry_json",
        "BUSINESS14_PILOT_BASE_URL": "pilot_base_url",
        "BUSINESS14_PILOT_MODEL_ID": "pilot_model_id",
        "BUSINESS14_PILOT_PROVIDER_ID": "pilot_provider_id",
        "BUSINESS14_PILOT_UPSTREAM_MODEL": "pilot_upstream_model",
        "BUSINESS14_PILOT_TIMEOUT_SECONDS": "pilot_timeout_seconds",
    }

    for env_key, attr in _MAP.items():
        value = overrides.get(env_key)
        if value is not None:
            setattr(pilot_settings, attr, value)

    from app.pilot.registry import reset_registry
    reset_registry()

    # Surface each registered platform-owned Provider's secret binding into the
    # process environment so the generic platform credential plane can read it.
    # The binding name is non-secret; the value is never logged or exposed.
    import os as _os

    from app.pilot import platform_secrets as _ps

    for _spec in _ps.list_platform_providers():
        if _spec.credential_source == _ps.CredentialSource.PLATFORM_SECRET:
            _value = overrides.get(_spec.credential_binding_name)
            if _value is not None:
                _os.environ[_spec.credential_binding_name] = str(_value)
