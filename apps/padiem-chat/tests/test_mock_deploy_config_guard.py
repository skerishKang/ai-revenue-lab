from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_guard_module():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / ".github/scripts/b62_cloudflare_mock_config_guard.py"
    spec = importlib.util.spec_from_file_location("b62_cloudflare_mock_config_guard_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_config(tmp_path: Path, vars_block: str, *, name: str = "padiem-chat") -> Path:
    path = tmp_path / "wrangler.toml"
    path.write_text(
        f'''name = "{name}"
main = "worker.py"

[vars]
{vars_block}
''',
        encoding="utf-8",
    )
    return path


def test_current_wrangler_passes_predeploy_mock_guard(capsys):
    module = _load_guard_module()
    repo_root = Path(__file__).resolve().parents[3]
    wrangler = repo_root / "apps/padiem-chat/wrangler.toml"

    assert module.validate_config(wrangler) == []
    assert module.main([str(wrangler)]) == 0
    output = capsys.readouterr().out
    assert "B62_MOCK_CONFIG_GUARD=PASS" in output
    assert "RUNTIME=mock" in output
    assert "LIVE_ENABLED=false" in output
    assert "PLAINTEXT_LIVE_OR_SECRET_VARS=0" in output


def test_guard_rejects_b14_runtime_before_deploy(tmp_path):
    module = _load_guard_module()
    path = _write_config(
        tmp_path,
        'PADIEM_CHAT_RUNTIME_MODE = "b14"\nPADIEM_CHAT_LIVE_ENABLED = "false"',
    )
    errors = module.validate_config(path)
    assert any("PADIEM_CHAT_RUNTIME_MODE" in error for error in errors)
    assert module.main([str(path)]) == 1


def test_guard_rejects_live_arm_before_deploy(tmp_path):
    module = _load_guard_module()
    path = _write_config(
        tmp_path,
        'PADIEM_CHAT_RUNTIME_MODE = "mock"\nPADIEM_CHAT_LIVE_ENABLED = "true"',
    )
    errors = module.validate_config(path)
    assert any("PADIEM_CHAT_LIVE_ENABLED" in error for error in errors)
    assert module.main([str(path)]) == 1


def test_guard_requires_explicit_live_false_string(tmp_path):
    module = _load_guard_module()
    missing = _write_config(tmp_path, 'PADIEM_CHAT_RUNTIME_MODE = "mock"')
    assert any("PADIEM_CHAT_LIVE_ENABLED" in error for error in module.validate_config(missing))

    boolean_dir = tmp_path / "boolean"
    boolean_dir.mkdir()
    boolean_value = _write_config(
        boolean_dir,
        'PADIEM_CHAT_RUNTIME_MODE = "mock"\nPADIEM_CHAT_LIVE_ENABLED = false',
    )
    assert any("string 'false'" in error for error in module.validate_config(boolean_value))


def test_guard_rejects_live_or_secret_values_in_plaintext_vars(tmp_path):
    module = _load_guard_module()
    for index, key in enumerate(sorted(module.FORBIDDEN_PLAINTEXT_VARS)):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        path = _write_config(
            case_dir,
            'PADIEM_CHAT_RUNTIME_MODE = "mock"\n'
            'PADIEM_CHAT_LIVE_ENABLED = "false"\n'
            f'{key} = "must-not-be-committed-here"',
        )
        errors = module.validate_config(path)
        assert any(key in error for error in errors)
        assert module.main([str(path)]) == 1


def test_guard_rejects_wrong_worker_identity(tmp_path):
    module = _load_guard_module()
    path = _write_config(
        tmp_path,
        'PADIEM_CHAT_RUNTIME_MODE = "mock"\nPADIEM_CHAT_LIVE_ENABLED = "false"',
        name="some-other-worker",
    )
    errors = module.validate_config(path)
    assert any("Worker name" in error for error in errors)
