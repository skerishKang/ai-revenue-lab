"""CPython-only composition for the shared login contract."""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

from starlette.responses import RedirectResponse

from .auth_routes import current_user_id
from .shared_auth_adapter import SharedChatAuth
from .shared_auth_compare_flow import _un64, exchange_with_httpx
from .shared_login_flow import SharedLoginFlow, issue_shared_cookies, revoke_with_httpx


class NativeES256Signer:
    async def sign(self, jwk, message):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        def number(name):
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
        if jwk.get('kty') != 'EC' or jwk.get('crv') != 'P-256':
            raise ValueError('invalid_key')
        key = ec.derive_private_key(number('d'), ec.SECP256R1())
        public = key.public_key().public_numbers()
        if public.x != number('x') or public.y != number('y'):
            raise ValueError('invalid_key')
        r, s = decode_dss_signature(key.sign(message, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


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


def create_host_shared_login_flow(env, authority, public_base_url):
    if str(env.get('PADIEM_CHAT_SHARED_LOGIN_ENABLED') or '').strip().lower() != 'true':
        return None
    if authority is None:
        print('shared_login: missing IDENTITY_AUTHORITY_SERVICE')
        return None
    private = _read_secret(env, 'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK')
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
        verifier = NativeTokenVerifier(client_id)
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
        flow = SharedLoginFlow(state_key=_un64(state), client_id=client_id,
            public_base_url=public_base_url, client_jwk=json.loads(private), kid=str(kid),
            operator_guard=lambda request: False, legacy_user=current_user_id,
            comparator=lambda *args: None, exchange=exchange_with_httpx,
            crypto=NativeES256Signer(), resolve_account=auth.user_id, issue_session=issue,
            revoke_session=revoke_with_httpx, provision_profile=provision)
        flow.auth = auth
        return flow
    except Exception:
        print('shared_login: unavailable')
        return None
