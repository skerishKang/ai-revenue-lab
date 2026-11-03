"""Success-only, short-TTL in-memory cache for the two per-turn identity reads.

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

Residual staleness is bounded and auth-neutral: the session revocation guard
keeps its own SQLite discipline unchanged, so what can lag up to the TTL is
only which PC tools the lane offers, never whether a request is signed in.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Callable

_MAX_TTL_SECONDS = 60


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CachedIdentityAuthority:
    """Transparent authority wrapper; exactly two reads are cached.

    Everything else — `resolve_auth_session` for the revocation guard, the
    revoke/delete/membership calls, the schema helpers — delegates untouched,
    so the guard's own cache discipline and every audit path keep their
    present behaviour.
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
        for key in [k for k, (_, _, user_ref) in self._entries.items()
                    if user_ref == user_id]:
            self._entries.pop(key, None)

    def invalidate_session(self, session_id: str) -> None:
        """Drop the owner-scope entry of one canonical session."""
        self._epoch += 1
        self._entries.pop("ownerscope:" + _hash_key(session_id), None)

    async def _get_or_load(self, key: str, user_ref: str, loader) -> Any:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]
        self._entries.pop(key, None)
        task = self._inflight.get(key)
        if task is None:
            epoch = self._epoch
            task = asyncio.create_task(self._load(key, user_ref, loader, epoch))
            self._inflight[key] = task

            def _finished(done: asyncio.Task) -> None:
                if self._inflight.get(key) is done:
                    self._inflight.pop(key, None)
                # A disconnected caller must not leave an unobserved exception.
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(_finished)
        return await asyncio.shield(task)

    async def _load(self, key: str, user_ref: str, loader, epoch: int) -> Any:
        value = await loader()
        if self._epoch == epoch:
            self._entries[key] = (self._clock() + self._ttl_seconds, value, user_ref)
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
