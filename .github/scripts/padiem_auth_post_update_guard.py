"""Compare sanitized before/after snapshots without emitting binding values."""
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from padiem_auth_binding_check import binding_pairs
from padiem_auth_client_delta import verify_delta


def expected_after(before, config, reviewed):
    if not isinstance(before, dict) or before.get('success') is not True:
        raise ValueError('before snapshot unavailable')
    entries = before.get('result', {}).get('bindings')
    if not isinstance(entries, list):
        raise ValueError('before snapshot unavailable')
    desired = json.loads(json.dumps(entries))
    proposed = config.get('vars', {}).get('PADIEM_AUTH_CLIENTS')
    matches = [b for b in desired if b.get('name') == 'PADIEM_AUTH_CLIENTS' and b.get('type') == 'plain_text']
    if len(matches) != 1 or not isinstance(proposed, str):
        raise ValueError('client configuration unavailable')
    digest = hashlib.sha256(proposed.encode('utf-8')).hexdigest()
    if matches[0].get('sha256') != digest:
        verify_delta(before.get('client_fingerprints'), proposed, reviewed['vars']['PADIEM_AUTH_CLIENTS'])
        matches[0]['sha256'] = digest
    return desired


def verify_after(before, after, config, reviewed):
    if not isinstance(after, dict) or after.get('success') is not True:
        raise ValueError('after snapshot unavailable')
    expected = expected_after(before, config, reviewed)
    if binding_pairs(expected) != binding_pairs(after.get('result', {}).get('bindings')):
        raise ValueError('post-update bindings differ')
    return True


def main():
    if len(sys.argv) != 5:
        raise SystemExit('usage: BEFORE AFTER CONFIG REVIEWED_CONFIG')
    def read_json(path):
        return json.loads(Path(path).read_text(encoding='utf-8'))
    def read_toml(path):
        with open(path, 'rb') as f:
            return tomllib.load(f)
    verify_after(read_json(sys.argv[1]), read_json(sys.argv[2]), read_toml(sys.argv[3]), read_toml(sys.argv[4]))
    print('post-update binding state: PASS')


if __name__ == '__main__':
    main()
