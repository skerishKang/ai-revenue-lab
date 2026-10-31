"""Read/attach exactly auth.padiem.net to padiem-auth; never print API values."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HOST, ZONE, WORKER = 'auth.padiem.net', 'padiem.net', 'padiem-auth'


def request(token, method, url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def inspect(call, account):
    api = 'https://api.cloudflare.com/client/v4'
    zones = call('GET', api + '/zones?' + urllib.parse.urlencode({'name': ZONE, 'status': 'active'}))
    matches = [z for z in zones.get('result', []) if z.get('name') == ZONE and z.get('account', {}).get('id') == account]
    if zones.get('success') is not True or len(matches) != 1 or not matches[0].get('id'):
        raise ValueError('approved zone not uniquely verified')
    zone_id = matches[0]['id']
    domains = call('GET', api + '/accounts/' + account + '/workers/domains')
    if domains.get('success') is not True or not isinstance(domains.get('result'), list):
        raise ValueError('domain inventory unavailable')
    entries = [d for d in domains['result'] if d.get('hostname') == HOST]
    if len(entries) > 1 or (entries and entries[0].get('service') != WORKER):
        raise ValueError('domain conflict')
    dns = call('GET', api + '/zones/' + zone_id + '/dns_records?' + urllib.parse.urlencode({'name': HOST}))
    if dns.get('success') is not True or not isinstance(dns.get('result'), list):
        raise ValueError('DNS inventory unavailable')
    if not entries and dns['result']:
        raise ValueError('existing DNS record requires review')
    return 'already-attached' if entries else 'absent'


def run(mode, account, token):
    evidence = Path('docs/operations/PADIEM_WEB_SEARCH_PROVIDER_POLICY_3385.md').read_text(encoding='utf-8')
    known = re.findall(r'Charliekant Account ID `([0-9a-f]{32})`', evidence)
    if len(known) != 1 or account != known[0]:
        raise ValueError('account evidence mismatch')
    call = lambda method, url, payload=None: request(token, method, url, payload)
    api = 'https://api.cloudflare.com/client/v4'
    identity = call('GET', api + '/accounts/' + account)
    if identity.get('success') is not True or identity.get('result', {}).get('id') != account:
        raise ValueError('account inaccessible')
    # Metadata-only list proves the target exists without reading source or secrets.
    scripts = call('GET', api + '/accounts/' + account + '/workers/scripts')
    if scripts.get('success') is not True or not any(s.get('id') == WORKER for s in scripts.get('result', [])):
        raise ValueError('target worker unavailable')
    state = inspect(call, account)
    if mode == 'readonly':
        print('approved account, zone, worker and domain preflight: PASS; domain=' + state)
        return
    if mode != 'activate':
        raise ValueError('invalid mode')
    # Re-read immediately; do not overwrite existing DNS or another service.
    state = inspect(call, account)
    if state == 'already-attached':
        print('domain already attached to target: PASS')
        return
    result = call('PUT', api + '/accounts/' + account + '/workers/domains', {'hostname': HOST, 'service': WORKER, 'zone_name': ZONE})
    if result.get('success') is not True or result.get('result', {}).get('hostname') != HOST or result.get('result', {}).get('service') != WORKER:
        raise ValueError('domain attach not confirmed')
    if inspect(call, account) != 'already-attached':
        raise ValueError('domain readback failed')
    print('domain attach and readback: PASS')


if __name__ == '__main__':
    try:
        run(os.environ['MODE'], os.environ['CLOUDFLARE_ACCOUNT_ID'], os.environ['CLOUDFLARE_API_TOKEN'])
    except Exception as exc:
        # Never dump request URLs, headers, API response bodies or credential values.
        print('domain operation failed: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
