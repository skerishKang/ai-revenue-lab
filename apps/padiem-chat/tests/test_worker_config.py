from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ConfigError, Settings
from app.worker_config import (
    BASE_SECURITY_HEADERS,
    WORKER_BINDING_NAMES,
    response_headers_for_path,
    settings_from_worker_bindings,
)


def test_settings_from_values_and_env_share_validation(monkeypatch):
    direct = Settings.from_values("b14", "https://example.com/root/", "12")
    assert direct == Settings(runtime_mode="b14", b14_base_url="https://example.com/root", timeout_seconds=12.0)

    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://example.com/root/")
    monkeypatch.setenv("PADIEM_CHAT_TIMEOUT_SECONDS", "12")
    assert Settings.from_env() == direct


def test_worker_bindings_default_to_mock():
    settings = settings_from_worker_bindings({})
    assert settings.runtime_mode == "mock"
    assert settings.b14_base_url is None
    assert settings.timeout_seconds == 20.0


def test_worker_b14_mode_requires_valid_fixed_url():
    with pytest.raises(ConfigError):
        settings_from_worker_bindings({"PADIEM_CHAT_RUNTIME_MODE": "b14"})
    with pytest.raises(ConfigError):
        settings_from_worker_bindings({
            "PADIEM_CHAT_RUNTIME_MODE": "b14",
            "PADIEM_CHAT_B14_BASE_URL": "https://user:pw@example.com",
        })

    settings = settings_from_worker_bindings({
        "PADIEM_CHAT_RUNTIME_MODE": "b14",
        "PADIEM_CHAT_B14_BASE_URL": "https://b14.example/",
        "PADIEM_CHAT_TIMEOUT_SECONDS": "15",
    })
    assert settings == Settings(runtime_mode="b14", b14_base_url="https://b14.example", timeout_seconds=15.0)


def test_worker_binding_contract_contains_no_provider_secret():
    assert WORKER_BINDING_NAMES == {
        "PADIEM_CHAT_RUNTIME_MODE",
        "PADIEM_CHAT_B14_BASE_URL",
        "PADIEM_CHAT_TIMEOUT_SECONDS",
    }
    joined = " ".join(sorted(WORKER_BINDING_NAMES)).upper()
    assert "OPENROUTER" not in joined
    assert "API_KEY" not in joined
    assert "PROVIDER_KEY" not in joined


def test_security_headers_and_api_no_store():
    assert BASE_SECURITY_HEADERS == {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    }
    assert response_headers_for_path("/") == BASE_SECURITY_HEADERS
    api = response_headers_for_path("/api/chat")
    health = response_headers_for_path("/health")
    assert api["Cache-Control"] == "no-store"
    assert health["Cache-Control"] == "no-store"


def test_worker_package_is_mock_first_and_static_assets_are_bound():
    root = Path(__file__).resolve().parents[1]
    wrangler = (root / "wrangler.toml").read_text(encoding="utf-8")
    worker = (root / "worker.py").read_text(encoding="utf-8")
    assert 'name = "padiem-chat"' in wrangler
    assert 'main = "worker.py"' in wrangler
    assert 'compatibility_flags = ["python_workers"]' in wrangler
    assert 'directory = "static"' in wrangler
    assert 'PADIEM_CHAT_RUNTIME_MODE = "mock"' in wrangler
    assert "settings_from_worker_bindings(self.env)" in worker
    assert "create_app(settings=settings)" in worker
    assert "OPENROUTER_API_KEY" not in worker
    assert "PADIEM_CHAT_B14_BASE_URL" not in worker


def test_phase1_css_blob_content_remains_byte_equal():
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    assert (root / "static/styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()
