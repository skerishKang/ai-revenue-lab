from __future__ import annotations

from pathlib import Path
import tomllib


APP_ROOT = Path(__file__).resolve().parents[1]


def _load_config():
    return tomllib.loads((APP_ROOT / "wrangler.toml").read_text(encoding="utf-8"))


def _service_bindings(config):
    return config.get("services", [])


def test_wrangler_is_service_binding_only_and_not_public() -> None:
    config = _load_config()

    assert config["name"] == "padiem-ai-engine"
    assert config["workers_dev"] is False
    assert "route" not in config
    assert "routes" not in config


def test_worker_config_declares_b14_service_binding() -> None:
    config = _load_config()
    bindings = _service_bindings(config)
    assert {"binding": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform"} in bindings


def test_worker_config_declares_control_plane_identity_binding() -> None:
    config = _load_config()
    bindings = _service_bindings(config)
    assert {"binding": "CONTROL_PLANE_IDENTITY", "service": "padiem-control-plane-identity"} in bindings


def test_control_plane_identity_target_is_canonical() -> None:
    config = _load_config()
    bindings = _service_bindings(config)
    cp = [b for b in bindings if b["binding"] == "CONTROL_PLANE_IDENTITY"]
    assert len(cp) == 1
    assert cp[0]["service"] == "padiem-control-plane-identity"


def test_no_duplicate_service_bindings() -> None:
    config = _load_config()
    bindings = _service_bindings(config)
    names = [b["binding"] for b in bindings]
    assert len(names) == len(set(names))


def test_existing_engine_config_regression_passes() -> None:
    config = _load_config()
    bindings = _service_bindings(config)
    assert {"binding": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform"} in bindings


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
