"""Read-only preflight for auth updates. Refuses unless baseline is approved.

The caller supplies local metadata-only API responses. No values are printed.
"""
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from padiem_auth_binding_check import verify
from padiem_auth_client_delta import verify_delta


UUID = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')


def validate_config(config, baseline, live_clients=None, reviewed_config=None):
    if config.get('name') != 'padiem-auth':
        raise ValueError('wrong Worker')
    bindings = baseline.get('bindings', [])
    declared = config.get('vars', {})
    if not isinstance(declared, dict):
        raise ValueError('invalid declared vars')
    reviewed = {b.get('name'): b for b in bindings if b.get('type') == 'plain_text'}
    for name, value in declared.items():
        if name not in {'GOOGLE_CLIENT_ID', 'PADIEM_AUTH_CLIENTS'} or not isinstance(value, str):
            raise ValueError('unreviewed declared variable')
        expected = reviewed.get(name, {}).get('sha256')
        if expected != hashlib.sha256(value.encode('utf-8')).hexdigest():
            if name != 'PADIEM_AUTH_CLIENTS' or reviewed_config is None:
                raise ValueError('declared variable differs from reviewed baseline')
            verify_delta(live_clients, value, reviewed_config['vars']['PADIEM_AUTH_CLIENTS'])

    services = [b for b in bindings if b.get('type') == 'service']
    objects = [b for b in bindings if b.get('type') == 'durable_object_namespace']
    configured_services = config.get('services', [])
    configured_objects = config.get('durable_objects', {}).get('bindings', [])
    expected_services = sorted((x['name'], x.get('service'), x.get('environment'), x.get('entrypoint')) for x in services)
    if any(set(x) - {'binding', 'service', 'environment', 'entrypoint'} for x in configured_services):
        raise ValueError('unreviewed service option')
    if any(set(x) - {'name', 'class_name', 'script_name'} for x in configured_objects):
        raise ValueError('unreviewed DO option')
    planned_services = sorted((x['binding'], x.get('service'), x.get('environment'), x.get('entrypoint')) for x in configured_services)
    expected_objects = sorted((x['name'], x.get('class_name'), x.get('script_name')) for x in objects)
    planned_objects = sorted((x['name'], x.get('class_name'), x.get('script_name')) for x in configured_objects)
    if expected_services != planned_services or expected_objects != planned_objects:
        raise ValueError('planned service/DO bindings do not match approved baseline')
    # Updates to Durable Object classes need a separately reviewed migration.
    if config.get('migrations') != [{'tag': 'v1', 'new_sqlite_classes': ['AuthStateObject']}]:
        raise ValueError('DO migration plan differs')
    known = {'name', 'main', 'compatibility_date', 'workers_dev', 'services', 'durable_objects', 'migrations', 'vars'}
    if set(config) - known:
        raise ValueError('unreviewed Worker config')


def verify_deployment(deployments, expected):
    if not UUID.fullmatch(expected):
        raise ValueError('invalid expected version')
    if not isinstance(deployments, list) or not deployments:
        raise ValueError('no deployment history')
    current = max(deployments, key=lambda d: d.get('created_on', ''))
    versions = current.get('versions')
    if not isinstance(versions, list) or len(versions) != 1 or versions[0].get('version_id') != expected or versions[0].get('percentage') != 100:
        raise ValueError('current version changed or traffic split')


def main():
    if len(sys.argv) not in (5, 6):
        raise SystemExit('usage: SETTINGS BASELINE DEPLOYMENTS EXPECTED_VERSION [REVIEWED_CONFIG]')
    def read(path):
        return json.loads(Path(path).read_text(encoding='utf-8'))
    baseline = read(sys.argv[2])
    settings = read(sys.argv[1])
    verify(settings, baseline)
    reviewed = None
    if len(sys.argv) == 6:
        with open(sys.argv[5], 'rb') as approved:
            reviewed = tomllib.load(approved)
    with open('apps/padiem-auth/wrangler.toml', 'rb') as f:
        validate_config(tomllib.load(f), settings['result'], settings.get('client_fingerprints'), reviewed)
    verify_deployment(read(sys.argv[3]), sys.argv[4])
    print('approved binding baseline, planned config and active version: PASS')


if __name__ == '__main__':
    main()
