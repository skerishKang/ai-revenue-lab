"""Living Travel staging deployment on Modal.

Isolated staging App: ``ai-revenue-living-travel-staging``. It serves the same
FastAPI factory as local/test but is configured (via the service-specific Modal
Secret) for PostgreSQL + Firebase. There is NO persistent volume and NO SQLite
database on Modal — persistence is Neon PostgreSQL only.

Required Secret ``ai-revenue-living-travel-staging`` keys (fail-closed if absent
or incomplete — see app.config validation):
    LT_ENVIRONMENT=staging
    LT_DATABASE_BACKEND=postgresql
    LT_AUTH_MODE=firebase
    LT_DATABASE_URL            (Neon pooled runtime URL)
    LT_MIGRATION_DATABASE_URL  (Neon direct URL)
    LT_FIREBASE_PROJECT_ID=ai-revenue-lab-identity
    FIREBASE_SERVICE_ACCOUNT_JSON  (Firebase Admin service account JSON)
    LT_ALLOWED_ORIGINS         (comma-separated exact origins)

Deploy:
    modal deploy apps/living-travel/modal_app.py
"""

from __future__ import annotations

from pathlib import Path

import modal

APP_NAME = "ai-revenue-living-travel-staging"
SECRET_NAME = "ai-revenue-living-travel-staging"

_HERE = Path(__file__).resolve().parent

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi>=0.115",
        "uvicorn>=0.30",
        "pydantic>=2.7",
        "pydantic-settings>=2.3",
        "jinja2>=3.1",
        "python-multipart>=0.0.9",
        "psycopg[binary]>=3.2,<4",
        "firebase-admin>=6.5",
    )
    # Application package + migration SQL (sibling layout matches app.db discovery).
    .add_local_dir(str(_HERE / "app"), remote_path="/root/lt/app")
    .add_local_dir(str(_HERE / "migrations"), remote_path="/root/lt/migrations")
    .env({"PYTHONPATH": "/root/lt"})
)

app = modal.App(APP_NAME, image=image)


@app.function(
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    timeout=300,
    scaledown_window=60,  # scale-to-zero friendly
)
@modal.asgi_app()
def web():
    """ASGI entrypoint. create_app() runs migrations and validates config,
    failing closed if required PostgreSQL/Firebase settings are missing."""
    from app.factory import create_app

    return create_app()
