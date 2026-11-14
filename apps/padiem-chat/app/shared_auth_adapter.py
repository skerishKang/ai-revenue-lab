"""Opt-in, not yet wired: map a verified common session to an existing Chat user.

The caller must supply the shared ES256 verifier, and the legacy resolver. This
adapter never creates an identity link and must not be enabled until real account
continuity and the Worker verifier runtime have been independently confirmed.

2026-11-08 · the adapter now also owns one bounded renewal: when the deployment
configures a canonical-session lifetime, a verified request whose product has
no ACTIVE canonical session re-establishes it (#7161 incident). The shared
login flow issues cookies only and ``/auth/shared/refresh`` re-exchanges and
re-issues — neither ever established the canonical B62/B54 session that the
Claw/MCP consumers resolve, so the last legacy login's canonical session
expiring left those consumers failing closed on every request. The renewal is
server-derived exactly like every other identity fact here: the subject comes
from the verifier's own claim, the product user from the authority's reverse
lookup, the clock and lifetime from the server — no request content can name
any of them. Failures are journaled with closed codes and never turn a
verified request into a failure.
"""
from __future__ import annotations

import inspect
import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .auth_validation_cache import cache_for_request, cache_configured_for_request
from .shared_login_timing import record_login_timing
from .connector_account_subject import _remember_verified_login, forget_verified_login

#: The products whose canonical session the Claw/MCP consumers resolve. Both
#: links already exist for a signed-in owner; only the session rows expire.
_CANONICAL_SESSION_PRODUCTS = ("b62", "b54-padiem-claw")

