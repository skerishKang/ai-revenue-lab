"""Opt-in comparison endpoint for a separately wired, protected test flow.

Not mounted by the application. The caller must supply an operator guard and a
server-side OAuth completion function which validates state and PKCE. Never
accept a token from the request body or return credentials to the browser.
"""
from __future__ import annotations

import inspect
from starlette.responses import JSONResponse
from starlette.routing import Route


async def _await(value):
    return await value if inspect.isawaitable(value) else value


def comparison_routes(*, enabled=False, operator_guard=None, complete_flow=None, comparator=None):
    if enabled is not True:
        return []
    if not all(callable(x) for x in (operator_guard, complete_flow, comparator)):
        raise ValueError('comparison_dependencies_missing')

    async def compare(request):
        headers = {'cache-control': 'no-store', 'referrer-policy': 'no-referrer'}
        try:
            # Both the guard and comparator's legacy resolver must verify the
            # existing Chat session. The flow must consume a bound one-time
            # code server-side; no browser-supplied token is trusted.
            if await _await(operator_guard(request)) is not True:
                return JSONResponse({'result': 'UNKNOWN'}, status_code=403, headers=headers)
            token = await _await(complete_flow(request))
            result = await _await(comparator(request, token))
            if result not in {'MATCH', 'MISMATCH', 'UNKNOWN'}:
                result = 'UNKNOWN'
            return JSONResponse({'result': result}, headers=headers)
        except Exception:
            return JSONResponse({'result': 'UNKNOWN'}, headers=headers)

    return [Route('/_test/auth/account-comparison', compare, methods=['POST'])]
