"""Local workerd inspector sampling. Results are estimates, never edge billing CPU."""
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
import websocket

BASE = 'http://127.0.0.1:18787'
INSPECT = 'http://127.0.0.1:19229/json'
CASES = [
    ('poll', '/api/claw/connector/mesh-reads/poll', 'POST', b'{}'),
    ('google-start', '/auth/google/start', 'GET', None),
    ('lovetree-start', '/auth/lovetree/start', 'GET', None),
    ('password-login', '/api/auth/password/login', 'POST', b'{}'),
]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

def local_request(path, method='GET', body=None):
    url = BASE + path
    if urlparse(url).hostname != '127.0.0.1':
        raise ValueError('loopback only')
    request = urllib.request.Request(url, data=body, method=method, headers={'Content-Type':'application/json', 'Origin':BASE})
    start = time.perf_counter()
    try:
        with opener.open(request, timeout=20) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    return status, round((time.perf_counter()-start)*1000, 3)

def rpc(ws, ident, method):
    ws.send(json.dumps({'id':ident,'method':method}))
    while True:
        reply = json.loads(ws.recv())
        if reply.get('id') == ident:
            if 'error' in reply:
                raise RuntimeError(str(reply['error']))
            return reply.get('result', {})

def main():
    targets = json.load(opener.open(INSPECT, timeout=10))
    debugger = next(t['webSocketDebuggerUrl'] for t in targets if t.get('webSocketDebuggerUrl'))
    if urlparse(debugger).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError('non-local inspector refused')
    ws = websocket.create_connection(debugger, timeout=20, suppress_origin=True)
    try:
        rpc(ws, 1, 'Profiler.enable')
        for i, (label, path, method, body) in enumerate(CASES):
            rpc(ws, i*2+2, 'Profiler.start')
            status, wall = local_request(path, method, body)
            profile = rpc(ws, i*2+3, 'Profiler.stop')['profile']
            nodes = {n['id']: n for n in profile.get('nodes', [])}
            samples, deltas = profile.get('samples', []), profile.get('timeDeltas', [])
            if not samples or len(samples) != len(deltas):
                raise RuntimeError('inspector returned no usable CPU samples')
            active = sum(dt for sample, dt in zip(samples, deltas) if nodes.get(sample, {}).get('callFrame', {}).get('functionName') != '(idle)')
            print(json.dumps({'path':label,'status':status,'wall_ms':wall,'sampled_active_ms':round(active/1000, 3),'samples':len(samples),'classification':'synthetic unconfigured refusal; NOT successful production path'}), flush=True)
    finally:
        ws.close()

if __name__ == '__main__':
    main()
