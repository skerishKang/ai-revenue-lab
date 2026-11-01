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
from starlette.routing import Route

from .shared_auth_compare_flow import AUTH, TOKEN_URL, ComparisonFlow, _await, _b64, _encoded, _un64

CALLBACK = 'https://chat.padiem.net/auth/shared/callback'
STATE_COOKIE = '__Host-padiem-shared-state'
ACCESS_COOKIE = '__Host-padiem-shared-access'
REFRESH_COOKIE = 'padiem_shared_refresh'
MARKER_COOKIE = '__Host-padiem-shared-marker'
REFRESH_PATH = '/auth/shared'
ACCESS_SECONDS = 15 * 60
REFRESH_SECONDS = 30 * 24 * 60 * 60


def issue_shared_cookies(response, access, refresh):
    """Service host only; refresh is sent only to the common-auth endpoints."""
    response.set_cookie(ACCESS_COOKIE, access, secure=True, httponly=True,
                        samesite='lax', path='/', max_age=ACCESS_SECONDS)
    response.set_cookie(REFRESH_COOKIE, refresh, secure=True, httponly=True,
                        samesite='lax', path=REFRESH_PATH, max_age=REFRESH_SECONDS)
    # Presentation-only hint: never carries a credential or authorizes access.
    response.set_cookie(MARKER_COOKIE, '1', secure=True, httponly=True,
                        samesite='lax', path='/', max_age=REFRESH_SECONDS)
    return response


def clear_shared_cookies(response):
    response.delete_cookie(ACCESS_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, secure=True, httponly=True, samesite='lax')
    response.delete_cookie(MARKER_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response


class SharedLoginFlow(ComparisonFlow):
    """Use the existing assertion/WebCrypto contract; keep tokens server-side.

    ``issue_session`` must persist the verified access and refresh credentials
    safely and return a response; this skeleton does not install a cookie or
    convert a shared access token to an unbounded legacy session.
    """

    def __init__(self, *, issue_session, resolve_account, revoke_session=None, provision_profile=None, public_base_url=None, **kwargs):
        from urllib.parse import urlsplit
        base = (public_base_url or 'https://chat.padiem.net').rstrip('/')
        url = urlsplit(base)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError('invalid_shared_login_origin')
        self.public_base_url = base
        self.callback = base + '/auth/shared/callback'
        super().__init__(**kwargs)
        if not callable(issue_session) or not callable(resolve_account):
            raise ValueError('invalid_session_integration')
        self.issue_session = issue_session
        self.resolve_account = resolve_account
        self.revoke_session = revoke_session
        self.provision_profile = provision_profile

    async def start_login(self, request):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        data = _encoded({'state': state, 'verifier': verifier, 'exp': int(self.clock()) + 600})
        cookie = data + '.' + _b64(self._mac(b'shared-login', data.encode('ascii')))
        query = urlencode({'client_id': self.client_id, 'redirect_uri': self.callback, 'state': state,
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
                'redirect_uri': self.callback, 'code_verifier': state['verifier'],
            }))
            access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ValueError('invalid_exchange')
            user = await _await(self.resolve_account(request, access))
            if not isinstance(user, str) or not user:
                raise ValueError('unknown_account')
            if self.provision_profile is not None:
                await _await(self.provision_profile(request, user, access, tokens))
            response = await _await(self.issue_session(request, user, access, refresh))
            if not isinstance(response, RedirectResponse):
                raise ValueError('invalid_session_response')
            response.headers.update(headers)
        except Exception:
            response = JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)
        response.delete_cookie(STATE_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
        return response

    async def refresh(self, request):
        """The authority owns rotation and the 30-second concurrent-use grace."""
        headers = {'cache-control': 'no-store', 'referrer-policy': 'no-referrer'}
        try:
            if request.headers.get('origin') != self.public_base_url:
                return JSONResponse({'error': 'invalid_origin'}, status_code=403, headers=headers)
            old = request.cookies.get(REFRESH_COOKIE)
            if not old:
                return JSONResponse({'error': 'not_authenticated'}, status_code=401, headers=headers)
            tokens = await _await(self.exchange(TOKEN_URL, {
                'client_id': self.client_id,
                'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                'client_assertion': await self._assertion(int(self.clock())),
                'grant_type': 'refresh_token', 'refresh_token': old,
            }))
            access, refresh = tokens.get('access_token'), tokens.get('refresh_token')
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ValueError('invalid_exchange')
            user = await _await(self.resolve_account(request, access))
            if not isinstance(user, str) or not user:
                raise ValueError('unknown_account')
            return issue_shared_cookies(JSONResponse({'ok': True}, headers=headers), access, refresh)
        except Exception:
            return JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)

    async def logout(self, request):
        headers = {'cache-control': 'no-store'}
        if request.headers.get('origin') != self.public_base_url:
            return JSONResponse({'error': 'invalid_origin'}, status_code=403, headers=headers)
        old = request.cookies.get(REFRESH_COOKIE)
        if old:
            try:
                if not callable(self.revoke_session):
                    raise ValueError('revoke_unavailable')
                await _await(self.revoke_session({
                    'client_id': self.client_id,
                    'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                    'client_assertion': await self._assertion(int(self.clock())),
                    'refresh_token': old,
                }))
            except Exception:
                return JSONResponse({'error': 'authentication_unavailable'}, status_code=503, headers=headers)
        return clear_shared_cookies(JSONResponse({'ok': True}, headers=headers))

    def login_routes(self):
        return [Route('/auth/shared/start', self.start_login, methods=['GET']),
                Route('/auth/shared/callback', self.finish_login, methods=['GET']),
                Route('/auth/shared/refresh', self.refresh, methods=['POST']),
                Route('/auth/shared/logout', self.logout, methods=['POST'])]


