"""Server-side, opt-in OAuth flow for account comparison; never auto-mounted."""
from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import secrets
import time
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
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


async def exchange_with_httpx(url, data):
    """Fixed-origin server-side exchange; never log the request or response."""
    if url != TOKEN_URL:
        raise ValueError('invalid_token_endpoint')
    from . import httpx_compat as httpx
    from .auth import MAX_AUTH_RESPONSE_BYTES
    async with httpx.AsyncClient(follow_redirects=False) as client:
        async with client.stream('POST', TOKEN_URL, data=data) as response:
            if response.status_code != 200:
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
    """Use the common verifier with a Workers-fetch JWKS source and local cache."""
    audience = 'b62'
    jwks_url = AUTH + '/.well-known/jwks.json'

    def __init__(self, verifier_class, *, clock=time.time, cache_seconds=300):
        if not callable(verifier_class) or cache_seconds <= 0:
            raise ValueError('invalid_verifier_configuration')
        self.verifier_class, self.clock, self.cache_seconds = verifier_class, clock, cache_seconds
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
        if len(parts) != 3:
            raise ValueError('invalid_token')
        header = json.loads(_un64(parts[0]))
        kid = header.get('kid') if isinstance(header, dict) else None
        if not isinstance(kid, str) or not kid:
            raise ValueError('invalid_token')
        had_cache = self.keys is not None and self.clock() < self.until
        keys = self.keys if had_cache else await self._fetch()
        if had_cache and not any(isinstance(k, dict) and k.get('kid') == kid for k in keys['keys']):
            keys = await self._fetch()
        verifier = self.verifier_class(audience=self.audience, fetcher=lambda: keys, clock=self.clock)
        return verifier.verify(token)


class ComparisonFlow:
    def __init__(self, *, state_key, client_id, client_jwk, kid, operator_guard,
                 legacy_user, comparator, exchange, clock=time.time):
        if (not isinstance(state_key, bytes) or len(state_key) < 32
                or not isinstance(client_id, str) or not client_id
                or not isinstance(kid, str) or not kid
                or not all(callable(x) for x in (operator_guard, legacy_user, comparator, exchange))):
            raise ValueError('invalid_comparison_configuration')
        if client_jwk.get('kty') != 'EC' or client_jwk.get('crv') != 'P-256':
            raise ValueError('invalid_client_key')
        private = ec.derive_private_key(int.from_bytes(_un64(client_jwk['d']), 'big'), ec.SECP256R1())
        public = private.public_key().public_numbers()
        if (public.x != int.from_bytes(_un64(client_jwk['x']), 'big')
                or public.y != int.from_bytes(_un64(client_jwk['y']), 'big')):
            raise ValueError('invalid_client_key')
        self.key, self.client_id, self.kid = private, client_id, kid
        self.state_key, self.guard, self.legacy_user = state_key, operator_guard, legacy_user
        self.comparator, self.exchange, self.clock = comparator, exchange, clock

    def _mac(self, purpose, message):
        return hmac.new(self.state_key, purpose + b'\0' + message, hashlib.sha256).digest()

    def _assertion(self, now):
        head = _encoded({'alg':'ES256', 'kid':self.kid})
        payload = _encoded({'iss':self.client_id, 'sub':self.client_id, 'aud':TOKEN_URL,
                            'iat':now, 'exp':now + 120, 'jti':secrets.token_urlsafe(32)})
        signed = (head + '.' + payload).encode('ascii')
        r, s = decode_dss_signature(self.key.sign(signed, ec.ECDSA(hashes.SHA256())))
        return signed.decode('ascii') + '.' + _b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))

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
                'client_assertion':self._assertion(int(self.clock())), 'grant_type':'authorization_code',
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


def create_chat_comparison_flow(*, state_key, client_jwk, kid, verifier, authority,
                                exchange=exchange_with_httpx):
    """Wire the real Chat session, admin gate and read-only identity adapter.

    Configuration remains an explicit injection; this does not read secrets,
    enable the feature, or create any identity link.
    """
    from .auth_routes import auth_ready, current_user_id
    from .platform_admin_routes import platform_authority_for
    from .shared_auth_adapter import SharedChatAuth
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
