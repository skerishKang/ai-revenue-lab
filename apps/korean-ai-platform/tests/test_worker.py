"""Tests for Cloudflare Python Worker integration (contract & bridge logic)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

WORKER_SRC = Path(__file__).resolve().parent.parent / "worker.py"
WRANGLER_TOML = Path(__file__).resolve().parent.parent / "wrangler.toml"


class TestWorkerEntrypoint:
    def test_file_exists(self):
        assert WORKER_SRC.is_file()

    def test_has_default_class(self):
        src = WORKER_SRC.read_text()
        assert "class Default(WorkerEntrypoint)" in src

    def test_has_asgi_fetch(self):
        src = WORKER_SRC.read_text()
        assert "asgi.fetch(app," in src

    def test_imports_app_main(self):
        src = WORKER_SRC.read_text()
        assert "from app.main import app" in src

    def test_security_headers(self):
        src = WORKER_SRC.read_text()
        for h in ("X-Content-Type-Options", "X-Frame-Options",
                  "Referrer-Policy", "Cache-Control"):
            assert h in src

    def test_root_redirects_before_asgi(self):
        src = WORKER_SRC.read_text()
        redirect_guard = 'if urlparse(request.url).path == "/":'
        assert "from workers import Response, WorkerEntrypoint" in src
        assert redirect_guard in src
        assert '"Location": "/workspace"' in src
        assert "status=307" in src
        assert src.index(redirect_guard) < src.index("asgi.fetch(app,")

    def test_root_redirect_keeps_security_headers(self):
        src = WORKER_SRC.read_text()
        redirect_block = src.split('if urlparse(request.url).path == "/":', 1)[1]
        redirect_block = redirect_block.split("# Collect env bindings", 1)[0]
        assert "**_SECURITY_HEADERS" in redirect_block


class TestWranglerConfig:
    def test_name_exact(self):
        content = WRANGLER_TOML.read_text()
        m = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
        assert m and m.group(1) == "ai-revenue-korean-ai-platform"

    def test_python_workers_flag(self):
        assert "python_workers" in WRANGLER_TOML.read_text()

    def test_assets_binding(self):
        content = WRANGLER_TOML.read_text()
        assert "binding = \"ASSETS\"" in content
        assert "[assets]" in content

    def test_no_secret_values_or_account_credentials(self):
        content = WRANGLER_TOML.read_text()
        for word in ("api_token", "CLOUDFLARE", "account_id"):
            assert word.lower() not in content.lower()
        # The binding name/resource identity is intentionally present; no
        # secret value or API credential is embedded in this config.
        assert 'type = "secrets_store_secret"' in content
        assert 'store_id = "f0b09ca04a7b43248154c773704a5616"' in content
        assert 'secret_name = "PADIEM_POOLSIDE_API_KEY"' in content


class TestEnvBridge:
    """Test _apply_env_once logic (deployment-level immutable config)."""

    @pytest.mark.asyncio
    async def test_secret_store_binding_is_resolved_with_async_get(self):
        from app.pilot.worker_env import collect_env_overrides

        class SecretBinding:
            async def get(self):
                return "resolved-poolside-secret"

        env = SimpleNamespace(
            PADIEM_POOLSIDE_API_KEY=SecretBinding(),
            B14_PROVIDER_MODE="live",
        )

        overrides = await collect_env_overrides(
            env, ("PADIEM_POOLSIDE_API_KEY", "B14_PROVIDER_MODE")
        )

        assert overrides["PADIEM_POOLSIDE_API_KEY"] == "resolved-poolside-secret"
        assert "SecretBinding" not in overrides["PADIEM_POOLSIDE_API_KEY"]
        assert overrides["B14_PROVIDER_MODE"] == "live"

    def test_secret_binding_helper_is_used(self):
        src = WORKER_SRC.read_text()
        assert "from app.pilot.worker_env import collect_env_overrides" in src
        assert "await collect_env_overrides(self.env, _ENV_KEYS)" in src

    def test_env_keys_defined(self):
        src = WORKER_SRC.read_text()
        for k in ("BUSINESS14_PROVIDER_REGISTRY_JSON",
                  "BUSINESS14_PILOT_BASE_URL",
                  "BUSINESS14_PILOT_MODEL_ID",
                  "BUSINESS14_PILOT_PROVIDER_ID",
                  "BUSINESS14_PILOT_UPSTREAM_MODEL",
                  "BUSINESS14_PILOT_TIMEOUT_SECONDS"):
            assert k in src

    def test_applied_once_flag_in_source(self):
        """The _env_applied flag pattern exists in worker.py."""
        src = WORKER_SRC.read_text()
        assert "_env_applied" in src
