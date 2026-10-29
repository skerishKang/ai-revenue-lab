"""Read approved-account Worker binding metadata; write only sanitized fields."""
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path


def main():
    account = os.environ['CLOUDFLARE_ACCOUNT_ID']
    token = os.environ['CLOUDFLARE_API_TOKEN']
    source = Path('docs/operations/PADIEM_WEB_SEARCH_PROVIDER_POLICY_3385.md').read_text(encoding='utf-8')
    known = re.findall(r'Charliekant Account ID `([0-9a-f]{32})`', source)
    if len(known) != 1 or known[0] != account:
        raise ValueError('approved account mismatch')
    base = 'https://api.cloudflare.com/client/v4/accounts/' + account
    def get(path):
        req = urllib.request.Request(base + path, headers={'Authorization': 'Bearer ' + token})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except Exception:
            raise ValueError('Cloudflare metadata read failed') from None
    auth = get('')
    if auth.get('success') is not True or auth.get('result', {}).get('id') != account:
        raise ValueError('approved account unreadable')
    result = get('/workers/scripts/padiem-auth/settings')
    if result.get('success') is not True or not isinstance(result.get('result', {}).get('bindings'), list):
        raise ValueError('binding settings unavailable')
    bindings = []
    for b in result['result']['bindings']:
        if not isinstance(b, dict):
            raise ValueError('invalid binding')
        kind = b.get('type')
        out = {'name': b.get('name'), 'type': kind}
        if kind == 'secret_text':
            if b.get('text'):
                raise ValueError('unexpected readable secret data')
        elif kind == 'plain_text':
            if not isinstance(b.get('text'), str):
                raise ValueError('plain variable unavailable')
            out['sha256'] = hashlib.sha256(b['text'].encode()).hexdigest()
        elif kind == 'service':
            for k in ('service', 'environment', 'entrypoint'):
                if k in b: out[k] = b[k]
        elif kind == 'durable_object_namespace':
            for k in ('class_name', 'script_name', 'namespace_id'):
                if k in b: out[k] = b[k]
        else:
            raise ValueError('unreviewed binding type')
        bindings.append(out)
    target = Path(sys.argv[1])
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump({'success': True, 'result': {'bindings': bindings}}, out)
    print('approved-account binding metadata read: PASS')


if __name__ == '__main__':
    main()