#: The one authority code that means "re-establishing is the fix". Every other
#: failure stays fail-closed for the consumers that resolve it.
_CANONICAL_SESSION_NOT_FOUND = "canonical_auth_session_not_found"


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
    def __init__(self, *, verifier: Any, authority: Any, legacy: Callable, clock=time.time,
                 cache_seconds=300, canonical_session_lifetime_seconds: int | None = None):
        if not callable(getattr(verifier, 'verify', None)) or not callable(legacy) or cache_seconds <= 0:
            raise ValueError('invalid_shared_auth_configuration')
        if canonical_session_lifetime_seconds is not None and (
                isinstance(canonical_session_lifetime_seconds, bool)
                or canonical_session_lifetime_seconds < 1):
            raise ValueError('invalid_shared_auth_configuration')
        self._verifier, self._authority, self._legacy = verifier, authority, legacy
        self._clock, self._cache_seconds = clock, cache_seconds
        self._canonical_lifetime = canonical_session_lifetime_seconds
        self._mapping: dict[str, tuple[str, float]] = {}

    @property
    def verifier(self):
        """The composed shared-token verifier this adapter authenticates with.

        The common-login refresh re-attachment (#7381) re-verifies the renewed
        access token through the same verifier instance the login used, so it
        reads the adapter's composition instead of reaching into private state.
        """
        return self._verifier

    async def _ensure_canonical_sessions(self, account_id: str, user_id: str) -> None:
        """Re-establish the expired canonical sessions behind a verified request.

        Strictly an aside: the whole body is contained, so ANY exception it can
        raise — an authority outage, a missing contract, a broken clock — is
        journaled and dropped. The verified request's outcome never changes
        because of the renewal. Fires only when the authority answers
        ``canonical_auth_session_not_found`` for a product — the one condition
        the bounded renewal can fix. A subject whose link is gone or an
        authority that is unreachable leaves every consumer exactly where it
        was: fail-closed. The subject is the verifier's own claim; the product
        user came from the authority's reverse lookup; nothing here is taken
        from the request.
        """

        if not self._canonical_lifetime:
            return
        try:
            from padiem_control_plane import CanonicalSubjectRef, SubjectType

            started = datetime.fromtimestamp(int(self._clock()), tz=timezone.utc)
            not_after = started + timedelta(seconds=int(self._canonical_lifetime))
            for product in _CANONICAL_SESSION_PRODUCTS:
                try:
                    await self._authority.resolve_current_auth_session(
                        product_id=product, product_user_id=user_id,
                    )
                    continue
                except Exception as exc:
                    if getattr(exc, 'code', '') != _CANONICAL_SESSION_NOT_FOUND:
                        print('canonical_session_renewal product=%s outcome=%s' % (
                            product, getattr(exc, 'code', '') or type(exc).__name__), flush=True)
                        continue
                try:
                    await self._authority.establish_auth_session(
                        product_id=product,
                        subject=CanonicalSubjectRef(
                            subject_type=SubjectType.USER, subject_id=account_id,
                        ),
                        authenticated_at=started, not_after=not_after,
                    )
                    print('canonical_session_renewal product=%s outcome=established' % product,
                          flush=True)
                except Exception as exc:
                    print('canonical_session_renewal product=%s outcome=%s' % (
                        product, getattr(exc, 'code', '') or type(exc).__name__), flush=True)
        except Exception as exc:
            # The renewal's own scaffolding (the contract import, the clock)
            # failing is still not the request's failure.
            print('canonical_session_renewal product=none outcome=%s' % type(exc).__name__,
                  flush=True)

    async def user_id(self, request: Any, shared_token: str | None) -> str | None:
        forget_verified_login()
        if shared_token is None:
            result = self._legacy(request)
            return await result if inspect.isawaitable(result) else result
        if not isinstance(shared_token, str) or not shared_token:
            raise SharedAuthUnavailable('invalid_shared_credential')
        try:
            verify_started = time.perf_counter()
            try:
                verified = self._verifier.verify(shared_token)
                if inspect.isawaitable(verified):
                    verified = await verified
            finally:
                record_login_timing('account_token_verify', (time.perf_counter() - verify_started) * 1000)
            account_id, expires = verified['accountId'], verified['expiresAt']
            if not isinstance(account_id, str) or not account_id.startswith('sub_') or type(expires) is not int or expires <= self._clock():
                raise ValueError('invalid_verified_claims')
            cache = cache_for_request(request)
            if cache_configured_for_request(request):
                # COM2's explicit None is cache-off, not permission to fall
                # back to the old process-local mapping on a different worker.
                self._mapping.clear()
                async def load_mapping():
                    identity_started = time.perf_counter()
                    try:
                        user_id = await self._authority.resolve_product_user_for_subject(
                            product_id='b62', canonical_subject_id=account_id)
                    finally:
                        record_login_timing('identity_rpc', (time.perf_counter() - identity_started) * 1000)
                    if not isinstance(user_id, str) or not user_id:
                        raise ValueError('missing_product_link')
                    return user_id, expires
                async def load_link():
                    # A session key is new on every login, so the authority was
                    # re-asked which account this subject is even though the link
                    # it answers with had not changed.
                    if cache is None:
                        link_started = time.perf_counter()
                        try:
                            return await load_mapping()
                        finally:
                            record_login_timing('shared_account_link_lookup',
                                                (time.perf_counter() - link_started) * 1000)
                    link_started = time.perf_counter()
                    try:
                        user_id = await cache.get_or_load_account_link(account_id, load_mapping)
                    finally:
                        record_login_timing('shared_account_link_lookup',
                                            (time.perf_counter() - link_started) * 1000)
                    return user_id, expires
                session_id = verified.get('sessionId')
                if cache is not None and isinstance(session_id, str) and session_id:
                    lookup_started = time.perf_counter()
                    try:
                        user_id = await cache.get_or_load('shared', account_id, session_id, load_link)
                    finally:
                        record_login_timing('shared_session_result_lookup',
                                            (time.perf_counter() - lookup_started) * 1000)
                    _remember_verified_login(verified, user_id)
                    if self._canonical_lifetime:
                        await self._ensure_canonical_sessions(account_id, user_id)
                    return user_id
                # Disabled caching and verifier contracts without a signed
                # session ID fall back to the subject's own cache, or to a fresh
                # authority lookup when even that is switched off.
                user_id = (await load_link())[0]
                _remember_verified_login(verified, user_id)
                if self._canonical_lifetime:
                    await self._ensure_canonical_sessions(account_id, user_id)
                return user_id
            link_started = time.perf_counter()
            cached = self._mapping.get(account_id)
            if cached and cached[1] > self._clock():
                record_login_timing('shared_account_link_lookup',
                                    (time.perf_counter() - link_started) * 1000)
                _remember_verified_login(verified, cached[0])
                if self._canonical_lifetime:
                    await self._ensure_canonical_sessions(account_id, cached[0])
                return cached[0]
            link_started = time.perf_counter()
            try:
                user_id = await self._authority.resolve_product_user_for_subject(
                    product_id='b62', canonical_subject_id=account_id)
            finally:
                record_login_timing('shared_account_link_lookup',
                                    (time.perf_counter() - link_started) * 1000)
            if not isinstance(user_id, str) or not user_id:
                raise ValueError('missing_product_link')
            self._mapping[account_id] = (user_id, min(expires, self._clock() + self._cache_seconds))
            _remember_verified_login(verified, user_id)
            await self._ensure_canonical_sessions(account_id, user_id)
            return user_id
        except Exception as exc:
            forget_verified_login()
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
