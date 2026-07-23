"""Modal ASGI deployment for Living Learning staging.

Reuses the same ``create_app()`` FastAPI factory — no separate product behavior.
Scale-to-zero (``min_containers=0``), bounded concurrency, a named Modal Secret,
and fail-closed startup config (inside ``create_app()``). ``modal`` is imported
lazily so this module imports cleanly without the Modal SDK installed (import
smoke test).

Staging app name: ``ai-revenue-living-learning-staging``.

Required secret keys (values stored ONLY in the named Modal Secret, never here):
    LL_ENVIRONMENT=staging
    LL_DATABASE_BACKEND=postgresql
    LL_DATABASE_URL              (runtime pooled PostgreSQL URL)
    LL_IDENTITY_PROVIDER=firebase
    LL_FIREBASE_PROJECT_ID
    FIREBASE_SERVICE_ACCOUNT_JSON
    LL_ALLOWED_ORIGINS
    LL_PROVIDER_TYPE / LL_PROVIDER_MODEL / LL_ALLOW_MOCK_STAGING

``LL_MIGRATION_DATABASE_URL`` is deliberately NOT a runtime secret: migrations
run via the operator command (``python -m app.production.migrate``), never from
the runtime container.
"""

from __future__ import annotations

APP_NAME = "ai-revenue-living-learning-staging"
SECRET_NAME = "living-learning-staging-secrets"

# Documented required runtime secret keys (values never stored in this file).
REQUIRED_SECRET_KEYS = (
    "LL_ENVIRONMENT",
    "LL_DATABASE_BACKEND",
    "LL_DATABASE_URL",
    "LL_IDENTITY_PROVIDER",
    "LL_FIREBASE_PROJECT_ID",
    "FIREBASE_SERVICE_ACCOUNT_JSON",
    "LL_ALLOWED_ORIGINS",
)

RUNTIME_DEPENDENCIES = [
    "fastapi>=0.115,<1",
    "uvicorn",
    "pydantic>=2.10,<3",
    "pydantic-settings",
    "psycopg[binary]>=3.2,<4",
    "psycopg-pool>=3.2,<4",
    "firebase-admin>=6.5",
]

# Scale-to-zero capacity cap (no always-on container, no keep-warm).
MIN_CONTAINERS = 0
BUFFER_CONTAINERS = 0
MAX_CONTAINERS = 2
SCALEDOWN_WINDOW_SECONDS = 60
FUNCTION_TIMEOUT_SECONDS = 60
CPU = 0.25
MEMORY_MB = 512


def build_modal_image():
    """Build the Modal image, shipping only ``app`` and ``migrations_postgres``."""
    import modal

    image = modal.Image.debian_slim("3.12").pip_install(*RUNTIME_DEPENDENCIES)
    # Ship only the application package and PostgreSQL migrations (never the
    # whole repo, never automount).
    from pathlib import Path

    package_root = Path(__file__).resolve().parent.parent
    image = image.add_local_dir(package_root, remote_path="/root/app")
    migrations_dir = package_root.parent / "migrations_postgres"
    image = image.add_local_dir(migrations_dir, remote_path="/root/migrations_postgres")
    return image


def build_asgi_app():
    """Lazily build the FastAPI app so the image build stays fast."""
    from app.factory import create_app

    return create_app()


def build_app():
    """Construct the Modal App with the ASGI function (call with modal installed)."""
    import modal

    image = build_modal_image()
    app = modal.App(
        APP_NAME,
        image=image,
        secrets=[modal.Secret.from_name(SECRET_NAME, required_keys=list(REQUIRED_SECRET_KEYS))],
    )

    @app.function(
        cpu=CPU,
        memory=MEMORY_MB,
        min_containers=MIN_CONTAINERS,
        buffer_containers=BUFFER_CONTAINERS,
        max_containers=MAX_CONTAINERS,
        scaledown_window=SCALEDOWN_WINDOW_SECONDS,
        timeout=FUNCTION_TIMEOUT_SECONDS,
    )
    @modal.asgi_app()
    def web():
        return build_asgi_app()

    return app


# ``app`` is resolved lazily by Modal's CLI; importing this module without modal
# installed must not fail, so we do not call build_app() at import time.
