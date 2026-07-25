"""Cloudflare Python Worker entrypoint for Korean AI Platform.

Environment variables from Worker bindings are injected into the request scope
so that downstream handlers can access them without modifying global state.
Security headers are applied to every response, including static assets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workers import WorkerEntrypoint

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
})


# ---------------------------------------------------------------------------
# Worker entrypoint
# ---------------------------------------------------------------------------
class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

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

        # Security headers — applied to all responses
        native_resp.headers["X-Content-Type-Options"] = "nosniff"
        native_resp.headers["X-Frame-Options"] = "DENY"
        native_resp.headers["Referrer-Policy"] = "no-referrer"
        native_resp.headers["Cache-Control"] = "no-store"

        return native_resp


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
