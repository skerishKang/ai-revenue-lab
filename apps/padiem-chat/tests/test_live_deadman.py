from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.config import ConfigError, Settings
from app.main import create_app
from app.usage_gate import InMemoryUsageCounterStore
from app.worker_config import apply_live_deadman_switch, settings_from_worker_bindings

QUOTA_SALT = "b62-live-deadman-test-salt-not-a-real-secret-0001"


def test_live_switch_defaults_false_and_is_strict():
    assert Settings.from_values().live_enabled is False
    assert Settings.from_values(live_enabled=True).live_enabled is True
    assert Settings.from_values(live_enabled="TRUE").live_enabled is True
    assert Settings.from_values(live_enabled="false").live_enabled is False

    for bad in ("1", "yes", "on", "", None):
        with pytest.raises(ConfigError):
            Settings.from_values(live_enabled=bad)


def test_worker_binding_defaults_live_switch_false():
    settings = settings_from_worker_bindings({})
    assert settings.runtime_mode == "mock"
    assert settings.live_enabled is False


def test_deadman_downgrades_b14_to_mock_when_not_explicitly_armed():
    requested = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example",
        live_enabled="false",
    )

    effective = apply_live_deadman_switch(requested)

    assert requested.runtime_mode == "b14"
    assert requested.live_enabled is False
    assert effective.runtime_mode == "mock"
    assert effective.b14_base_url == "https://b14.example"
    assert effective.live_enabled is False


def test_deadman_preserves_b14_only_when_explicitly_armed():
    requested = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example",
        live_enabled="true",
    )
    effective = apply_live_deadman_switch(requested)
    assert effective.runtime_mode == "b14"
    assert effective.live_enabled is True


def test_live_switch_never_promotes_mock_to_b14():
    requested = Settings.from_values(runtime_mode="mock", live_enabled="true")
    effective = apply_live_deadman_switch(requested)
    assert effective.runtime_mode == "mock"


@pytest.mark.asyncio
async def test_deadman_health_stays_truthful_and_disables_deep_research():
    requested = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example",
        live_enabled="false",
        web_provider="mock",
        quota_salt=QUOTA_SALT,
    )
    effective = apply_live_deadman_switch(requested)
    app = create_app(effective, usage_store=InMemoryUsageCounterStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"] == "mock"
    assert body["b14_configured"] is True
    assert body["quota_store_bound"] is True
    assert body["live_abuse_gate_ready"] is True
    assert body["live_enabled"] is False
    assert body["deep_research_ready"] is False


@pytest.mark.asyncio
async def test_health_reports_live_only_when_switch_and_abuse_gate_are_ready():
    settings = apply_live_deadman_switch(
        Settings.from_values(
            runtime_mode="b14",
            b14_base_url="https://b14.example",
            live_enabled="true",
            quota_salt=QUOTA_SALT,
        )
    )
    app = create_app(settings, usage_store=InMemoryUsageCounterStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    body = response.json()
    assert body["runtime"] == "b14"
    assert body["live_abuse_gate_ready"] is True
    assert body["live_enabled"] is True


def test_worker_and_wrangler_wire_the_deadman_switch_before_bootstrap():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf-8")
    wrangler = (root / "wrangler.toml").read_text(encoding="utf-8")

    apply_line = "settings = apply_live_deadman_switch(settings_from_worker_bindings(self.env))"
    assert apply_line in worker
    assert worker.index(apply_line) < worker.index("create_app(settings=settings")
    assert 'PADIEM_CHAT_LIVE_ENABLED = "false"' in wrangler
