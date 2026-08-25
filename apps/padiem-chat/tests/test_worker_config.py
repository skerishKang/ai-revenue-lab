from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ConfigError, Settings
from app.worker_config import (
    BASE_SECURITY_HEADERS,
    D1_BINDING_NAME,
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
    monkeypatch.delenv("PADIEM_CHAT_WEB_PROVIDER", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("PADIEM_CHAT_AUTH_MODE", raising=False)
    monkeypatch.delenv("PADIEM_CHAT_QUOTA_SALT", raising=False)
    assert Settings.from_env() == direct


def test_worker_bindings_default_to_mock_web_off_auth_off_with_finite_limits():
    settings = settings_from_worker_bindings({})
    assert settings.runtime_mode == "mock"
    assert settings.b14_base_url is None
    assert settings.timeout_seconds == 20.0
    assert settings.web_provider == "off"
    assert settings.firecrawl_api_key is None
    assert settings.web_timeout_seconds == 15.0
    assert settings.auth_mode == "off"
    assert settings.public_base_url is None
    assert settings.google_client_id is None
    assert settings.google_client_secret is None
    assert settings.session_secret is None
    assert settings.quota_salt is None
    assert settings.anonymous_burst_limit == 4
    assert settings.anonymous_daily_limit == 20
    assert settings.user_burst_limit == 8
    assert settings.user_daily_limit == 100
    assert settings.global_daily_limit == 1000


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
    assert settings.runtime_mode == "b14"
    assert settings.b14_base_url == "https://b14.example"
    assert settings.timeout_seconds == 15.0
    assert settings.quota_salt is None


def test_server_only_worker_bindings_and_google_config_validation():
    assert WORKER_BINDING_NAMES == {
        "PADIEM_CHAT_RUNTIME_MODE",
        "PADIEM_CHAT_B14_BASE_URL",
        "PADIEM_CHAT_TIMEOUT_SECONDS",
        "PADIEM_CHAT_WEB_PROVIDER",
        "FIRECRAWL_API_KEY",
        "PADIEM_CHAT_WEB_TIMEOUT_SECONDS",
        "PADIEM_CHAT_AUTH_MODE",
        "PADIEM_CHAT_PUBLIC_BASE_URL",
        "PADIEM_CHAT_GOOGLE_CLIENT_ID",
        "PADIEM_CHAT_GOOGLE_CLIENT_SECRET",
        "PADIEM_CHAT_SESSION_SECRET",
        "PADIEM_CHAT_SESSION_MAX_AGE_SECONDS",
        "PADIEM_CHAT_QUOTA_SALT",
        "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT",
        "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT",
        "PADIEM_CHAT_USER_BURST_LIMIT",
        "PADIEM_CHAT_USER_DAILY_LIMIT",
        "PADIEM_CHAT_GLOBAL_DAILY_LIMIT",
    }
    assert D1_BINDING_NAME == "PADIEM_CHAT_DB"
    joined = " ".join(sorted(WORKER_BINDING_NAMES)).upper()
    assert "OPENROUTER" not in joined
    assert "BUSINESS14_PROVIDER_KEY" not in joined
    assert "FIRECRAWL_API_KEY" in WORKER_BINDING_NAMES

    with pytest.raises(ConfigError):
        settings_from_worker_bindings({"PADIEM_CHAT_WEB_PROVIDER": "firecrawl"})
    configured = settings_from_worker_bindings({
        "PADIEM_CHAT_WEB_PROVIDER": "firecrawl",
        "FIRECRAWL_API_KEY": "fc-server-only-test",
        "PADIEM_CHAT_WEB_TIMEOUT_SECONDS": "11",
    })
    assert configured.web_provider == "firecrawl"
    assert configured.firecrawl_api_key == "fc-server-only-test"
    assert configured.web_timeout_seconds == 11.0
    assert "fc-server-only-test" not in repr(configured)

    google = settings_from_worker_bindings({
        "PADIEM_CHAT_AUTH_MODE": "google",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.example.test",
        "PADIEM_CHAT_GOOGLE_CLIENT_ID": "client-id",
        "PADIEM_CHAT_GOOGLE_CLIENT_SECRET": "unit-test-secret",
        "PADIEM_CHAT_SESSION_SECRET": "phase9-session-secret-not-a-real-credential-000000",
        "PADIEM_CHAT_SESSION_MAX_AGE_SECONDS": "3600",
    })
    assert google.auth_mode == "google"
    assert google.public_base_url == "https://chat.example.test"
    assert "unit-test-secret" not in repr(google)
    assert "phase9-session-secret" not in repr(google)


def test_quota_config_is_server_owned_bounded_and_secret_redacted():
    salt = "quota-salt-not-a-real-secret-01234567890123456789"
    settings = settings_from_worker_bindings({
        "PADIEM_CHAT_QUOTA_SALT": salt,
        "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT": "3",
        "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT": "17",
        "PADIEM_CHAT_USER_BURST_LIMIT": "7",
        "PADIEM_CHAT_USER_DAILY_LIMIT": "91",
        "PADIEM_CHAT_GLOBAL_DAILY_LIMIT": "777",
    })
    assert settings.quota_salt == salt
    assert settings.anonymous_burst_limit == 3
    assert settings.anonymous_daily_limit == 17
    assert settings.user_burst_limit == 7
    assert settings.user_daily_limit == 91
    assert settings.global_daily_limit == 777
    assert salt not in repr(settings)

    with pytest.raises(ConfigError):
        settings_from_worker_bindings({"PADIEM_CHAT_QUOTA_SALT": "too-short"})
    for key in (
        "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT",
        "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT",
        "PADIEM_CHAT_USER_BURST_LIMIT",
        "PADIEM_CHAT_USER_DAILY_LIMIT",
        "PADIEM_CHAT_GLOBAL_DAILY_LIMIT",
    ):
        with pytest.raises(ConfigError):
            settings_from_worker_bindings({key: "0"})
        with pytest.raises(ConfigError):
            settings_from_worker_bindings({key: "unlimited"})


def test_security_headers_and_api_auth_no_store():
    assert BASE_SECURITY_HEADERS == {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
    }
    assert response_headers_for_path("/") == BASE_SECURITY_HEADERS
    assert response_headers_for_path("/api/chat")["Cache-Control"] == "no-store"
    assert response_headers_for_path("/api/auth/status")["Cache-Control"] == "no-store"
    assert response_headers_for_path("/auth/google/callback")["Cache-Control"] == "no-store"
    assert response_headers_for_path("/health")["Cache-Control"] == "no-store"


def test_worker_package_is_mock_first_static_bound_and_no_fake_d1_id():
    root = Path(__file__).resolve().parents[1]
    wrangler = (root / "wrangler.toml").read_text(encoding="utf-8")
    worker = (root / "worker.py").read_text(encoding="utf-8")
    assert 'name = "padiem-chat"' in wrangler
    assert 'main = "worker.py"' in wrangler
    assert 'compatibility_flags = ["python_workers"]' in wrangler
    assert 'directory = "static"' in wrangler
    assert 'PADIEM_CHAT_RUNTIME_MODE = "mock"' in wrangler
    assert "database_id" not in wrangler
    assert "settings_from_worker_bindings(self.env)" in worker
    assert "D1HistoryStore" in worker and "PADIEM_CHAT_DB" not in worker
    assert "D1UsageCounterStore" in worker
    assert "usage_store=usage_store" in worker
    assert "OPENROUTER_API_KEY" not in worker
    assert "PADIEM_CHAT_B14_BASE_URL" not in worker
    assert "FIRECRAWL_API_KEY" not in worker
    assert "GOOGLE_CLIENT_SECRET" not in worker


def test_phase1_css_blob_content_remains_byte_equal():
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    assert (root / "static/styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()
