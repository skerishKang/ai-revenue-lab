"""Cloudflare Python Worker entrypoint for Korean AI Platform.

Bridges Worker env bindings to pydantic-settings singletons at request time.
Security headers are applied at the fetch handler level.
Static files are served from memory (loaded at module load time).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def _serve_static(request_url: str) -> tuple[bytes | None, str | None]:
    """Check if the request is for a known static file."""
    parsed = urlparse(request_url)
    path = parsed.path
    if not path.startswith("/static/"):
        return None, None
    filename = path[len("/static/"):]
    entry = _STATIC.get(filename)
    if entry is None:
        return None, None
    return entry  # (data, mime_type)


# ---------------------------------------------------------------------------
# Environment bridge
# ---------------------------------------------------------------------------
def _bridge_env(env: Any) -> None:
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
        value = getattr(env, env_key, None)
        if value is not None:
            setattr(pilot_settings, attr, value)

    from app.pilot.registry import reset_registry
    reset_registry()


# ---------------------------------------------------------------------------
# Worker entrypoint
# ---------------------------------------------------------------------------
class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

        _bridge_env(self.env)

        # Serve static files from memory
        data, mime = _serve_static(request.url)
        if data is not None:
            resp = Response(data)
            resp.headers["Content-Type"] = mime
        else:
            resp = await asgi.fetch(app, request.js_object, self.env)

        # Security headers
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"

        return resp


from workers import Response  # noqa: E402
