from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
PUBLIC_URL = 'https://chat.padiem.net'


def _load_module():
    spec = importlib.util.spec_from_file_location('b62_cloudflare_production_deploy_config', ROOT / '.github/scripts/b62_cloudflare_production_deploy_config.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _settings_payload(bindings):
    return {'success': True, 'result': {'bindings': bindings}}


def _production_bindings():
    return [
        {'name': 'ASSETS', 'type': 'assets'},
        {'name': 'B14_SERVICE', 'type': 'service', 'service': 'platform'},
        {'name': 'PADIEM_CHAT_PUBLIC_BASE_URL', 'type': 'plain_text', 'text': PUBLIC_URL},
        {'name': 'PADIEM_CHAT_RUNTIME_MODE', 'type': 'plain_text', 'text': 'b14'},
        {'name': 'PADIEM_CHAT_LIVE_ENABLED', 'type': 'plain_text', 'text': 'true'},
        {'name': 'PADIEM_CHAT_QUOTA_SALT', 'type': 'secret_text'},
    ]


def _write_repo_config(tmp_path):
    p = tmp_path / 'wrangler.toml'
    p.write_text('''name = "padiem-chat"
main = "worker.py"
compatibility_date = "2026-08-25"
[assets]
binding = "ASSETS"
directory = "static"
[[services]]
binding = "B14_SERVICE"
service = "platform"
[version_metadata]
binding = "CF_VERSION_METADATA"
[secrets]
required = ["PADIEM_CHAT_QUOTA_SALT"]
[vars]
PADIEM_CHAT_RUNTIME_MODE = "mock"
PADIEM_CHAT_LIVE_ENABLED = "false"
''')
    return p


def _read_workflow():
    return (ROOT / '.github/workflows/b62-production-code-deploy-gate.yml').read_text()


def test_repository_binding_addition_is_not_silently_omitted(tmp_path):
    import tomllib
    m = _load_module(); live = m.parse_live_bindings(_settings_payload(_production_bindings()))
    output = m.build_production_config(live, _write_repo_config(tmp_path), PUBLIC_URL)
    config = tomllib.loads(output)
    assert config['version_metadata']['binding'] == 'CF_VERSION_METADATA'
    assert config['vars']['PADIEM_CHAT_RUNTIME_MODE'] == 'b14'
    assert config['vars']['PADIEM_CHAT_LIVE_ENABLED'] == 'true'
    assert config['secrets']['required'] == ['PADIEM_CHAT_QUOTA_SALT']


def test_repository_targets_are_used_instead_of_live_targets(tmp_path, capsys):
    import tomllib
    m = _load_module(); bindings = _production_bindings(); bindings[1]['service'] = 'old-private-target'
    output = m.build_production_config(m.parse_live_bindings(_settings_payload(bindings)), _write_repo_config(tmp_path), PUBLIC_URL)
    assert tomllib.loads(output)['services'][0]['service'] == 'platform'
    logged = capsys.readouterr().out
    assert 'changed' in logged and 'B14_SERVICE' in logged
    assert 'old-private-target' not in logged


def test_removal_blocked_unless_explicitly_allowed(tmp_path):
    m = _load_module(); bindings = _production_bindings() + [{'name': 'OLD', 'type': 'browser'}]
    live = m.parse_live_bindings(_settings_payload(bindings)); repo = _write_repo_config(tmp_path)
    with pytest.raises(m.BindingAuthorityError, match='allow_binding_removal'):
        m.build_production_config(live, repo, PUBLIC_URL)
    assert '[browser]' not in m.build_production_config(live, repo, PUBLIC_URL, allow_binding_removal=True)


def test_vars_preserved_added_changed_removed_without_value_output(tmp_path, capsys):
    import tomllib
    m = _load_module(); bindings = _production_bindings() + [{'name': 'PRIVATE_GUARD', 'type': 'plain_text', 'text': 'guard-value-never-log'}]
    live = m.parse_live_bindings(_settings_payload(bindings)); repo = _write_repo_config(tmp_path)
    with repo.open('a') as f: f.write('NEW_FLAG = "new-value-never-log"\n')
    config = tomllib.loads(m.build_production_config(live, repo, PUBLIC_URL, set_var={'PRIVATE_GUARD': 'changed-value-never-log'}))
    assert config['vars']['PRIVATE_GUARD'] == 'changed-value-never-log'
    assert config['vars']['NEW_FLAG'] == 'new-value-never-log'
    with pytest.raises(m.ProductionConfigError):
        m.build_production_config(live, repo, PUBLIC_URL, set_var={'PRIVATE_GUARD': None})
    config = tomllib.loads(m.build_production_config(live, repo, PUBLIC_URL, allow_binding_removal=True, set_var={'PRIVATE_GUARD': None}))
    assert 'PRIVATE_GUARD' not in config['vars']
    assert 'never-log' not in capsys.readouterr().out


def test_all_repository_d1_ids_are_validated(tmp_path):
    m = _load_module(); repo = _write_repo_config(tmp_path)
    with repo.open('a') as f: f.write('\n[[d1_databases]]\nbinding="DB"\ndatabase_id="not-a-uuid"\n')
    with pytest.raises(ValueError):
        m.build_production_config(m.parse_live_bindings(_settings_payload(_production_bindings())), repo, PUBLIC_URL)


@pytest.mark.parametrize('value', [0, [], {'secret': 'value'}])
def test_explicit_variable_changes_have_closed_value_types(tmp_path, value):
    m = _load_module()
    with pytest.raises(m.ProductionConfigError):
        m.build_production_config(m.parse_live_bindings(_settings_payload(_production_bindings())), _write_repo_config(tmp_path), PUBLIC_URL, set_var={'FLAG': value})


def test_cli_errors_never_echo_private_event_or_source_values(tmp_path, capsys):
    m = _load_module(); repo = _write_repo_config(tmp_path); live = tmp_path / 'live.json'; event = tmp_path / 'event.json'
    live.write_text(json.dumps(_settings_payload(_production_bindings())))
    event.write_text(json.dumps({'inputs': {'set_var': '{"FLAG": "private-value-never-log" broken'}}))
    assert m.main(['--settings', str(live), '--repo-config', str(repo), '--public-base-url', PUBLIC_URL, '--output', str(tmp_path/'out'), '--dispatch-event', str(event)]) == 1
    log = capsys.readouterr()
    assert 'private-value-never-log' not in log.out + log.err


def test_secret_payloads_are_never_serialized(tmp_path):
    m = _load_module(); rows = _production_bindings(); rows[-1]['text'] = 'secret-value-must-not-leave-api-envelope'
    output = m.build_production_config(m.parse_live_bindings(_settings_payload(rows)), _write_repo_config(tmp_path), PUBLIC_URL)
    assert 'secret-value-must-not-leave-api-envelope' not in output
