from __future__ import annotations

import importlib.util
import json
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


def _settings_payload(bindings: list[dict]) -> dict:
    return {"success": True, "result": {"bindings": bindings}}


def _production_bindings() -> list[dict]:
    return [
        {"type": "assets", "name": "ASSETS"},
        {"type": "service", "name": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform"},
        {"type": "service", "name": "IDENTITY_AUTHORITY_SERVICE", "service": "padiem-control-plane-identity"},
        {"type": "d1", "name": "PADIEM_CHAT_DB", "id": "702bb62b-36f5-41a0-973f-c4f663ee01e6"},
        {"type": "secret_text", "name": "PADIEM_CHAT_QUOTA_SALT"},
        {"type": "plain_text", "name": "PADIEM_CHAT_RUNTIME_MODE", "text": "b14"},
        {"type": "plain_text", "name": "PADIEM_CHAT_LIVE_ENABLED", "text": "true"},
        {"type": "plain_text", "name": "PADIEM_CHAT_TIMEOUT_SECONDS", "text": "20"},
    ]


def _write_repo_config(tmp_path: Path) -> Path:
    path = tmp_path / "wrangler.toml"
    path.write_text(
        'name = "padiem-chat"\n'
        'main = "worker.py"\n'
        'compatibility_date = "2026-08-25"\n'
        'compatibility_flags = ["python_workers"]\n'
        "\n"
        "[assets]\n"
        'directory = "static"\n'
        'binding = "ASSETS"\n'
        "\n"
        "[vars]\n"
        'PADIEM_CHAT_RUNTIME_MODE = "mock"\n'
        'PADIEM_CHAT_LIVE_ENABLED = "false"\n',
        encoding="utf-8",
    )
    return path


PUBLIC_URL = "https://padiem-chat.charliekant.workers.dev"


def test_live_dump_is_authority_and_repo_mock_vars_do_not_leak(tmp_path):
    module = _load_module()
    live = module.parse_live_bindings(_settings_payload(_production_bindings()))
    config = module.build_production_config(live, _write_repo_config(tmp_path), PUBLIC_URL)

    assert 'PADIEM_CHAT_RUNTIME_MODE = "b14"' in config
    assert 'PADIEM_CHAT_LIVE_ENABLED = "true"' in config
    assert f'PADIEM_CHAT_PUBLIC_BASE_URL = "{PUBLIC_URL}"' in config
    assert 'service = "padiem-control-plane-identity"' in config
    assert 'service = "ai-revenue-korean-ai-platform"' in config
    assert 'database_id = "702bb62b-36f5-41a0-973f-c4f663ee01e6"' in config
    assert 'directory = "static"' in config
    assert "compatibility_flags = [" in config


def test_secret_binding_values_are_never_emitted(tmp_path):
    module = _load_module()
    live = module.parse_live_bindings(_settings_payload(_production_bindings()))
    config = module.build_production_config(live, _write_repo_config(tmp_path), PUBLIC_URL)

    assert "PADIEM_CHAT_QUOTA_SALT" not in config
    assert "secret_text" not in config


def test_unsupported_live_binding_type_fails_closed(tmp_path):
    module = _load_module()
    bindings = _production_bindings() + [{"type": "kv_namespace", "name": "MY_KV"}]
    with pytest.raises(module.ProductionConfigError, match="unsupported live binding type"):
        module.parse_live_bindings(_settings_payload(bindings))


def test_mock_runtime_in_live_settings_aborts(tmp_path):
    module = _load_module()
    bindings = [
        b for b in _production_bindings()
        if b.get("name") != "PADIEM_CHAT_RUNTIME_MODE"
    ] + [{"type": "plain_text", "name": "PADIEM_CHAT_RUNTIME_MODE", "text": "mock"}]
    live = module.parse_live_bindings(_settings_payload(bindings))
    with pytest.raises(module.ProductionConfigError, match="runtime mode is mock"):
        module.build_production_config(live, _write_repo_config(tmp_path), PUBLIC_URL)


def test_public_base_url_drift_aborts(tmp_path):
    module = _load_module()
    bindings = _production_bindings() + [
        {"type": "plain_text", "name": "PADIEM_CHAT_PUBLIC_BASE_URL", "text": "https://elsewhere.example.test"}
    ]
    live = module.parse_live_bindings(_settings_payload(bindings))
    with pytest.raises(module.ProductionConfigError, match="drift"):
        module.build_production_config(live, _write_repo_config(tmp_path), PUBLIC_URL)


def test_duplicate_binding_names_fail_closed():
    module = _load_module()
    bindings = _production_bindings() + [
        {"type": "service", "name": "B14_SERVICE", "service": "other-worker"}
    ]
    with pytest.raises(module.ProductionConfigError, match="duplicate binding names"):
        module.parse_live_bindings(_settings_payload(bindings))


def test_missing_identity_service_still_deploys_what_live_has(tmp_path):
    module = _load_module()
    bindings = [b for b in _production_bindings() if b.get("name") != "IDENTITY_AUTHORITY_SERVICE"]
    live = module.parse_live_bindings(_settings_payload(bindings))
    config = module.build_production_config(live, _write_repo_config(tmp_path), PUBLIC_URL)
    assert "IDENTITY_AUTHORITY_SERVICE" not in config
    assert config.count("[[services]]") == 1


def test_main_cli_writes_output_and_reports_zero_secret_reads(tmp_path, capsys):
    module = _load_module()
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(_settings_payload(_production_bindings())), encoding="utf-8")
    output_path = tmp_path / "wrangler.production.generated.toml"

    rc = module.main([
        "--settings", str(settings_path),
        "--repo-config", str(_write_repo_config(tmp_path)),
        "--public-base-url", PUBLIC_URL,
        "--output", str(output_path),
    ])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "B62_PRODUCTION_CONFIG_GENERATED=PASS" in printed
    assert "SECRET_VALUES_READ=0" in printed
    assert "SECRET_VALUES_EMITTED=0" in printed
    assert "PADIEM_CHAT_PUBLIC_BASE_URL_STATE=injected" in printed
    assert output_path.exists()


def test_main_cli_refuses_existing_output(tmp_path, capsys):
    module = _load_module()
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(_settings_payload(_production_bindings())), encoding="utf-8")
    output_path = tmp_path / "wrangler.production.generated.toml"
    output_path.write_text("existing", encoding="utf-8")

    rc = module.main([
        "--settings", str(settings_path),
        "--repo-config", str(_write_repo_config(tmp_path)),
        "--public-base-url", PUBLIC_URL,
        "--output", str(output_path),
    ])
    assert rc == 1
    assert output_path.read_text(encoding="utf-8") == "existing"
