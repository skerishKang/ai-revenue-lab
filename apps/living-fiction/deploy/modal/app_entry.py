"""Modal deployment entry for Living Fiction (free-tier Starter skeleton).

Deploy (Phase B, by an operator — this file never deploys itself):

    cd apps/living-fiction
    modal deploy deploy/modal/app_entry.py

Design constraints honoured here:

* Reuses the existing ``create_app()`` ASGI factory unchanged.
* App name is stable: ``ai-revenue-living-fiction``.
* Scales to zero: ``min_containers=0``, ``buffer_containers=0``, short
  ``scaledown_window``. No keep-warm, no always-on container, no GPU, no
  Volume, no custom domain.
* Hard capacity cap: ``max_containers`` bounds total concurrency (Modal serves
  one concurrent input per container by default; this entry deliberately keeps
  that default instead of raising per-container concurrency).
* Secrets are referenced by NAME only; no secret value appears in this file.
  The operator creates the secret out of band:

      modal secret create living-fiction-secrets \
          LF_ENV=... LF_DATABASE_BACKEND=postgres LF_DATABASE_URL=... \
          LF_ALLOWED_ORIGINS=... LF_ADMIN_SECRET=... \
          LF_CREDENTIAL_HMAC_KEY=... LF_SESSION_HMAC_KEY=...

* Production configuration fails closed inside ``create_app()`` (missing
  backend selection, missing runtime URL, weak secrets, or a non-current
  schema all abort startup). Cold starts are expected and acceptable.
"""

from __future__ import annotations

import modal

APP_NAME = "ai-revenue-living-fiction"
SECRET_NAME = "living-fiction-secrets"

MAX_CONTAINERS = 2
SCALEDOWN_WINDOW_SECONDS = 60
FUNCTION_TIMEOUT_SECONDS = 60
CPU = 0.25
MEMORY_MB = 512

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "fastapi>=0.115,<1",
    "uvicorn>=0.32,<1",
    "pydantic>=2.10,<3",
    "pydantic-settings>=2.6,<3",
    "jinja2>=3.1,<4",
    "python-multipart>=0.0.18,<1",
    "psycopg[binary]>=3.2,<4",
    "psycopg-pool>=3.2,<4",
)

app = modal.App(
    APP_NAME,
    image=image,
    secrets=[modal.Secret.from_name(SECRET_NAME)],
)


def build_asgi_app():
    """Build the ASGI application (imported lazily so the image builds fast).

    Kept as a plain callable so tests can exercise the exact startup path
    without Modal machinery. ``create_app()`` validates the backend selection,
    opens the bounded pool, and verifies the PostgreSQL schema is current —
    failing closed on any misconfiguration.
    """
    from app.factory import create_app  # noqa: PLC0415

    return create_app()


@app.function(
    cpu=CPU,
    memory=MEMORY_MB,
    min_containers=0,
    buffer_containers=0,
    max_containers=MAX_CONTAINERS,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    timeout=FUNCTION_TIMEOUT_SECONDS,
)
@modal.asgi_app()
def web():
    """The public ASGI web endpoint (all Living Fiction routes + /health)."""
    return build_asgi_app()
