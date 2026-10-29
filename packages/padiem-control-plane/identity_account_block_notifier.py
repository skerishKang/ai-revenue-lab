"""Separate private service-binding entrypoint for account-block delivery.

The identity authority's default RPC endpoint does not export this operation.
The authorized account-block workflow must invoke this named entrypoint only
after its own durable block decision; unsuccessful deliveries must be retried.
"""
import json
import re
from workers import WorkerEntrypoint

URL = 'https://auth.padiem.net/internal/account-block'


def _request(account_id, secret):
    from js import Request, Object
    from pyodide.ffi import to_js
    options = {'method': 'POST', 'headers': {'authorization': 'Bearer ' + secret, 'content-type': 'application/json'}, 'body': json.dumps({'account_id': account_id})}
    return Request.new(URL, to_js(options, dict_converter=Object.fromEntries))


async def deliver(binding, secret, payload, make_request=_request):
    if not isinstance(payload, dict) or set(payload) != {'account_id'} or not isinstance(payload['account_id'], str) or not re.fullmatch(r'sub_[A-Za-z0-9_-]+', payload['account_id']):
        return {'ok': False, 'error': 'invalid_event'}
    if not binding or not isinstance(secret, str) or not secret:
        return {'ok': False, 'error': 'not_configured'}
    try:
        response = await binding.fetch(make_request(payload['account_id'], secret))
    except Exception:
        return {'ok': False, 'error': 'delivery_failed'}
    return {'ok': True} if getattr(response, 'status', None) == 200 else {'ok': False, 'error': 'delivery_failed'}


class BlockNotifier(WorkerEntrypoint):
    async def notify_account_blocked(self, payload):
        return await deliver(getattr(self.env, 'PADIEM_AUTH_ADMIN', None), getattr(self.env, 'PADIEM_AUTH_ADMIN_SECRET', None), payload)
