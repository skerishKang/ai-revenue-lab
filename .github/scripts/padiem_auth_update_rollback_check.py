"""Require an approved baseline and exact rollback version binding metadata."""
import json
import sys
from pathlib import Path
from padiem_auth_binding_check import verify


def verify_rollback(baseline, version, expected):
    if baseline.get('status') != 'approved':
        raise ValueError('baseline not approved')
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
    print('rollback version binding metadata: PASS')


if __name__ == '__main__':
    main()
