from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / ".github/scripts/b62_cloudflare_production_deploy_config.py"
    spec = importlib.util.spec_from_file_location("b62_cloudflare_production_deploy_config", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo_config(tmp_path: Path) -> Path:
    path = tmp_path / "wrangler.toml"
    path.write_text(
        'name = "padiem-chat"\n'
        'main = "worker.py"\n'
        'compatibility_date = "2026-08-25"\n'
        'compatibility_flags = ["python_workers"]\n\n'
        '[assets]\n'
        'directory = "static"\n'
        'binding = "ASSETS"\n',
        encoding="utf-8",
    )
    return path


def _bindings(r2: dict) -> list[dict]:
    return [
        {"type": "assets", "name": "ASSETS"},
        {"type": "service", "name": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform"},
        {"type": "service", "name": "IDENTITY_AUTHORITY_SERVICE", "service": "padiem-control-plane-identity"},
        {"type": "d1", "name": "PADIEM_CHAT_DB", "id": "702bb62b-36f5-41a0-973f-c4f663ee01e6"},
        r2,
        {"type": "plain_text", "name": "PADIEM_CHAT_RUNTIME_MODE", "text": "b14"},
        {"type": "plain_text", "name": "PADIEM_CHAT_LIVE_ENABLED", "text": "true"},
    ]


def _payload(bindings: list[dict]) -> dict:
    return {"success": True, "result": {"bindings": bindings}}


def test_live_r2_binding_is_preserved_into_generated_wrangler(tmp_path):
    module = _load_module()
    live = module.parse_live_bindings(
        _payload(
            _bindings(
                {
                    "type": "r2_bucket",
                    "name": "PADIEM_WORKSPACE_FILES",
                    "bucket_name": "padiem-workspace-files",
                }
            )
        )
    )

    config = module.build_production_config(
        live,
        _repo_config(tmp_path),
        "https://padiem-chat.charliekant.workers.dev",
    )

    assert '[[r2_buckets]]' in config
    assert 'binding = "PADIEM_WORKSPACE_FILES"' in config
    assert 'bucket_name = "padiem-workspace-files"' in config
    assert live["r2"][0]["name"] == "PADIEM_WORKSPACE_FILES"


def test_r2_binding_missing_bucket_name_fails_closed():
    module = _load_module()
    with pytest.raises(module.ProductionConfigError, match="has no bucket_name"):
        module.parse_live_bindings(
            _payload(_bindings({"type": "r2_bucket", "name": "PADIEM_WORKSPACE_FILES"}))
        )


def test_r2_binding_invalid_jurisdiction_fails_closed():
    module = _load_module()
    with pytest.raises(module.ProductionConfigError, match="unsupported jurisdiction"):
        module.parse_live_bindings(
            _payload(
                _bindings(
                    {
                        "type": "r2_bucket",
                        "name": "PADIEM_WORKSPACE_FILES",
                        "bucket_name": "padiem-workspace-files",
                        "jurisdiction": "moon",
                    }
                )
            )
        )


def test_unknown_binding_type_still_fails_closed():
    module = _load_module()
    with pytest.raises(module.ProductionConfigError, match="unsupported live binding type"):
        module.parse_live_bindings(
            _payload(_bindings({"type": "kv_namespace", "name": "UNEXPECTED"}))
        )
