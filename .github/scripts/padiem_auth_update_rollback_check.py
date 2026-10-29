"""Require a reviewed same-key-generation rollback version and bindings."""
import json
import sys
from pathlib import Path
from padiem_auth_binding_check import verify


def verify_rollback(baseline, version, expected):
    if baseline.get('status') != 'approved' or not baseline.get('active_key_generation'):
        raise ValueError('approved key generation missing')
    if baseline.get('rollback_key_generations', {}).get(expected) != baseline['active_key_generation']:
        raise ValueError('rollback key generation not verified')
    if version.get('id') != expected or not isinstance(version.get('resources', {}).get('bindings'), list):
        raise ValueError('rollback version metadata unavailable')
    verify({'success': True, 'result': {'bindings': version['resources']['bindings']}}, baseline)
    return True


def main():
    if len(sys.argv) != 4:
        raise SystemExit('usage: BASELINE VERSION_JSON EXPECTED_VERSION')
    baseline = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    version = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    verify_rollback(baseline, version, sys.argv[3])
    print('rollback version bindings and key generation: PASS')


if __name__ == '__main__':
    main()
