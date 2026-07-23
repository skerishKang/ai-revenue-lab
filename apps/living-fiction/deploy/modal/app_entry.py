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
* Runtime sources are packaged explicitly with ``Image.add_local_dir``. Modal
  1.x does not auto-include arbitrary sibling local packages, so this entry
  never relies on automount and never copies the whole repository. Only the
  ``app`` package (which carries the ``templates/`` and ``static/``
  subdirectories that ``app/web.py`` resolves relative to itself) and
  ``migrations_postgres`` (verified at startup by ``app/factory.py`` via
  ``app_root``) are shipped. Tests, local SQLite data, ``.env``, virtualenvs,
  and other Business apps are excluded.
* Secrets are referenced by NAME only; no secret value appears in this file.
  ``required_keys`` documents the runtime keys Modal must resolve; the
  application still fails closed inside ``create_app()``. The operator creates
  the secret out of band:

      modal secret create living-fiction-secrets \
          LF_ENV=... LF_DATABASE_BACKEND=postgres LF_DATABASE_URL=... \
          LF_ALLOWED_ORIGINS=... LF_ADMIN_SECRET=... \
          LF_CREDENTIAL_HMAC_KEY=... LF_SESSION_HMAC_KEY=...

  ``LF_MIGRATION_DATABASE_URL`` is deliberately NOT a runtime secret key — it
  is an operator-only migration connection string.

* Production configuration fails closed inside ``create_app()`` (missing
  backend selection, missing runtime URL, weak secrets, or a non-current
  schema all abort startup). Cold starts are expected and acceptable.
"""

from __future__ import annotations

from pathlib import Path

import modal

APP_NAME = "ai-revenue-living-fiction"
SECRET_NAME = "living-fiction-secrets"

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

RUNTIME_DEPENDENCIES = (
    "fastapi>=0.115,<1",
    "uvicorn>=0.32,<1",
    "pydantic>=2.10,<3",
    "pydantic-settings>=2.6,<3",
    "jinja2>=3.1,<4",
    "python-multipart>=0.0.18,<1",
    "psycopg[binary]>=3.2,<4",
    "psycopg-pool>=3.2,<4",
)

REQUIRED_SECRET_KEYS = (
    "LF_ENV",
    "LF_DATABASE_BACKEND",
    "LF_DATABASE_URL",
    "LF_ALLOWED_ORIGINS",
    "LF_ADMIN_SECRET",
    "LF_CREDENTIAL_HMAC_KEY",
    "LF_SESSION_HMAC_KEY",
)

MAX_CONTAINERS = 2
SCALEDOWN_WINDOW_SECONDS = 60
FUNCTION_TIMEOUT_SECONDS = 60
CPU = 0.25
MEMORY_MB = 512


def build_modal_image(package_root: Path = PACKAGE_ROOT, base_image=None):
    """Assemble the Modal Image with only the runtime sources the app needs.

    The ``app`` package is mapped to ``/root/app``; because ``app/web.py``
    resolves ``templates`` and ``static`` relative to its own directory, those
    subdirectories land at ``/root/app/templates`` and ``/root/app/static``.
    ``migrations_postgres`` is mapped to ``/root/migrations_postgres`` to match
    ``app/factory.py`` (``app_root = Path(__file__).parent.parent`` → ``/root``).

    ``base_image`` is an injection seam: tests pass a fake fluent image to
    assert the exact ``add_local_dir`` mappings without touching the Modal
    network or building a real image.
    """
    if base_image is None:
        base_image = modal.Image.debian_slim(python_version="3.11").pip_install(
            *RUNTIME_DEPENDENCIES
        )
    image = base_image
    image = image.add_local_dir(package_root / "app", "/root/app")
    image = image.add_local_dir(
        package_root / "migrations_postgres", "/root/migrations_postgres"
    )
    return image


image = build_modal_image()

app = modal.App(
    APP_NAME,
    image=image,
    secrets=[
        modal.Secret.from_name(SECRET_NAME, required_keys=list(REQUIRED_SECRET_KEYS))
    ],
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
