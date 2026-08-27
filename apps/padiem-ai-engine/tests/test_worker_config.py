from __future__ import annotations

from pathlib import Path
import tomllib


APP_ROOT = Path(__file__).resolve().parents[1]


def test_wrangler_is_service_binding_only_and_not_public() -> None:
    config = tomllib.loads((APP_ROOT / "wrangler.toml").read_text(encoding="utf-8"))

    assert config["name"] == "padiem-ai-engine"
    assert config["workers_dev"] is False
    assert "route" not in config
    assert "routes" not in config
    assert config["services"] == [
        {
            "binding": "B14_SERVICE",
            "service": "ai-revenue-korean-ai-platform",
        }
    ]


def test_worker_source_has_no_browser_cors_or_public_b14_fallback() -> None:
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    transport = (APP_ROOT / "app" / "cloudflare_transport.py").read_text(
        encoding="utf-8"
    )

    assert "Access-Control-Allow-Origin" not in source
    assert "workers.dev" not in source
    assert "workers.dev" not in transport
    assert 'B14_SERVICE_BINDING_NAME = "B14_SERVICE"' in source
    assert 'B14_INTERNAL_ORIGIN = "https://b14.internal"' in transport