async def revoke_with_httpx(data):
    from . import httpx_compat as httpx
    async with httpx.AsyncClient(follow_redirects=False) as client:
        from .shared_auth_compare_flow import SERVER_HEADERS
        async with client.stream('POST', AUTH + '/logout', data=data, headers=SERVER_HEADERS) as response:
            if response.status_code != 200:
                print(f"[shared_login] revoke status={response.status_code}", flush=True)
                raise ValueError('revoke_failed')


async def create_worker_shared_login_flow(env, authority):
    """No secrets or routes are loaded while the explicit switch is off."""
    from .worker_config import binding_value, resolve_secret_binding
    if str(binding_value(env, 'PADIEM_CHAT_SHARED_LOGIN_ENABLED') or '').strip().lower() != 'true':
        return None
    from .auth_routes import current_user_id
    from .shared_auth_adapter import SharedChatAuth
    from .shared_auth_compare_flow import WorkerJwksVerifier, exchange_with_httpx
    try:
        if authority is None:
            print('shared_login: missing IDENTITY_AUTHORITY_SERVICE')
            return None
        private = await resolve_secret_binding(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK')
        state = await resolve_secret_binding(env, 'PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY')
        kid = binding_value(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_KID')
        missing = [name for name, value in (
            ('PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK', private),
            ('PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY', state),
            ('PADIEM_CHAT_SHARED_AUTH_CLIENT_KID', kid),
        ) if not value]
        if missing:
            print('shared_login: missing ' + ', '.join(missing))
            return None
        client_id = str(binding_value(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_ID') or 'b62').strip()
        public_base_url = binding_value(env, 'PADIEM_CHAT_PUBLIC_BASE_URL')
        verifier = WorkerJwksVerifier(audience=client_id)
        auth = SharedChatAuth(verifier=verifier, authority=authority, legacy=current_user_id)

        async def provision(request, user, access, tokens):
            from .b66_signup_notifications import deliver_after_signup
            from .shared_profile_provision import provision_shared_profile
            store = getattr(request.app.state, 'history_store', None)
            if store is None or not callable(getattr(store, 'upsert_shared_user', None)):
                raise ValueError('profile_store_unavailable')
            await provision_shared_profile(request, user, access, tokens, verifier=verifier,
                store=store, legacy_user=current_user_id, notify=deliver_after_signup)

        async def issue(request, user, access, refresh):
            return issue_shared_cookies(RedirectResponse('/', status_code=302), access, refresh)

        flow = SharedLoginFlow(state_key=_un64(state), client_id=client_id, public_base_url=public_base_url, client_jwk=json.loads(private),
            kid=str(kid), operator_guard=lambda request: False, legacy_user=current_user_id,
            comparator=lambda *args: None, exchange=exchange_with_httpx, resolve_account=auth.user_id,
            issue_session=issue, revoke_session=revoke_with_httpx, provision_profile=provision)
        flow.auth = auth
        return flow
    except Exception:
        print('shared_login: unavailable')
        return None
