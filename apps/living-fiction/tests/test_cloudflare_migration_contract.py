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
    assert "LF_DATABASE_URL" not in config
    assert "LF_MIGRATION_DATABASE_URL" not in config
    assert 'os.environ["LF_AI_PROVIDER"] = "mock"' in source
    assert "CONTAINER_FALLBACK_REQUIRED" in readme
    assert "MODAL_RETIREMENT_BEFORE_PARITY = NO" in readme
