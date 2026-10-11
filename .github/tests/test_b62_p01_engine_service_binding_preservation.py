"""S0-C: the existing B62 production config generator preserves the live
``P01_ENGINE_SERVICE`` -> ``padiem-ai-engine`` service binding (#3199).

Uses the existing generator only (no second production config generator) and
exercises it through its public functions, so the live settings dump stays the
single authority for bindings.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b62_cloudflare_production_deploy_config.py"
REPO_CONFIG = ROOT / "apps" / "padiem-chat" / "wrangler.toml"

spec = importlib.util.spec_from_file_location("b62_p01_preservation", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

REPO = tomllib.loads(REPO_CONFIG.read_text(encoding="utf-8"))
ASSETS_BINDING = REPO["assets"]["binding"]
PUBLIC_BASE_URL = "https://padiem.example"
P01 = {"name": "P01_ENGINE_SERVICE", "type": "service", "service": "padiem-ai-engine"}


def _payload(*, services=None, extras=None):
    bindings = [{"name": ASSETS_BINDING, "type": "assets"}]
    # the generator requires the reviewed plain-text vars to be present live,
    # with the live arm enabled and a non-mock runtime mode
    var_values = {
        "PADIEM_CHAT_LIVE_ENABLED": "true",
        "PADIEM_CHAT_RUNTIME_MODE": "live",
        mod.PUBLIC_BASE_URL_VAR: PUBLIC_BASE_URL,
    }
    bindings.extend(
        {"name": name, "type": "plain_text", "text": var_values.get(name, "test")}
        for name in sorted(mod.REQUIRED_VARS)
    )
    if mod.PUBLIC_BASE_URL_VAR not in mod.REQUIRED_VARS:
        # the deploy never injects the public origin: it must already be exact live
        bindings.append(
            {"name": mod.PUBLIC_BASE_URL_VAR, "type": "plain_text", "text": PUBLIC_BASE_URL}
        )
    bindings.extend(services or [])
    bindings.extend(extras or [])
    return {"success": True, "result": {"bindings": bindings}}


def _build(payload):
    live = mod.parse_live_bindings(payload)
    config = mod.build_production_config(live, REPO_CONFIG, PUBLIC_BASE_URL)
    mod.verify_mutation_zero(config, live)
    return config


def test_live_p01_engine_service_binding_is_preserved_by_the_generator() -> None:
    config = _build(_payload(services=[P01]))

    assert "[[services]]" in config
    assert 'binding = "P01_ENGINE_SERVICE"' in config
    assert 'service = "padiem-ai-engine"' in config


def test_unrelated_bindings_are_preserved_alongside_p01() -> None:
    other = {"name": "IDENTITY_AUTHORITY_SERVICE", "type": "service", "service": "padiem-control-plane-identity"}
    config = _build(_payload(services=[other, P01]))

    assert 'binding = "IDENTITY_AUTHORITY_SERVICE"' in config
    assert 'service = "padiem-control-plane-identity"' in config
    assert 'binding = "P01_ENGINE_SERVICE"' in config
    assert 'service = "padiem-ai-engine"' in config


def test_duplicate_binding_names_are_rejected() -> None:
    payload = _payload(services=[P01, dict(P01)])
    with pytest.raises(mod.ProductionConfigError):
        mod.parse_live_bindings(payload)


def test_unsupported_binding_type_is_rejected() -> None:
    payload = _payload(extras=[{"name": "WEIRD", "type": "not_a_binding_type"}])
    with pytest.raises(mod.ProductionConfigError):
        mod.parse_live_bindings(payload)


def test_missing_assets_binding_is_rejected() -> None:
    live = mod.parse_live_bindings(_payload(services=[P01]))
    config = mod.build_production_config(live, REPO_CONFIG, PUBLIC_BASE_URL)
    # the assets binding is required by the repository contract
    assert 'binding = "' + ASSETS_BINDING + '"' in config
    no_assets = mod.parse_live_bindings({"success": True, "result": {"bindings": [P01]}})
    with pytest.raises(mod.ProductionConfigError):
        mod.build_production_config(no_assets, REPO_CONFIG, PUBLIC_BASE_URL)


def test_no_second_production_config_generator() -> None:
    scripts = ROOT / ".github" / "scripts"
    generators = sorted(path.name for path in scripts.glob("*production_deploy_config*.py"))
    assert generators == ["b62_cloudflare_production_deploy_config.py"]
