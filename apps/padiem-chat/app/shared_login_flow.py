"""Opt-in OAuth authorization-code flow for Chat's common login.

This module is not mounted by default.  It depends on #6267 and deliberately
delegates session creation until the Worker session integration is supplied.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode

from starlette.responses import JSONResponse, RedirectResponse

from .shared_auth_compare_flow import AUTH, TOKEN_URL, ComparisonFlow, _await, _b64, _encoded, _un64

CALLBACK = 'https://chat.padiem.net/auth/shared/callback'
STATE_COOKIE = '__Host-padiem-shared-state'


class SharedLoginFlow(ComparisonFlow):
    """Use the existing assertion/WebCrypto contract; keep tokens server-side.

    ``issue_session`` must persist the verified access and refresh credentials
    safely and return a response; this skeleton does not install a cookie or
    convert a shared access token to an unbounded legacy session.
    """

    def __init__(self, *, issue_session, resolve_account, **kwargs):
        super().__init__(**kwargs)
        if not callable(issue_session) or not callable(resolve_account):
            raise ValueError('invalid_session_integration')
        self.issue_session = issue_session
        self.resolve_account = resolve_account

    async def start_login(self, request):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        data = _encoded({'state': state, 'verifier': verifier, 'exp': int(self.clock()) + 600})
        cookie = data + '.' + _b64(self._mac(b'shared-login', data.encode('ascii')))
        query = urlencode({'client_id': self.client_id, 'redirect_uri': CALLBACK, 'state': state,
                           'code_challenge': _b64(hashlib.sha256(verifier.encode('ascii')).digest()),
                           'code_challenge_method': 'S256'})
        response = RedirectResponse(AUTH + '/login?' + query, status_code=302,
                                    headers={'cache-control': 'no-store', 'referrer-policy': 'no-referrer'})
        response.set_cookie(STATE_COOKIE, cookie, secure=True, httponly=True, samesite='lax', path='/', max_age=600)
        return response

    async def finish_login(self, request):
        headers = {'cache-control': 'no-store', 'referrer-policy': 'no-referrer'}
        try:
            states, codes = request.query_params.getlist('state'), request.query_params.getlist('code')
            parts = request.cookies.get(STATE_COOKIE, '').split('.')
            if len(states) != 1 or len(codes) != 1 or not codes[0] or len(parts) != 2:
                raise ValueError('invalid_flow')
            mac = _b64(self._mac(b'shared-login', parts[0].encode('ascii')))
            if not hmac.compare_digest(mac, parts[1]):
                raise ValueError('invalid_cookie')
            state = json.loads(_un64(parts[0]))
            if (type(state.get('exp')) is not int or state['exp'] <= int(self.clock())
                    or not isinstance(state.get('state'), str)
                    or not hmac.compare_digest(state['state'], states[0])
                    or not isinstance(state.get('verifier'), str)):
                raise ValueError('invalid_state')
            tokens = await _await(self.exchange(TOKEN_URL, {
                'client_id': self.client_id,
                'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                'client_assertion': await self._assertion(int(self.clock())),
                'grant_type': 'authorization_code', 'code': codes[0],
                'redirect_uri': CALLBACK, 'code_verifier': state['verifier'],
            }))
            access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ValueError('invalid_exchange')
            user = await _await(self.resolve_account(request, access))
            if not isinstance(user, str) or not user:
                raise ValueError('unknown_account')
            response = await _await(self.issue_session(request, user, access, refresh))
            if not isinstance(response, RedirectResponse):
                raise ValueError('invalid_session_response')
            response.headers.update(headers)
        except Exception:
            response = JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)
        response.delete_cookie(STATE_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
        return response
