from __future__ import annotations

import importlib.util
import json
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


def _load_mock_smoke_module():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / ".github/scripts/b62_cloudflare_mock_smoke.py"
    spec = importlib.util.spec_from_file_location("b62_cloudflare_mock_smoke_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mock_smoke_transport(*, live_enabled: bool):
    api_headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }

    def fake_request(url: str, *, method: str = "GET", payload: dict | None = None):
        if url.endswith("/health"):
            body = {
                "status": "ok",
                "app": "padiem-chat",
                "runtime": "mock",
                "b14_configured": False,
                "live_enabled": live_enabled,
                "deep_research_ready": False,
            }
            return 200, api_headers, json.dumps(body).encode("utf-8")
        if url.endswith("/api/chat"):
            body = {
                "runtime": "mock",
                "answer": "현재는 데모 모드이며 실제 모델을 호출하지 않았습니다.",
            }
            return 200, api_headers, json.dumps(body, ensure_ascii=False).encode("utf-8")
        return 200, {}, "Padiem Chat 무엇을 도와드릴까요".encode("utf-8")

    return fake_request


def test_mock_deploy_smoke_requires_http_live_enabled_false(monkeypatch, capsys):
    module = _load_mock_smoke_module()
    monkeypatch.setenv("B62_BASE_URL", "https://padiem-chat.example.test")
    monkeypatch.setattr(module, "request_with_retry", _mock_smoke_transport(live_enabled=False))

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "LIVE_ENABLED=false" in output
    assert "DEEP_RESEARCH_READY=false" in output
    assert "REAL_PROVIDER_CALLS=0" in output


def test_mock_deploy_smoke_fails_closed_if_http_reports_live_enabled(monkeypatch):
    module = _load_mock_smoke_module()
    monkeypatch.setenv("B62_BASE_URL", "https://padiem-chat.example.test")
    monkeypatch.setattr(module, "request_with_retry", _mock_smoke_transport(live_enabled=True))

    assert module.main() == 1
