"""Server-side, opt-in OAuth flow for account comparison; never auto-mounted."""
from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import secrets
import re
import time
from urllib.parse import urlencode

from .shared_auth_compare_webcrypto import WorkerES256
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

AUTH = 'https://auth.padiem.net'
TOKEN_URL = AUTH + '/token'
COOKIE = '__Host-padiem-compare-state'
CALLBACK = 'https://chat.padiem.net/_test/auth/account-comparison/callback'


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _un64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def _encoded(value):
    return _b64(json.dumps(value, separators=(',', ':')).encode('utf-8'))


async def _await(value):
    return await value if inspect.isawaitable(value) else value


SERVER_HEADERS = {'User-Agent': 'PADIEM-Chat/1.0 (+https://chat.padiem.net)', 'Accept': 'application/json'}


async def exchange_with_httpx(url, data):
    """Fixed-origin server-side exchange; never log the request or response."""
    if url != TOKEN_URL:
        raise ValueError('invalid_token_endpoint')
    from . import httpx_compat as httpx
    from .auth import MAX_AUTH_RESPONSE_BYTES
    async with httpx.AsyncClient(follow_redirects=False) as client:
        # An explicit product User-Agent: auth.padiem.net sits behind Cloudflare's
        # browser-integrity check, which refuses default library agents (error 1010).
        async with client.stream('POST', TOKEN_URL, data=data, headers=SERVER_HEADERS) as response:
            if response.status_code != 200:
                # Status only: the body may carry token material.
                print(f"[shared_login] token exchange status={response.status_code}", flush=True)
                raise ValueError('exchange_failed')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                # Use the established Chat authentication response limit.
                if len(body) > MAX_AUTH_RESPONSE_BYTES:
                    raise ValueError('exchange_response_too_large')
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError('exchange_invalid_response')
            return value


class WorkerJwksVerifier:
    """Validate the shared ES256 contract with Workers fetch and WebCrypto."""
    audience = 'b62'
    jwks_url = AUTH + '/.well-known/jwks.json'

    def __init__(self, *, crypto=None, clock=time.time, cache_seconds=300, audience='b62'):
        if not isinstance(audience, str) or not audience or cache_seconds <= 0:
            raise ValueError('invalid_verifier_configuration')
        self.audience = audience
        self.crypto, self.clock, self.cache_seconds = crypto or WorkerES256(), clock, cache_seconds
        self.keys, self.until = None, 0

    async def _fetch(self):
        from . import httpx_compat as httpx
        from .auth import MAX_AUTH_RESPONSE_BYTES
        async with httpx.AsyncClient(follow_redirects=False) as client:
            async with client.stream('GET', self.jwks_url) as response:
                if response.status_code != 200:
                    raise ValueError('jwks_unavailable')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_AUTH_RESPONSE_BYTES:
                        raise ValueError('jwks_too_large')
                value = json.loads(data)
                if not isinstance(value, dict) or not isinstance(value.get('keys'), list):
                    raise ValueError('invalid_jwks')
                self.keys, self.until = value, self.clock() + self.cache_seconds
                return value

    async def verify(self, token):
        parts = token.split('.') if isinstance(token, str) else []
        if len(parts) != 3 or not all(re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in parts):
            raise ValueError('invalid_token')
        header, body = json.loads(_un64(parts[0])), json.loads(_un64(parts[1]))
        if (not isinstance(header, dict) or not isinstance(body, dict)
                or header.get('alg') != 'ES256' or header.get('typ') != 'JWT'
                or not isinstance(header.get('kid'), str) or not header['kid']
                or any(k in header for k in ('crit', 'jku', 'jwk', 'x5u'))):
            raise ValueError('invalid_header')
        kid = header['kid']
        had_cache = self.keys is not None and self.clock() < self.until
        keys = self.keys if had_cache else await self._fetch()
        if had_cache and not any(isinstance(k, dict) and k.get('kid') == kid for k in keys['keys']):
            keys = await self._fetch()
        matches = [k for k in keys['keys'] if isinstance(k, dict) and k.get('kid') == kid
                   and k.get('kty') == 'EC' and k.get('crv') == 'P-256' and not k.get('d')
                   and k.get('alg', 'ES256') == 'ES256' and k.get('use', 'sig') == 'sig']
        if len(matches) != 1:
            raise ValueError('unknown_key')
        signature = _un64(parts[2])
        if not await self.crypto.verify(matches[0], signature, (parts[0] + '.' + parts[1]).encode('ascii')):
            raise ValueError('invalid_signature')
        now = int(self.clock())
        if (body.get('iss') != AUTH or body.get('aud') != self.audience or body.get('token_use') != 'access'
                or type(body.get('iat')) is not int or body['iat'] > now
                or type(body.get('exp')) is not int or body['exp'] <= now or body['exp'] > body['iat'] + 900
                or not isinstance(body.get('sub'), str) or not body['sub']
                or not isinstance(body.get('account_id'), str) or not re.fullmatch(r'sub_[A-Za-z0-9_-]+', body['account_id'])
                or not isinstance(body.get('sid'), str) or not body['sid']):
            raise ValueError('invalid_claims')
        return dict(subject=body['sub'], accountId=body['account_id'], sessionId=body['sid'], expiresAt=body['exp'])


