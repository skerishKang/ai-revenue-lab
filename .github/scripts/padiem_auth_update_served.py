"""Check the served version bindings without displaying values or version IDs."""
import json
import subprocess
import sys
from pathlib import Path
from padiem_auth_binding_check import verify
from padiem_auth_update_preflight import verify_deployment


def main():
    baseline = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    def wrangler(*args):
        result = subprocess.run(['npx', '--no-install', 'wrangler', *args], capture_output=True, text=True, check=False)
        if result.returncode:
            raise ValueError('served version metadata unavailable')
        return json.loads(result.stdout)
    deployments = wrangler('deployments', 'list', '--name', 'padiem-auth', '--json')
    if not isinstance(deployments, list) or not deployments:
        raise ValueError('served deployment missing')
    latest = max(deployments, key=lambda x: x.get('created_on', ''))
    versions = latest.get('versions', [])
    if len(versions) != 1:
        raise ValueError('served deployment split')
    version_id = versions[0].get('version_id', '')
    verify_deployment(deployments, version_id)
    version = wrangler('versions', 'view', version_id, '--name', 'padiem-auth', '--json')
    if version.get('id') != version_id:
        raise ValueError('served version identity mismatch')
    verify({'success': True, 'result': {'bindings': version.get('resources', {}).get('bindings')}}, baseline)
    print('served version binding baseline: PASS')
    print('PADIEM_AUTH_SERVED_VERSION_ID=' + version_id)


if __name__ == '__main__':
    main()
