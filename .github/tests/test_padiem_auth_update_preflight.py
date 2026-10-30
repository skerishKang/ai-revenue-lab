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

if __name__ == '__main__': unittest.main()