class ComparisonFlow:
    def __init__(self, *, state_key, client_id, client_jwk, kid, operator_guard,
                 legacy_user, comparator, exchange, crypto=None, clock=time.time):
        if (not isinstance(state_key, bytes) or len(state_key) < 32
                or not isinstance(client_id, str) or not client_id
                or not isinstance(kid, str) or not kid
                or not all(callable(x) for x in (operator_guard, legacy_user, comparator, exchange))):
            raise ValueError('invalid_comparison_configuration')
        if (not isinstance(client_jwk, dict) or client_jwk.get('kty') != 'EC'
                or client_jwk.get('crv') != 'P-256'
                or not all(isinstance(client_jwk.get(k), str) and client_jwk[k] for k in ('x', 'y', 'd'))):
            raise ValueError('invalid_client_key')
        self.key, self.client_id, self.kid = dict(client_jwk), client_id, kid
        self.crypto = crypto or WorkerES256()
        self.state_key, self.guard, self.legacy_user = state_key, operator_guard, legacy_user
        self.comparator, self.exchange, self.clock = comparator, exchange, clock

    def _mac(self, purpose, message):
        return hmac.new(self.state_key, purpose + b'\0' + message, hashlib.sha256).digest()

    async def _assertion(self, now):
        head = _encoded({'alg':'ES256', 'kid':self.kid})
        payload = _encoded({'iss':self.client_id, 'sub':self.client_id, 'aud':TOKEN_URL,
                            'iat':now, 'exp':now + 120, 'jti':secrets.token_urlsafe(32)})
        signed = (head + '.' + payload).encode('ascii')
        signature = await self.crypto.sign(self.key, signed)
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise ValueError('invalid_es256_signature')
        return signed.decode('ascii') + '.' + _b64(signature)

    async def start(self, request):
        headers = {'cache-control':'no-store', 'referrer-policy':'no-referrer'}
        try:
            if await _await(self.guard(request)) is not True:
                return JSONResponse({'result':'UNKNOWN'}, status_code=403, headers=headers)
            user = await _await(self.legacy_user(request))
            if not isinstance(user, str) or not user:
                return JSONResponse({'result':'UNKNOWN'}, status_code=403, headers=headers)
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            binding = _b64(self._mac(b'legacy-user', user.encode('utf-8')))
            data = _encoded({'state':state, 'verifier':verifier, 'binding':binding,
                             'exp':int(self.clock()) + 600})
            value = data + '.' + _b64(self._mac(b'flow', data.encode('ascii')))
            query = urlencode({'client_id':self.client_id, 'redirect_uri':CALLBACK, 'state':state,
                               'code_challenge':_b64(hashlib.sha256(verifier.encode('ascii')).digest()),
                               'code_challenge_method':'S256'})
            response = RedirectResponse(AUTH + '/login?' + query, status_code=302, headers=headers)
            response.set_cookie(COOKIE, value, secure=True, httponly=True, samesite='lax', path='/', max_age=600)
            return response
        except Exception:
            return JSONResponse({'result':'UNKNOWN'}, status_code=503, headers=headers)

    async def callback(self, request):
        headers = {'cache-control':'no-store', 'referrer-policy':'no-referrer'}
        result = 'UNKNOWN'
        try:
            if await _await(self.guard(request)) is not True:
                raise ValueError('forbidden')
            user = await _await(self.legacy_user(request))
            if not isinstance(user, str) or not user:
                raise ValueError('legacy_missing')
            states, codes = request.query_params.getlist('state'), request.query_params.getlist('code')
            cookie = request.cookies.get(COOKIE, '')
            parts = cookie.split('.')
            if len(states) != 1 or len(codes) != 1 or not codes[0] or len(parts) != 2:
                raise ValueError('invalid_flow')
            expected = _b64(self._mac(b'flow', parts[0].encode('ascii')))
            if not hmac.compare_digest(expected, parts[1]):
                raise ValueError('invalid_cookie')
            state = json.loads(_un64(parts[0]))
            binding = _b64(self._mac(b'legacy-user', user.encode('utf-8')))
            if (type(state.get('exp')) is not int or state['exp'] <= int(self.clock())
                    or not hmac.compare_digest(state.get('state', ''), states[0])
                    or not hmac.compare_digest(state.get('binding', ''), binding)):
                raise ValueError('invalid_state')
            response = await _await(self.exchange(TOKEN_URL, {
                'client_id':self.client_id, 'client_assertion_type':'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                'client_assertion':await self._assertion(int(self.clock())), 'grant_type':'authorization_code',
                'code':codes[0], 'redirect_uri':CALLBACK, 'code_verifier':state['verifier'],
            }))
            token = response.get('access_token') if isinstance(response, dict) else None
            if not isinstance(token, str) or not token:
                raise ValueError('exchange_failed')
            value = await _await(self.comparator(request, token))
            if value in {'MATCH','MISMATCH','UNKNOWN'}:
                result = value
        except Exception:
            pass
        response = JSONResponse({'result':result}, headers=headers)
        response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='lax')
        return response

    def routes(self, enabled=False):
        if enabled is not True:
            return []
        return [Route('/_test/auth/account-comparison/start', self.start, methods=['GET']),
                Route('/_test/auth/account-comparison/callback', self.callback, methods=['GET'])]


