"""Cloudflare Python Worker adapter for Living Fiction.

This module deliberately reuses the canonical FastAPI ``create_app`` factory.
It contains no product routes or database implementation of its own.

M0 is source/preflight only. Production deployment stays blocked until the
PostgreSQL dependency path is proven compatible with Python Workers or the
Cloudflare Container fallback is selected under Issue #2223.
"""

from __future__ import annotations

import os

from workers import asgi, env


def _required_text_binding(name: str) -> str:
    value = getattr(env, name, None)
    if value is None:
        raise RuntimeError(f"missing required Cloudflare binding: {name}")
    text = str(value).strip()
    if not text:
        raise RuntimeError(f"empty required Cloudflare binding: {name}")
    return text


def _configure_living_fiction_environment() -> None:
    """Project trusted Worker bindings into the existing LF_* config seam.

    The existing application is pydantic-settings/environment based. Cloudflare
    Python bindings are not treated as browser/user authority; only server-owned
    Worker bindings are copied into the process environment before importing
    the canonical application factory.
    """

    hyperdrive = getattr(env, "HYPERDRIVE", None)
    connection_string = (
        getattr(hyperdrive, "connectionString", None)
        if hyperdrive is not None
        else None
    )
    if connection_string is None or not str(connection_string).strip():
        raise RuntimeError("missing required Cloudflare Hyperdrive binding")

    os.environ["LF_ENV"] = "production"
    os.environ["LF_DATABASE_BACKEND"] = "postgres"
    os.environ["LF_DATABASE_URL"] = str(connection_string)

    # Migration credentials remain an operator-only path and are intentionally
    # NOT projected into the request-serving Worker.
    os.environ.pop("LF_MIGRATION_DATABASE_URL", None)

    for name in (
        "LF_ADMIN_SECRET",
        "LF_CREDENTIAL_HMAC_KEY",
        "LF_SESSION_HMAC_KEY",
        "LF_ALLOWED_ORIGINS",
    ):
        os.environ[name] = _required_text_binding(name)

    # Keep the migration source-only: do not silently activate a paid/live AI
    # provider while moving hosting platforms.
    os.environ["LF_AI_PROVIDER"] = "mock"
    os.environ["LF_AI_MODEL"] = "mock-living-fiction-v1"


_configure_living_fiction_environment()

# Import only after trusted Worker bindings have been projected, because
# app.config constructs the canonical Settings object at import time.
from app.factory import create_app  # noqa: E402

app = create_app()
Default = asgi.entrypoint(app)
