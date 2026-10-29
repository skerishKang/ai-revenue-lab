"""Opt-in, not yet wired: map a verified common session to an existing Chat user.

The caller must supply the shared ES256 verifier, and the legacy resolver. This
adapter never creates an identity link and must not be enabled until real account
continuity and the Worker verifier runtime have been independently confirmed.
"""
from __future__ import annotations

import inspect
import time
from typing import Any, Callable


class SharedAuthUnavailable(Exception):
    """Shared credentials were present but could not be verified or mapped."""


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
