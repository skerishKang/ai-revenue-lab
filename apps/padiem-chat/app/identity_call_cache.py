"""Success-only, short-TTL in-memory cache for the repeated identity reads.

Every orchestration turn resolves the chat owner through the Control Plane
authority (`resolve_current_auth_session`, apps/padiem-chat/app/chat_pc_drive.py
_resolve_chat_owner) and PC turns add a `resolve_connector_owner_scope` read;
both are remote Worker RPCs that cost 0.6-1.0 s from COM2 because the identity
edge attaches to LAX/SJC for this line (261104 measurement). The reads are pure
functions of a verified credential: one canonical session per (product, product
user), one owner scope per canonical session.

Discipline mirrors SqliteAuthValidationCache. The Control Plane authority
remains the sole producer and is reached for every cache miss. Only successful
answers are cached — a rejection, an error or an authority outage propagates
and is never stored, so a refusal re-asks the authority on the next call. Keys
carry only a SHA-256 hash of the credential or session id, never the values.
The TTL is capped at 60 s. Concurrent callers share one in-flight lookup, so a
turn cannot double-pay. Logout, account deletion, permission changes and
session revocation invalidate through `invalidate_auth_cache`; an invalidation
also fences every in-flight load, so a lookup that started before the logout
cannot repopulate the cache after it.

Residual staleness is bounded: the session revocation guard reads through
`resolve_auth_session`, so a revoked session may still be honoured for up to
20 s — the same shape the existing auth validation cache already has (30 s).
The 60 s entries only affect which PC tools the lane offers.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Callable

_MAX_TTL_SECONDS = 60
#: Same window as the existing per-turn reads: the product user of a verified
#: subject cannot change while that subject stays signed in.
_PRODUCT_USER_TTL_SECONDS = 60
#: Long enough to collapse the repeated reads inside one request and a 2 s
#: poll, short enough that a revoked session stops being honoured.
_AUTH_SESSION_TTL_SECONDS = 20


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CachedIdentityAuthority:
    """Transparent authority wrapper; four reads are cached.

    ``resolve_current_auth_session`` (60 s), ``resolve_connector_owner_scope``
    (60 s), ``resolve_product_user_for_subject`` (60 s) and
    ``resolve_auth_session`` (20 s) are the per-request reads; they repeat
    inside one request and, for the Engine PC-files poll, once per poll. The
    revoke/delete/membership calls and the schema helpers delegate untouched.
    Session revocation therefore lands within 20 s rather than instantly.
    """

    def __init__(self, inner: Any, *, ttl_seconds: int = 60,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not 0 < ttl_seconds <= _MAX_TTL_SECONDS:
            raise ValueError("invalid_identity_cache_ttl")
        self._inner = inner
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        # key -> (expiry, value, user_ref); user_ref drives user-level invalidation.
        self._entries: dict[str, tuple[float, Any, str]] = {}
        # Single-flight: concurrent callers of one key share one lookup.
        self._inflight: dict[str, asyncio.Task] = {}
        # Invalidation fence: a load started before an invalidation must not
        # store its answer after the invalidation.
        self._epoch = 0

    def invalidate_user(self, user_id: str) -> None:
        """Drop every entry that belongs to one product user.

        Logout, account deletion and permission changes call this through
        `invalidate_auth_cache`. The auth-session entries carry the product
        user id in their key; owner-scope entries carry the account ref they
        resolved, which is the same product user vocabulary.
        """
        self._epoch += 1
        # The session->user mapping is the authority's, not this cache's, so a
        # user-level invalidation drops every session answer (revocations are
        # rare and the cache is small).
        for key in [k for k, (_, _, user_ref) in self._entries.items()
                    if user_ref == user_id or k.startswith("authsess:")]:
            self._entries.pop(key, None)

    def invalidate_session(self, session_id: str) -> None:
        """Drop both entries keyed by one canonical session."""
        self._epoch += 1
        self._entries.pop("ownerscope:" + _hash_key(session_id), None)
        self._entries.pop("authsess:" + _hash_key(session_id), None)

    async def _get_or_load(self, key: str, user_ref: str, loader,
                           ttl: float | None = None, ref_of=None) -> Any:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]
        self._entries.pop(key, None)
        task = self._inflight.get(key)
        if task is None:
            epoch = self._epoch
            task = asyncio.create_task(self._load(
                key, user_ref, loader, epoch,
                self._ttl_seconds if ttl is None else ttl, ref_of))
            self._inflight[key] = task

            def _finished(done: asyncio.Task) -> None:
                if self._inflight.get(key) is done:
                    self._inflight.pop(key, None)
                # A disconnected caller must not leave an unobserved exception.
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(_finished)
        return await asyncio.shield(task)

    async def _load(self, key: str, user_ref: str, loader, epoch: int,
                    ttl: float, ref_of=None) -> Any:
        value = await loader()
        if ref_of is not None:
            user_ref = ref_of(value) or ""
        if self._epoch == epoch:
            self._entries[key] = (self._clock() + ttl, value, user_ref)
        return value

    async def resolve_current_auth_session(
        self, *, product_id: str, product_user_id: str,
    ) -> Any:
        """The per-turn chat-owner read, cached per (product, product user)."""
        key = "authsession:" + product_id + ":" + _hash_key(product_user_id)

        async def loader() -> Any:
            return await self._inner.resolve_current_auth_session(
                product_id=product_id, product_user_id=product_user_id,
            )

        return await self._get_or_load(key, product_user_id, loader)

    async def resolve_product_user_for_subject(
        self, *, product_id: str, canonical_subject_id: str,
    ) -> str:
        """The Subject -> product user bridge, cached per (product, subject).

        The Engine PC-files poll resolves this on every poll; the answer only
        changes when the subject's product link does. The entry is filed under
        the uid it resolved, so `invalidate_user` of that account drops it.
        """
        key = ("productuser:" + product_id + ":"
               + _hash_key(canonical_subject_id))

        async def loader() -> Any:
            return await self._inner.resolve_product_user_for_subject(
                product_id=product_id, canonical_subject_id=canonical_subject_id,
            )

        uid = await self._get_or_load(
            key, "", loader, ttl=_PRODUCT_USER_TTL_SECONDS,
            ref_of=lambda value: value if isinstance(value, str) else None,
        )
        if not isinstance(uid, str) or not uid:
            # An answer whose uid cannot key an invalidation is not kept.
            self._entries.pop(key, None)
        return uid

    async def resolve_auth_session(self, *, session_id: str) -> Any:
        """The request-path session read, cached per session id for 20 s.

        The revocation guard calls this method too, so a revoked session is
        honoured within the TTL instead of instantly — the same shape the
        existing auth validation cache already has (30 s). A refusal is never
        stored: the authority is asked again on the next call.
        """
        key = "authsess:" + _hash_key(session_id)

        async def loader() -> Any:
            return await self._inner.resolve_auth_session(session_id=session_id)

        session = await self._get_or_load(
            key, "", loader, ttl=_AUTH_SESSION_TTL_SECONDS,
        )
        if session is None:
            self._entries.pop(key, None)
        return session

    async def resolve_connector_owner_scope(self, *, session_id: str) -> dict[str, str]:
        """The PC-lane owner scope, cached per canonical session."""
        key = "ownerscope:" + _hash_key(session_id)

        async def loader() -> Any:
            return await self._inner.resolve_connector_owner_scope(session_id=session_id)

        scope = await self._get_or_load(key, "", loader)
        # The scope answers with the account the session belongs to, so a
        # user-level invalidation can find and drop this entry later.
        if isinstance(scope, dict):
            account_ref = scope.get("account_ref")
            entry = self._entries.get(key)
            if isinstance(account_ref, str) and account_ref and entry is not None:
                self._entries[key] = (entry[0], scope, account_ref)
        return scope

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
