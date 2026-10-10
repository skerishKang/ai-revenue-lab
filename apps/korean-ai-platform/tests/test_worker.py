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

    def test_workers_runtime_dependency_is_declared(self):
        content = (WRANGLER_TOML.parent / "pyproject.toml").read_text()
        assert '"workers-py==1.17.0"' not in content
        assert '"workers-py==1.16.2"' in content
        assert "[tool.pywrangler]" in content
        assert "allow-build = true" in content

    def test_assets_binding(self):
        content = WRANGLER_TOML.read_text()
        assert "binding = \"ASSETS\"" in content
        assert "[assets]" in content

    def test_canonical_live_mode_is_declared(self):
        content = WRANGLER_TOML.read_text()
        assert "[vars]" in content
        assert 'B14_PROVIDER_MODE = "live"' in content

    def test_no_secret_values_or_account_credentials(self):
        content = WRANGLER_TOML.read_text()
        for word in ("api_token", "CLOUDFLARE", "account_id"):
            assert word.lower() not in content.lower()
        # Owner decision 2026-09-18: Agnes+Poolside Secrets Store bindings
        # re-registered; both declarations are metadata-only (store_id,
        # secret_name) with no secret values committed here.
        # #3554: the PADIEM_GEMINI_API_KEY binding follows the same
        # metadata-only contract, raising the declared store binding count to 9.
        assert "[[unsafe.bindings]]" not in content
        assert 'type = "secrets_store_secret"' not in content
        import tomllib
        bindings=tomllib.loads(content)["secrets_store_secrets"]
        assert content.count("[[secrets_store_secrets]]") == len(bindings)
        assert len(bindings) >= 10
        assert all(b["store_id"] == "f0b09ca04a7b43248154c773704a5616" for b in bindings)
        assert len({b["binding"] for b in bindings}) == len(bindings)
        assert all(b["binding"] == b["secret_name"] for b in bindings)
        assert 'binding = "PADIEM_AGNES_API_KEY"' in content
        assert 'secret_name = "PADIEM_AGNES_API_KEY"' in content
        assert 'binding = "PADIEM_POOLSIDE_API_KEY"' in content
        assert 'secret_name = "PADIEM_POOLSIDE_API_KEY"' in content
        assert "PADIEM_AGNES_API_KEY =" not in content
        assert "PADIEM_POOLSIDE_API_KEY =" not in content

        for binding in (
            "PADIEM_INFRON_API_KEY",
            "PADIEM_INCEPTION_MERCURY_API_KEY",
            "PADIEM_ATRIA_API_KEY",
            "PADIEM_EXLAB_API_KEY",
            "PADIEM_GEMINI_API_KEY",
            "PADIEM_KIRAAI_API_KEY",
        ):
            assert f'binding = "{binding}"' in content
            assert f'secret_name = "{binding}"' in content
            assert f"{binding} =" not in content

    def test_bai_secret_store_binding_is_metadata_only_and_exact(self):
        content = WRANGLER_TOML.read_text()
        assert '[[secrets_store_secrets]]' in content
        assert 'binding = "PADIEM_B_AI_API_KEY"' in content
        assert 'store_id = "f0b09ca04a7b43248154c773704a5616"' in content
        assert 'secret_name = "PADIEM_B_AI_API_KEY"' in content
        assert "PADIEM_B_AI_API_KEY =" not in content


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
        assert "from app.pilot.worker_env import (" in src
        assert "bind_request_env," in src
        assert "collect_env_overrides," in src
        assert "reset_request_env," in src
        assert "await collect_env_overrides(self.env, _ENV_KEYS)" in src
        assert "for _env_key, _value in overrides.items()" in src
        assert "_os.environ[_env_key] = str(_value)" in src
        assert "if _env_key in _NON_SECRET_ENV_KEYS:" in src

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


def test_kilo_secret_store_binding_is_metadata_only_and_env_bridged():
    content = WRANGLER_TOML.read_text()
    worker = WORKER_SRC.read_text()
    assert 'binding = "PADIEM_KILO_API_KEY"' in content
    assert 'store_id = "f0b09ca04a7b43248154c773704a5616"' in content
    assert 'secret_name = "PADIEM_KILO_API_KEY"' in content
    assert 'secret_name = "KILO_API_KEY"' not in content
    assert "PADIEM_KILO_API_KEY =" not in content
    assert '"PADIEM_KILO_API_KEY"' in worker

def test_gemini_secret_store_binding_is_metadata_only_and_matches_provider():
    """#3554: the Google AI Studio credential binding is declared metadata-only.

    The binding name must equal GOOGLE_CREDENTIAL_BINDING so the registered
    Google provider resolves the store secret by that exact name; no secret
    value is ever committed, and the store_id stays the shared approved one.
    """
    content = WRANGLER_TOML.read_text()
    provider = (Path(__file__).resolve().parent.parent / "app" / "pilot" / "google_provider.py").read_text()
    assert '[[secrets_store_secrets]]' in content
    assert 'binding = "PADIEM_GEMINI_API_KEY"' in content
    assert 'store_id = "f0b09ca04a7b43248154c773704a5616"' in content
    assert 'secret_name = "PADIEM_GEMINI_API_KEY"' in content
    assert "PADIEM_GEMINI_API_KEY =" not in content
    # The declared binding must be the one the provider spec requires.
    assert 'GOOGLE_CREDENTIAL_BINDING = "PADIEM_GEMINI_API_KEY"' in provider
    import json as _json
    registry = _json.loads((Path(__file__).resolve().parent.parent / "app" / "pilot" / "b14_models.json").read_text(encoding="utf-8"))
    assert registry["providers"]["google"]["credential_binding_name"] == "PADIEM_GEMINI_API_KEY"
    # Preserve the original four owner-approved Google routes, but allow later
    # exact-ID additions without editing an unrelated Worker binding test.
    google_models = [m for m in registry["models"] if m["provider_id"] == "google"]
    google_ids = {m["id"] for m in google_models}
    assert {
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.5-flash-lite",
        "google/gemma-4-26b-a4b-it",
        "google/gemma-4-31b-it",
    } <= google_ids
    assert len(google_ids) == len(google_models)
    assert all(m["id"].startswith("google/") for m in google_models)


def test_worker_projects_every_enabled_platform_secret_registry_binding():
    """A declared Wrangler binding is unusable unless Worker explicitly
    collects and mirrors it into the application's environment.

    This checks ALL active providers, not a one-off Google-only literal.
    """
    import ast
    import json

    registry = json.loads(
        (WRANGLER_TOML.parent / "app" / "pilot" / "b14_models.json").read_text(
            encoding="utf-8"
        )
    )
    required = {
        entry["credential_binding_name"]
        for entry in registry["providers"].values()
        if entry["enabled"] and entry["credential_source"] == "platform_secret"
    }
    worker_ast = ast.parse(WORKER_SRC.read_text(encoding="utf-8"))
    assignments = [
        node for node in worker_ast.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_ENV_KEYS" for t in node.targets)
    ]
    assert len(assignments) == 1
    value = assignments[0].value
    assert isinstance(value, ast.Call)
    assert isinstance(value.func, ast.Name) and value.func.id == "frozenset"
    assert len(value.args) == 1
    allowlist = ast.literal_eval(value.args[0])
    assert required <= allowlist, (
        "Worker missing required provider Secret bindings: "
        + ", ".join(sorted(required - allowlist))
    )
    assert "PADIEM_GEMINI_API_KEY" in required
    assert "await collect_env_overrides(self.env, _ENV_KEYS)" in WORKER_SRC.read_text(
        encoding="utf-8"
    )
