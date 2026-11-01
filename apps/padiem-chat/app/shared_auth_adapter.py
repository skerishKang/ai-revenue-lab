"""Opt-in, not yet wired: map a verified common session to an existing Chat user.

The caller must supply the shared ES256 verifier, and the legacy resolver. This
adapter never creates an identity link and must not be enabled until real account
continuity and the Worker verifier runtime have been independently confirmed.
"""
from __future__ import annotations

import inspect
import hmac
import time
from typing import Any, Callable

from .auth_validation_cache import cache_for_request, cache_configured_for_request


class SharedAuthUnavailable(Exception):
    """Shared credentials were present but could not be verified or mapped."""


class IdentityAuthorityReverseLookup:
    """Adapt the existing identity authority's read-only RPC wire contract."""

    def __init__(self, rpc: Any):
        self._rpc = rpc

    async def resolve_product_user_for_subject(self, *, product_id: str, canonical_subject_id: str) -> str:
        response = await self._rpc.resolve_product_user_for_subject({
            'product_id': product_id, 'canonical_subject_id': canonical_subject_id,
        })
        if not isinstance(response, dict) or response.get('ok') is not True:
            raise ValueError('reverse_lookup_failed')
        user = response.get('product_user_id')
        if not isinstance(user, str) or not user:
            raise ValueError('reverse_lookup_invalid')
        return user


class SharedChatAuth:
    def __init__(self, *, verifier: Any, authority: Any, legacy: Callable, clock=time.time, cache_seconds=300):
        if not callable(getattr(verifier, 'verify', None)) or not callable(legacy) or cache_seconds <= 0:
            raise ValueError('invalid_shared_auth_configuration')
        self._verifier, self._authority, self._legacy = verifier, authority, legacy
        self._clock, self._cache_seconds = clock, cache_seconds
        self._mapping: dict[str, tuple[str, float]] = {}

    async def user_id(self, request: Any, shared_token: str | None) -> str | None:
        if shared_token is None:
            result = self._legacy(request)
            return await result if inspect.isawaitable(result) else result
        if not isinstance(shared_token, str) or not shared_token:
            raise SharedAuthUnavailable('invalid_shared_credential')
        try:
            verified = self._verifier.verify(shared_token)
            if inspect.isawaitable(verified):
                verified = await verified
            account_id, expires = verified['accountId'], verified['expiresAt']
            if not isinstance(account_id, str) or not account_id.startswith('sub_') or type(expires) is not int or expires <= self._clock():
                raise ValueError('invalid_verified_claims')
            cache = cache_for_request(request)
            if cache_configured_for_request(request):
                # COM2's explicit None is cache-off, not permission to fall
                # back to the old process-local mapping on a different worker.
                self._mapping.clear()
                async def load_mapping():
                    user_id = await self._authority.resolve_product_user_for_subject(
                        product_id='b62', canonical_subject_id=account_id)
                    if not isinstance(user_id, str) or not user_id:
                        raise ValueError('missing_product_link')
                    return user_id, expires
                async def load_link():
                    # A session key is new on every login, so the authority was
                    # re-asked which account this subject is even though the link
                    # it answers with had not changed.
                    if cache is None:
                        return await load_mapping()
                    user_id = await cache.get_or_load_account_link(account_id, load_mapping)
                    return user_id, expires
                session_id = verified.get('sessionId')
                if cache is not None and isinstance(session_id, str) and session_id:
                    return await cache.get_or_load('shared', account_id, session_id, load_link)
                # Disabled caching and verifier contracts without a signed
                # session ID fall back to the subject's own cache, or to a fresh
                # authority lookup when even that is switched off.
                return (await load_link())[0]
            cached = self._mapping.get(account_id)
            if cached and cached[1] > self._clock():
                return cached[0]
            user_id = await self._authority.resolve_product_user_for_subject(product_id='b62', canonical_subject_id=account_id)
            if not isinstance(user_id, str) or not user_id:
                raise ValueError('missing_product_link')
            self._mapping[account_id] = (user_id, min(expires, self._clock() + self._cache_seconds))
            return user_id
        except Exception as exc:
            raise SharedAuthUnavailable('shared_auth_failed') from exc

    async def invalidate_session(self, request, shared_token):
        """Called only after the authority confirmed a shared logout."""
        self._mapping.clear()
        cache = cache_for_request(request)
        if cache is None:
            return
        verified = None
        if isinstance(shared_token, str) and shared_token:
            try:
                verified = self._verifier.verify(shared_token)
                if inspect.isawaitable(verified):
                    verified = await verified
            except Exception:
                pass
        if isinstance(verified, dict):
            account_id, session_id = verified.get('accountId'), verified.get('sessionId')
            if (isinstance(account_id, str) and account_id.startswith('sub_')
                    and isinstance(session_id, str) and session_id):
                await cache.invalidate_session('shared', account_id, session_id)
                return
        # Refresh-only/expired-access logout cannot prove a local cache key.
        # Drop this disposable cache rather than retaining unverifiable state.
        await cache.invalidate_all()

    async def compare_existing_account(self, request: Any, shared_token: str | None) -> str:
        """Compare two authenticated sessions; return only MATCH/MISMATCH/UNKNOWN.

        The caller supplies the verified legacy-session resolver and a common
        token obtained by the service's server-side OAuth code exchange. This
        method is deliberately not exposed as an HTTP route by itself.
        """
        if not isinstance(shared_token, str) or not shared_token:
            return 'UNKNOWN'
        try:
            legacy_user = self._legacy(request)
            if inspect.isawaitable(legacy_user):
                legacy_user = await legacy_user
            if not isinstance(legacy_user, str) or not legacy_user:
                return 'UNKNOWN'
            shared_user = await self.user_id(request, shared_token)
            if not isinstance(shared_user, str) or not shared_user:
                return 'UNKNOWN'
            return 'MATCH' if hmac.compare_digest(legacy_user.encode(), shared_user.encode()) else 'MISMATCH'
        except Exception:
            return 'UNKNOWN'
