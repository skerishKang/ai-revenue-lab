"""CPython-only composition for the shared login contract."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path

from starlette.responses import RedirectResponse

from .auth_routes import current_user_id
from .shared_auth_adapter import SharedChatAuth
from .shared_auth_compare_flow import _un64, exchange_with_httpx
from . import httpx_compat as httpx
from .shared_login_flow import (
    SharedLoginFlow, attach_chat_default_session, clear_login_return_cookie,
    issue_shared_cookies, login_return_target, parse_extra_origins,
    revoke_with_httpx,
)
from .shared_login_timing import record_login_timing


class NativeES256Signer:
    _COMPONENTS = ('kty', 'crv', 'x', 'y', 'd')

    def __init__(self):
        self._key_material = None
        self._private_key = None

    @staticmethod
    def _number(jwk, name):
        value = jwk.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError('invalid_key')
        try:
            raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        except Exception:
            raise ValueError('invalid_key') from None
        if len(raw) != 32:
            raise ValueError('invalid_key')
        return int.from_bytes(raw, 'big')

    @classmethod
    def _derive_key(cls, jwk):
        from cryptography.hazmat.primitives.asymmetric import ec
        if not isinstance(jwk, dict) or jwk.get('kty') != 'EC' or jwk.get('crv') != 'P-256':
            raise ValueError('invalid_key')
        key = ec.derive_private_key(cls._number(jwk, 'd'), ec.SECP256R1())
        public = key.public_key().public_numbers()
        if public.x != cls._number(jwk, 'x') or public.y != cls._number(jwk, 'y'):
            raise ValueError('invalid_key')
        return key

    def prepare(self, jwk):
        # A new flow/process loads the configured JWK again. Within a live flow,
        # compare all key components on every sign so an in-place rotation is
        # re-derived while the same validated key is reused between requests.
        self._private_key = None
        self._key_material = None
        key = self._derive_key(jwk)
        self._private_key = key
        self._key_material = tuple(jwk.get(name) for name in self._COMPONENTS)
        return key

    def _key_for(self, jwk):
        if not isinstance(jwk, dict):
            raise ValueError('invalid_key')
        material = tuple(jwk.get(name) for name in self._COMPONENTS)
        if self._private_key is not None and material == self._key_material:
            return self._private_key
        started = time.perf_counter()
        self._private_key = None
        self._key_material = None
        try:
            key = self._derive_key(jwk)
        finally:
            record_login_timing('assertion_key_refresh', (time.perf_counter() - started) * 1000)
        self._private_key = key
        self._key_material = material
        return key

    async def sign(self, jwk, message):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        key = self._key_for(jwk)
        r, s = decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


class ReusableHttpxTokenExchange:
    """One host-lifetime HTTPX pool for common-auth token exchanges."""

    def __init__(self, client_factory=None):
        self._client_factory = client_factory
        self._client = None
        self._lock = asyncio.Lock()

    async def _get_client(self):
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                if self._client_factory is not None:
                    self._client = self._client_factory()
                else:
                    self._client = httpx.AsyncClient(
                        follow_redirects=False,
                        limits=httpx.Limits(keepalive_expiry=75.0),
                    )
        return self._client

    async def __call__(self, url, data):
        return await exchange_with_httpx(url, data, client=await self._get_client())

    async def aclose(self):
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()


class NativeTokenVerifier:
    def __init__(self, audience):
        # The installer links this exact reviewed implementation into the host.
        from padiem_auth_verify import Verifier
        self._verifier = Verifier(audience)

    async def verify(self, token):
        return await asyncio.to_thread(self._verifier.verify, token)


def _read_secret(env, name):
    path = str(env.get(name + '_FILE') or '').strip()
    if path:
        try:
            return Path(path).read_text(encoding='utf-8').strip()
        except (OSError, UnicodeError):
            return None
    return env.get(name) or None


def create_host_shared_login_flow(env, authority, public_base_url,
                                  canonical_session_lifetime_seconds=None):
    if str(env.get('PADIEM_CHAT_SHARED_LOGIN_ENABLED') or '').strip().lower() != 'true':
        return None
    if authority is None:
        print('shared_login: missing IDENTITY_AUTHORITY_SERVICE')
        return None
    key_read_started = time.perf_counter()
    private = _read_secret(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK')
    key_read_ms = (time.perf_counter() - key_read_started) * 1000
    state = _read_secret(env, 'PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY')
    kid = env.get('PADIEM_CHAT_SHARED_AUTH_CLIENT_KID')
    missing = [name for name, value in (
        ('PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK', private),
        ('PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY', state),
        ('PADIEM_CHAT_SHARED_AUTH_CLIENT_KID', kid),
    ) if not value]
    if missing:
        print('shared_login: missing ' + ', '.join(missing))
        return None
    try:
        client_id = str(env.get('PADIEM_CHAT_SHARED_AUTH_CLIENT_ID') or 'b62').strip()
        parse_started = time.perf_counter()
        client_jwk = json.loads(private)
        key_parse_ms = (time.perf_counter() - parse_started) * 1000
        crypto = NativeES256Signer()
        key_prepare_started = time.perf_counter()
        prepare = getattr(crypto, 'prepare', None)
        if callable(prepare):
            prepare(client_jwk)
        key_prepare_ms = (time.perf_counter() - key_prepare_started) * 1000
        print('shared_login_key_setup outcome=ok read_ms=%d parse_ms=%d key_prepare_ms=%d' % (
            int(round(key_read_ms)), int(round(key_parse_ms)), int(round(key_prepare_ms))), flush=True)
        verifier = NativeTokenVerifier(client_id)
        auth = SharedChatAuth(verifier=verifier, authority=authority, legacy=current_user_id,
            canonical_session_lifetime_seconds=canonical_session_lifetime_seconds)
        token_exchange = ReusableHttpxTokenExchange()
        async def provision(request, user, access, tokens):
            from .b66_signup_notifications import deliver_after_signup
            from .shared_profile_provision import provision_shared_profile
            store = getattr(request.app.state, 'history_store', None)
            if store is None or not callable(getattr(store, 'upsert_shared_user', None)):
                raise ValueError('profile_store_unavailable')
            await provision_shared_profile(request, user, access, tokens, verifier=verifier,
                store=store, legacy_user=current_user_id, notify=deliver_after_signup)
        async def issue(request, user, access, refresh):
            response = RedirectResponse(login_return_target(request), status_code=302)
            await attach_chat_default_session(
                response, request, user_id=user, access=access, verifier=verifier,
            )
            issue_shared_cookies(response, access, refresh)
            return clear_login_return_cookie(response)
        flow = SharedLoginFlow(state_key=_un64(state), client_id=client_id,
            public_base_url=public_base_url, client_jwk=client_jwk, kid=str(kid),
            extra_origins=parse_extra_origins(env.get('PADIEM_CHAT_PUBLIC_BASE_URLS')),
            operator_guard=lambda request: False, legacy_user=current_user_id,
            comparator=lambda *args: None, exchange=token_exchange,
            crypto=crypto, resolve_account=auth.user_id, issue_session=issue,
            revoke_session=revoke_with_httpx, provision_profile=provision)
        flow.auth = auth
        return flow
    except Exception:
        print('shared_login: unavailable')
        return None
