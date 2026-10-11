from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLOUDFLARE = ROOT / "deploy" / "cloudflare"


def test_cloudflare_adapter_reuses_canonical_fastapi_factory() -> None:
    source = (CLOUDFLARE / "worker.py").read_text(encoding="utf-8")

    assert "from app.factory import create_app" in source
    assert "app = create_app()" in source
    assert "Default = asgi.entrypoint(app)" in source
    assert "FastAPI(" not in source


def test_cloudflare_adapter_keeps_database_and_security_authority_server_side() -> None:
    source = (CLOUDFLARE / "worker.py").read_text(encoding="utf-8")

    assert 'os.environ["LF_DATABASE_BACKEND"] = "postgres"' in source
    assert "HYPERDRIVE" in source
    assert 'os.environ.pop("LF_MIGRATION_DATABASE_URL", None)' in source
    assert "LF_ADMIN_SECRET" in source
    assert "LF_CREDENTIAL_HMAC_KEY" in source
    assert "LF_SESSION_HMAC_KEY" in source
    assert "LF_ALLOWED_ORIGINS" in source
    assert "MODAL" not in source


def test_cloudflare_m0_does_not_fabricate_runtime_resources_or_activate_ai() -> None:
    config = (CLOUDFLARE / "wrangler.toml").read_text(encoding="utf-8")
    source = (CLOUDFLARE / "worker.py").read_text(encoding="utf-8")
    readme = (CLOUDFLARE / "README.md").read_text(encoding="utf-8")

    assert 'compatibility_flags = ["python_workers"]' in config
    assert "[[hyperdrive]]" not in config
    assert "LF_DATABASE_URL =" not in config
    assert "LF_MIGRATION_DATABASE_URL =" not in config
    assert 'os.environ["LF_AI_PROVIDER"] = "mock"' in source
    assert "PRIMARY_MIGRATION_TARGET = CLOUDFLARE_CONTAINER" in readme
    assert "MODAL_RETIREMENT_BEFORE_PARITY = NO" in readme


def test_container_path_runs_canonical_app_with_neon_server_secrets_only() -> None:
    dockerfile = (ROOT / "Dockerfile.cloudflare").read_text(encoding="utf-8")
    worker = (CLOUDFLARE / "container_worker.js").read_text(encoding="utf-8")
    config = (ROOT / "wrangler.cloudflare-container.toml").read_text(encoding="utf-8")

    assert 'CMD ["uvicorn", "app.main:app"' in dockerfile
    assert 'python -m pip install ".[postgres]"' in dockerfile
    assert 'LF_DATABASE_URL: workerEnv.LF_DATABASE_URL' in worker
    assert 'LF_DATABASE_BACKEND: "postgres"' in worker
    assert 'LF_AI_PROVIDER: "mock"' in worker
    assert "LF_MIGRATION_DATABASE_URL" not in worker
    assert "@cloudflare/containers" in worker
    assert 'image = "./Dockerfile.cloudflare"' in config
    assert 'max_instances = 1' in config
    assert "MODAL" not in worker


def test_container_path_preserves_private_security_bindings() -> None:
    worker = (CLOUDFLARE / "container_worker.js").read_text(encoding="utf-8")

    for binding in (
        "LF_ADMIN_SECRET",
        "LF_CREDENTIAL_HMAC_KEY",
        "LF_SESSION_HMAC_KEY",
        "LF_ALLOWED_ORIGINS",
    ):
        assert f"{binding}: workerEnv.{binding}" in worker


def test_container_build_context_excludes_secrets_runtime_state_and_tooling() -> None:
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    required = {
        ".env",
        ".env.*",
        "node_modules",
        ".wrangler",
        ".wrangler-*",
        "__pycache__",
        "*.py[cod]",
        "*.sqlite",
        "*.sqlite3",
        "*.db",
        "var",
    }
    assert required <= ignored
    # Keep the non-secret configuration example available to image builders and
    # reviewers even though environment files are denied by default.
    assert "!.env.example" in ignored
