import importlib.util
import sys
import unittest
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location('preflight', root / 'padiem_auth_update_preflight.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
version = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
base = {'status': 'approved', 'bindings': [{'name': 'IDENTITY_AUTHORITY', 'type': 'service', 'service': 'padiem-control-plane-identity'}, {'name': 'AUTH_STATE', 'type': 'durable_object_namespace', 'class_name': 'AuthStateObject'}]}
config = {'name': 'padiem-auth', 'services': [{'binding': 'IDENTITY_AUTHORITY', 'service': 'padiem-control-plane-identity'}], 'durable_objects': {'bindings': [{'name': 'AUTH_STATE', 'class_name': 'AuthStateObject'}]}, 'migrations': [{'tag': 'v1', 'new_sqlite_classes': ['AuthStateObject']}]}
class Check(unittest.TestCase):
    def test_config_rejects_target_change_and_vars(self):
        m.validate_config(config, base)
        with self.assertRaises(ValueError): m.validate_config({**config, 'vars': {'X': 'bad'}}, base)
        with self.assertRaises(ValueError): m.validate_config({**config, 'services': []}, base)
    def test_split_or_changed_active_version_is_rejected(self):
        m.verify_deployment([{'created_on': '2026-01-01', 'versions': [{'version_id': version, 'percentage': 100}]}], version)
        with self.assertRaises(ValueError): m.verify_deployment([{'versions': [{'version_id': version, 'percentage': 50}]}], version)
        with self.assertRaises(ValueError): m.verify_deployment([], version)

    def test_real_wrangler_config_path_and_secret_var_override_rejected(self):
        import hashlib
        import tomllib
        root = Path(__file__).resolve().parents[2]
        with (root / 'apps/padiem-auth/wrangler.toml').open('rb') as stream:
            actual = tomllib.load(stream)
        baseline = {'status': 'approved', 'bindings': []}
        for svc in actual.get('services', []):
            baseline['bindings'].append({'name': svc['binding'], 'type': 'service',
                                         'service': svc['service']})
        for item in actual.get('durable_objects', {}).get('bindings', []):
            baseline['bindings'].append({'name': item['name'],
                                         'type': 'durable_object_namespace',
                                         'class_name': item['class_name']})
        for name, value in actual.get('vars', {}).items():
            baseline['bindings'].append({'name': name, 'type': 'plain_text',
                                         'sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()})
        m.validate_config(actual, baseline)
        altered = dict(actual)
        altered['vars'] = {**actual['vars'], 'PADIEM_AUTH_IDENTITY_HMAC_KEY': 'synthetic'}
        with self.assertRaises(ValueError):
            m.validate_config(altered, baseline)
        changed = dict(actual)
        changed['vars'] = {**actual['vars'], 'PADIEM_AUTH_CLIENTS': 'changed'}
        with self.assertRaises(ValueError):
            m.validate_config(changed, baseline)


    def test_real_preflight_config_enforces_only_reviewed_staging_addition(self):
        from padiem_auth_client_delta import fingerprints
        import hashlib
        import json
        old = json.dumps({'b62': {'redirect': ['before']}})
        new = json.dumps({'b62': {'redirect': ['before']}, 'b62-staging': {'id': 'b62-staging'}})
        reviewed = {'vars': {'PADIEM_AUTH_CLIENTS': new}}
        baseline = {**base, 'bindings': base['bindings'] + [
            {'name': 'PADIEM_AUTH_CLIENTS', 'type': 'plain_text',
             'sha256': hashlib.sha256(old.encode()).hexdigest()}]}
        actual = {**config, 'vars': {'PADIEM_AUTH_CLIENTS': new}}
        m.validate_config(actual, baseline, fingerprints(old), reviewed)
        changed = json.dumps({'b62': {'redirect': ['changed']}, 'b62-staging': {'id': 'b62-staging'}})
        with self.assertRaises(ValueError):
            m.validate_config({**config, 'vars': {'PADIEM_AUTH_CLIENTS': changed}},
                              baseline, fingerprints(old), reviewed)
        with self.assertRaises(ValueError):
            m.validate_config(actual, baseline)

    def test_readonly_main_with_approved_metadata_and_synthetic_snapshot(self):
        import hashlib, json, tempfile, tomllib
        from unittest.mock import patch
        from padiem_auth_client_delta import fingerprints
        repo = Path(__file__).resolve().parents[2]
        baseline = json.loads((repo / '.github/binding_baselines/padiem-auth.json').read_text(encoding='utf-8'))
        config = tomllib.loads((repo / 'apps/padiem-auth/wrangler.toml').read_text(encoding='utf-8'))
        bindings = []
        for item in baseline['bindings']:
            entry = dict(item)
            name, kind = item['name'], item['type']
            if kind == 'plain_text':
                value = config.get('vars', {}).get(name, 'synthetic-' + name)
                entry['sha256'] = hashlib.sha256(value.encode()).hexdigest()
            elif kind == 'service':
                candidate = next(s for s in config['services'] if s['binding'] == name)
                entry.update({k: v for k, v in candidate.items() if k != 'binding'})
            elif kind == 'durable_object_namespace':
                candidate = next(d for d in config['durable_objects']['bindings'] if d['name'] == name)
                entry.update(candidate)
            bindings.append(entry)
        snapshot = {'success': True, 'result': {'bindings': bindings},
                    'client_fingerprints': fingerprints(config['vars']['PADIEM_AUTH_CLIENTS'])}
        deployments = [{'created_on':'2026-10-31', 'versions':[{'version_id':version, 'percentage':100}]}]
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp)/x for x in ('settings.json','baseline.json','deployments.json')]
            for path, data in zip(paths, (snapshot, baseline, deployments)):
                path.write_text(json.dumps(data), encoding='utf-8')
            with patch.object(sys, 'argv', ['preflight', *map(str, paths), version]):
                m.main()
            bad = dict(snapshot); bad['result'] = {'bindings': bindings[:-1]}
            paths[0].write_text(json.dumps(bad), encoding='utf-8')
            with patch.object(sys, 'argv', ['preflight', *map(str, paths), version]), self.assertRaises(ValueError):
                m.main()

    def test_service_and_do_diagnostics_never_print_values(self):
        import contextlib, io
        for kind in ('service', 'do'):
            changed = {**base, 'bindings':[dict(b) for b in base['bindings']]}
            b = changed['bindings'][0 if kind == 'service' else 1]
            b['service' if kind == 'service' else 'class_name'] = 'SYNTHETIC_PRIVATE_VALUE'
            output = io.StringIO()
            with contextlib.redirect_stderr(output), self.assertRaises(ValueError):
                m.validate_config(config, changed)
            text = output.getvalue()
            self.assertIn('PADIEM_AUTH_PREFLIGHT_' + ('SERVICE' if kind == 'service' else 'DO') + '_MISMATCH=FAIL', text)
            self.assertIn(('IDENTITY_AUTHORITY service' if kind == 'service' else 'AUTH_STATE class_name'), text)
            self.assertNotIn('SYNTHETIC_PRIVATE_VALUE', text)

    def test_only_omitted_environment_matches_production(self):
        import contextlib, io
        def live(environment):
            changed = {**base, 'bindings':[dict(b) for b in base['bindings']]}
            changed['bindings'][0]['environment'] = environment
            return changed
        m.validate_config(config, live('production'))
        for environment in ('staging', ''):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
                m.validate_config(config, live(environment))
        for explicit in (None, 'staging'):
            candidate = {**config, 'services':[{**config['services'][0], 'environment':explicit}]}
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
                m.validate_config(candidate, live('production'))
        changed = {**config, 'services':[{**config['services'][0], 'service':'other-target'}]}
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
            m.validate_config(changed, live('production'))


if __name__ == '__main__': unittest.main()
