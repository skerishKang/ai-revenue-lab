import importlib.util
import copy
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


def actual_config_and_snapshot():
    import hashlib
    import tomllib
    repo = Path(__file__).resolve().parents[2]
    actual = tomllib.loads((repo / 'apps/padiem-auth/wrangler.toml').read_text(encoding='utf-8'))
    bindings = []
    for svc in actual.get('services', []):
        bindings.append({'name': svc['binding'], 'type': 'service',
                         **{key: value for key, value in svc.items() if key != 'binding'}})
    for item in actual.get('durable_objects', {}).get('bindings', []):
        bindings.append({'type': 'durable_object_namespace', **item})
    for name, value in actual.get('vars', {}).items():
        bindings.append({'name': name, 'type': 'plain_text',
                         'sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()})
    return actual, {'bindings': bindings}


class Check(unittest.TestCase):
    def test_config_rejects_target_change_and_vars(self):
        m.validate_config(config, base)
        with self.assertRaises(ValueError): m.validate_config({**config, 'vars': {'X': 'bad'}}, base)
        import contextlib, io
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), self.assertRaises(ValueError):
            m.validate_config({**config, 'services': []}, base)
        self.assertIn('PADIEM_AUTH_PREFLIGHT_SERVICE_MISMATCH=FAIL', output.getvalue())
    def test_only_log_retention_without_invocation_logs_is_reviewed(self):
        # 7542 P0-C: sign-in URLs carry one-time codes and state, so automatic
        # invocation logs must stay off while the Worker's own lines are kept.
        reviewed = {'enabled': True, 'head_sampling_rate': 1, 'logs': {'invocation_logs': False}}
        m.validate_config({**config, 'observability': reviewed}, base)
        for bad in ({**reviewed, 'logs': {'invocation_logs': True}},
                    {'enabled': True, 'head_sampling_rate': 1},
                    {**reviewed, 'head_sampling_rate': 0.5}):
            with self.assertRaises(ValueError):
                m.validate_config({**config, 'observability': bad}, base)

    def test_split_or_changed_active_version_is_rejected(self):
        m.verify_deployment([{'created_on': '2026-01-01', 'versions': [{'version_id': version, 'percentage': 100}]}], version)
        with self.assertRaises(ValueError): m.verify_deployment([{'versions': [{'version_id': version, 'percentage': 50}]}], version)
        with self.assertRaises(ValueError): m.verify_deployment([], version)

    def test_real_wrangler_config_path_and_secret_var_override_rejected(self):
        actual, baseline = actual_config_and_snapshot()
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
        old = json.dumps({'b62': {'redirect': ['before']}, 'b62-staging': {'id': 'b62-staging'},
                          'lovetree-4-0': {'redirect': ['love']}})
        new = json.dumps({'b62': {'redirect': ['before']}, 'b62-staging': {'id': 'b62-staging'},
                          'lovetree-4-0': {'redirect': ['love'], 'profile': ['email']}})
        reviewed = {'vars': {'PADIEM_AUTH_CLIENTS': new}}
        baseline = {**base, 'bindings': base['bindings'] + [
            {'name': 'PADIEM_AUTH_CLIENTS', 'type': 'plain_text',
             'sha256': hashlib.sha256(old.encode()).hexdigest()}]}
        actual = {**config, 'vars': {'PADIEM_AUTH_CLIENTS': new}}
        m.validate_config(actual, baseline, fingerprints(old), reviewed)
        other = json.dumps({'b62': {'redirect': ['changed']}, 'b62-staging': {'id': 'b62-staging'},
                            'lovetree-4-0': {'redirect': ['love'], 'profile': ['email']}})
        with self.assertRaises(ValueError):
            m.validate_config({**config, 'vars': {'PADIEM_AUTH_CLIENTS': other}},
                              baseline, fingerprints(old), reviewed)
        added = json.dumps({**json.loads(new), 'extra': {'redirect': ['extra']}})
        with self.assertRaises(ValueError):
            m.validate_config({**config, 'vars': {'PADIEM_AUTH_CLIENTS': added}},
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
            # A reviewed expected baseline does not make an absent live binding
            # acceptable. The gate must stop until it is actually provisioned.
            missing = {'success': True, 'result': {'bindings': [
                entry for entry in bindings if entry['name'] != 'COMMON_LOGIN_DELETION_RECORD']}}
            paths[0].write_text(json.dumps(missing), encoding='utf-8')
            with patch.object(sys, 'argv', ['preflight', *map(str, paths), version]), self.assertRaises(ValueError):
                m.main()

    def test_staging_targets_and_auth_state_cannot_cross_bind_production(self):
        actual, snapshot = actual_config_and_snapshot()
        m.validate_config(actual, snapshot)
        for index in (0, 1):
            changed = copy.deepcopy(actual)
            changed['env']['staging']['services'][index]['service'] = 'padiem-control-plane-identity'
            with self.subTest(service=index), self.assertRaisesRegex(ValueError, 'staging'):
                m.validate_config(changed, snapshot)
        changed = copy.deepcopy(actual)
        changed['env']['staging']['durable_objects']['bindings'][0]['script_name'] = 'padiem-auth'
        with self.assertRaisesRegex(ValueError, 'staging'):
            m.validate_config(changed, snapshot)

    def test_only_the_reviewed_staging_environment_shape_is_accepted(self):
        actual, snapshot = actual_config_and_snapshot()
        for key, value in (
            ('name', 'padiem-auth'), ('vars', {'SECRET': 'synthetic'}),
            ('migrations', []), ('routes', ['example.invalid/*']),
        ):
            changed = copy.deepcopy(actual)
            changed['env']['staging'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'staging'):
                m.validate_config(changed, snapshot)
        changed = copy.deepcopy(actual)
        changed['env']['other'] = copy.deepcopy(changed['env']['staging'])
        with self.assertRaisesRegex(ValueError, 'staging'):
            m.validate_config(changed, snapshot)

    def test_new_service_still_requires_the_exact_live_target_environment_and_entrypoint(self):
        import contextlib, io
        actual, snapshot = actual_config_and_snapshot()
        for side in ('config', 'live'):
            for field, value in (('entrypoint', None), ('entrypoint', 'Default'),
                                 ('service', 'padiem-control-plane-identity-staging'),
                                 ('environment', 'staging')):
                changed, live = copy.deepcopy(actual), copy.deepcopy(snapshot)
                items = changed['services'] if side == 'config' else live['bindings']
                key = 'binding' if side == 'config' else 'name'
                service = next(item for item in items if item.get(key) == 'COMMON_LOGIN_DELETION_RECORD')
                if value is None:
                    service.pop(field)
                else:
                    service[field] = value
                with self.subTest(side=side, field=field, value=value), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
                    m.validate_config(changed, live)
        missing = copy.deepcopy(snapshot)
        missing['bindings'] = [item for item in missing['bindings'] if item['name'] != 'COMMON_LOGIN_DELETION_RECORD']
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
            m.validate_config(actual, missing)

    def test_staging_deletion_entrypoint_must_be_present_and_exact(self):
        actual, snapshot = actual_config_and_snapshot()
        for entrypoint in (None, 'Default'):
            changed = copy.deepcopy(actual)
            service = changed['env']['staging']['services'][1]
            if entrypoint is None:
                service.pop('entrypoint')
            else:
                service['entrypoint'] = entrypoint
            with self.subTest(entrypoint=entrypoint), self.assertRaisesRegex(ValueError, 'staging'):
                m.validate_config(changed, snapshot)

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