def create_chat_comparison_flow(*, state_key, client_jwk, kid, authority, verifier=None,
                                exchange=exchange_with_httpx):
    """Wire the real Chat session, admin gate and read-only identity adapter.

    Configuration remains an explicit injection; this does not read secrets,
    enable the feature, or create any identity link.
    """
    from .auth_routes import auth_ready, current_user_id
    from .platform_admin_routes import platform_authority_for
    from .shared_auth_adapter import SharedChatAuth
    verifier = verifier or WorkerJwksVerifier()
    if getattr(verifier, 'audience', None) != 'b62':
        raise ValueError('comparison_audience_mismatch')

    async def is_operator(request):
        if not auth_ready(request):
            return False
        user = current_user_id(request)
        if not user:
            return False
        return await platform_authority_for(request).is_super_admin(user_id=user) is True

    compare = SharedChatAuth(verifier=verifier, authority=authority, legacy=current_user_id)
    return ComparisonFlow(state_key=state_key, client_id='b62', client_jwk=client_jwk,
        kid=kid, operator_guard=is_operator, legacy_user=current_user_id,
        comparator=compare.compare_existing_account, exchange=exchange)


async def create_worker_comparison_flow(env, authority):
    """Resolve test-only secrets after Worker startup, only when explicitly enabled."""
    from .worker_config import binding_value, resolve_secret_binding
    flag = binding_value(env, 'PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED')
    if str(flag or '').strip().lower() != 'true':
        return None
    try:
        if authority is None:
            raise ValueError('identity_unavailable')
        private = await resolve_secret_binding(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK')
        state = await resolve_secret_binding(env, 'PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY')
        kid = binding_value(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_KID')
        if not private or not state or not kid:
            raise ValueError('configuration_unavailable')
        return create_chat_comparison_flow(state_key=_un64(state), client_jwk=json.loads(private),
                                           kid=str(kid), authority=authority)
    except Exception:
        # No secret, ID, token, cookie, exception text, or raw URL is emitted.
        print('shared_auth_comparison: unavailable')
        return None
