import importlib.util
import json
import sys
from pathlib import Path
import subprocess
import tomllib
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.github/scripts'))
from b62_repo_binding_authority import binding_diff, inventory, index, verify_expected, BindingAuthorityError
from b62_cloudflare_production_deploy_config import parse_live_bindings, production_plan, build_production_config


def test_actual_declared_inventory_adds_only_the_reviewed_unserved_variable(capsys):
    rows = json.loads((ROOT/'.github/tests/fixtures/b62_served_binding_inventory_20261026.json').read_text())
    for row in rows:
        if row['type'] == 'plain_text': row['text'] = '<synthetic-private-value>'
    live = parse_live_bindings({'success': True, 'result': {'bindings': rows}})
    repo_path = ROOT / 'apps/padiem-chat/wrangler.toml'
    expected, values = production_plan(live, tomllib.loads(repo_path.read_text()))
    # CF_VERSION_METADATA went live with the 95c9a36d deploy, so it is no longer
    # an addition. What remains is exactly one reviewed, declared-but-unserved
    # variable: #5919 adds PC_AGENT_INSTALL_URL to [vars] with an empty value,
    # which the pairing handoff reads as "not ready" until deploy injects the
    # real https installer URL. The reviewed inventory is the set production is
    # answering with today, so a declared new variable must appear here as this
    # single named addition - never as an unexplained drift, and never as a
    # silent removal of something that is serving traffic.
    assert binding_diff(index(rows), expected) == {
        'added': [{'name': 'PC_AGENT_INSTALL_URL', 'type': 'plain_text'}],
        'removed': [], 'changed': []}
    assert '<synthetic-private-value>' not in capsys.readouterr().out


def test_binding_exact_readback_detects_target_and_type_changes():
    expected = index([{'name': 'SERVICE', 'type': 'service', 'service': 'expected'}])
    verify_expected(expected, expected)
    for entry in [{'name': 'SERVICE', 'type': 'service', 'service': 'different'}, {'name': 'SERVICE', 'type': 'browser'}]:
        with pytest.raises(BindingAuthorityError): verify_expected(expected, index([entry]))


def test_rollback_job_and_automatic_rollback_are_unchanged():
    import hashlib, re
    after = (ROOT/'.github/workflows/b62-production-code-deploy-gate.yml').read_text()
    assert hashlib.sha256(after.split('\n  rollback-production-code:',1)[1].encode()).hexdigest() == 'a2d44aedc2aee11e30677b8adf3b86d77aaee372a5e6f2ed54901a6cf0ab3a4f'
    assert hashlib.sha256(re.search(r'      - name: Auto-rollback.*?(?=\n      - name:)',after,re.S).group().encode()).hexdigest() == '31e7e332d6cffb63a25db824b7134c5725a8223f2b3e778c9307ed11b9df5dce'


def test_workflow_uses_private_event_input_and_keeps_exact_main_and_d1_checks():
    text = (ROOT/'.github/workflows/b62-production-code-deploy-gate.yml').read_text()
    w = yaml.safe_load(text); trigger = w.get('on', w.get(True)); inputs = trigger['workflow_dispatch']['inputs']
    assert 'allow_binding_removal' in inputs and inputs['allow_binding_removal']['default'] is False
    assert 'set_var' in inputs and 'inputs.set_var' not in text
    assert not any(n.startswith('attach_') for n in inputs)
    assert 'activate_claw_public_search' not in inputs
    assert '--dispatch-event "${GITHUB_EVENT_PATH}"' in text
    assert 'PREMUTATION_EXACT_MAIN_SHA=PASS' in text
    assert 'B62_D1_MIGRATION_008_SCHEMA=EXACT' in text
    assert '--verify-served' in text


def test_deploy_output_redaction_never_emits_guard_values():
    from b62_redact_deploy_output import redact
    variables = {'PRIVATE_GUARD': 'guard-abcdef-123456', 'MODE': 'b14'}
    assert 'guard-abcdef-123456' not in redact('diagnostic guard-abcdef-123456\n', variables)
    assert 'guard-abcdef-123456' not in redact('env.PRIVATE_GUARD ("guard-abcdef-123456")\n', variables)
    assert 'b14' not in redact('mode b14\n', variables)


def test_d1_schema_probes_use_repository_planned_identifiers():
    text = (ROOT/'.github/workflows/b62-production-code-deploy-gate.yml').read_text()
    deploy = yaml.safe_load(text)['jobs']['deploy-production-code']['steps']
    generate = next(i for i,s in enumerate(deploy) if s.get('name')=='Generate exact production config from live settings')
    probes = [(i,s) for i,s in enumerate(deploy) if 'db_id=' in s.get('run','')]
    assert probes
    for i,step in probes:
        assert generate < i
        assert 'b62-planned-d1-bindings.json' in step['run']
        assert 'b62-settings-before.json' not in step['run']


def test_repository_route_table_cannot_capture_worker_build_fields():
    config = tomllib.loads((ROOT/'apps/padiem-chat/wrangler.toml').read_text())
    assert config['base_dir'] == '.b66-worker-src'
    assert config['routes'] == [{'pattern': 'chat.padiem.net', 'custom_domain': True}]


def test_normal_deploy_has_no_legacy_live_target_or_variable_prerequisite():
    text = (ROOT/'.github/workflows/b62-production-code-deploy-gate.yml').read_text()
    steps = yaml.safe_load(text)['jobs']['deploy-production-code']['steps']
    legacy = next(s for s in steps if 'deploy-prereq' in s.get('run', ''))
    assert legacy['if'] == "${{ inputs.mode == 'recover_p01_sse_off' }}"
