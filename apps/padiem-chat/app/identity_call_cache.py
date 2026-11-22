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
`resolve_auth_session`, so a revoked session may be honoured for up to
the unified auth-session window (300 s by default, the same
`PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS` the general request cache uses) —
but every revocation event this host serves (logout, password change,
account deletion, admin membership/role changes, session rotation) removes
the entry immediately, so the window only bounds how late a revocation made
in another product is observed. The 60-second entries only affect which PC
tools the lane offers.

#7543 5단계: 값은 지금처럼 이 프로세스 메모리에 두고, "이 범위의 캐시를 버려라"는
신호만 ``worker_cache_generation`` 의 SQLite 표로 공유한다. 항목은 저장할 때의 세대
번호를 함께 들고, 조회할 때 요청당 한 번 번호를 읽어 다르면 버린다. 무효화는 로컬
drop 뒤에 번호를 올리고, 이 프로세스에 남은 항목은 새 번호로 다시 표시해 워커 1개일
때의 적중·무효화 결과를 그대로 유지한다. 표가 없으면 아무 것도 바뀌지 않는다.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from typing import Any, Callable
from .identity_cache_metrics import record
from . import worker_cache_generation as generation

_MAX_TTL_SECONDS = 60
#: Same window as the existing per-turn reads: the product user of a verified
#: subject cannot change while that subject stays signed in.
_PRODUCT_USER_TTL_SECONDS = 60
#: Unified auth-session window (#7084): the SAME
#: `PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS` the SQLite auth/session cache
#: uses (default 300 s, capped at 900 s), so the revocation guard's
#: `resolve_auth_session` read and the Chat general request cache can no
#: longer expire independently. Every revocation event removes the entry
#: immediately through `invalidate_auth_cache`, which is the same
#: invalidation both caches share. The previous 20 s window expired between
#: request bursts faster than the SQLite layer could refresh, so the guard
#: paid the authority RPC anyway.
_AUTH_SESSION_TTL_ENV = "PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS"
_AUTH_SESSION_TTL_DEFAULT = 300
_AUTH_SESSION_TTL_MAX = 900


def _owner_scope_ttl_seconds() -> int:
    """The PC-lane owner-scope window, shared with the auth-session window.

    The same upper bound (900 s) and default (300 s) as the auth-session
    window: pairing/disconnect/designation writes drop the entry in the
    same request (see drop_cached_owner_scope_of), so a longer window never
    holds a scope the authority no longer answers.
    """
    return _auth_session_ttl_seconds()


def _auth_session_ttl_seconds() -> int:
    """The auth-session window shared with the SQLite auth/session cache."""
    raw = os.environ.get(_AUTH_SESSION_TTL_ENV, "").strip()
    try:
        ttl = int(raw) if raw else _AUTH_SESSION_TTL_DEFAULT
    except ValueError:
        ttl = _AUTH_SESSION_TTL_DEFAULT
    if ttl < 1 or ttl > _AUTH_SESSION_TTL_MAX:
        ttl = _AUTH_SESSION_TTL_DEFAULT
    return ttl


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope_of_key(key: str) -> str:
    """키 접두사 → 세대 번호 범위."""

    prefix = key.split(":", 1)[0]
    if prefix == "ownerscope":
        return generation.IDENTITY_OWNER_SCOPE
    if prefix == "productuser":
        return generation.IDENTITY_SUBJECT_MAPPING
    return generation.IDENTITY_AUTH_SESSION


class CachedIdentityAuthority:
    """Transparent authority wrapper; four reads are cached.

    ``resolve_current_auth_session`` (60 s), ``resolve_connector_owner_scope``
    (60 s), ``resolve_product_user_for_subject`` (60 s) and
    ``resolve_auth_session`` (unified auth-session window, 300 s default,
    shared with the SQLite session cache) are the per-request reads; they
    repeat inside one request and, for the Engine PC-files poll, once per
    poll. The revoke/delete/membership calls and the schema helpers delegate
    untouched. Session revocation therefore lands immediately on revocation
    events rather than at window expiry.
    """

    def __init__(self, inner: Any, *, ttl_seconds: int = 60,
                 clock: Callable[[], float] = time.monotonic,
                 generation_store: Any = None) -> None:
        if not 0 < ttl_seconds <= _MAX_TTL_SECONDS:
            raise ValueError("invalid_identity_cache_ttl")
        self._inner = inner
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        # #7543 5단계: 세대 번호 표. 정해지지 않으면(워커 1개 조립, 시험) 아무 것도
        # 바뀌지 않는다.
        self._generation_store = generation_store
        # key -> (expiry, value, user_ref, generation); user_ref drives user-level
        # invalidation, generation the cross-process signal.
        self._entries: dict[str, tuple[float, Any, str, int | None]] = {}
        # Single-flight: concurrent callers of one key share one lookup.
        self._inflight: dict[str, asyncio.Task] = {}
        # Invalidation fence: a load started before an invalidation must not
        # store its answer after the invalidation.
        self._epoch = 0

    def maintenance_uncached_authority(self):
        """SYSTEM maintenance rechecks live authority, not cached request reads."""
        return self._inner

    def invalidate_user(self, user_id: str, *, share: bool = True) -> None:
        """Drop every entry that belongs to one product user.

        Logout, account deletion and permission changes call this through
        `invalidate_auth_cache`. The auth-session entries carry the product
        user id in their key; owner-scope entries carry the account ref they
        resolved, which is the same product user vocabulary.
        """
        self._epoch += 1
        self._inflight.clear()
        # The session->user mapping is the authority's, not this cache's, so a
        # user-level invalidation drops every session answer (revocations are
        # rare and the cache is small).
        for key in [k for k, (_, _, user_ref, _) in self._entries.items()
                    if user_ref == user_id or k.startswith("authsess:")]:
            self._entries.pop(key, None)
        if share:
            self._share_invalidation()

    def invalidate_session(self, session_id: str, *, share: bool = True) -> None:
        """Drop both entries keyed by one canonical session."""
        self._epoch += 1
        self._inflight.clear()
        self._entries.pop("ownerscope:" + _hash_key(session_id), None)
        self._entries.pop("authsess:" + _hash_key(session_id), None)
        if share:
            self._share_invalidation(
                (generation.IDENTITY_AUTH_SESSION, generation.IDENTITY_OWNER_SCOPE))

    def invalidate_owner_scope_of_user(self, user_id: str, *,
                                       share: bool = True) -> None:
        """Drop only that user's cached owner-scope answers.

        Pairing, unpairing, disconnect and designation change what the
        connector may resolve for the account; the entries these answer with
        are filed under the account ref they resolved. Unlike
        `invalidate_user`, auth-session answers stay standing, so one
        pairing does not revoke everybody's cached session reads.
        """
        if not isinstance(user_id, str) or not user_id:
            return
        self._epoch += 1
        self._inflight.clear()
        for key in [k for k, (_, _, user_ref, _) in self._entries.items()
                    if k.startswith("ownerscope:") and user_ref == user_id]:
            self._entries.pop(key, None)
        if share:
            self._share_invalidation((generation.IDENTITY_OWNER_SCOPE,))

    def _share_invalidation(self, scopes: tuple[str, ...] = ()) -> None:
        """번호 올리기를 지금 루프에 맡기고, 남은 항목은 새 번호로 다시 표시한다.

        로컬 drop 은 지금처럼 그 사용자·세션에만 닿는다. 다른 워커는 범위 단위
        신호만 볼 수 있으므로 그 범위 전체를 버리게 되고, 이 프로세스에 살아남은
        항목은 이 프로세스가 방금 무효화한 대상이 아니므로 새 번호를 달아 계속
        적중시킨다(워커 1개일 때의 적중 수가 그대로다).
        """

        if self._generation_store is None:
            return
        generation.bump_soon(
            self._generation_store,
            scopes or (generation.IDENTITY_AUTH_SESSION,
                       generation.IDENTITY_OWNER_SCOPE,
                       generation.IDENTITY_SUBJECT_MAPPING),
            on_bump=self._restamp,
        )

    def _restamp(self, scope: str, old: int | None, number: int) -> None:
        # 올리기 직전 번호와 같은 항목만 새 번호로 표시한다. 다른 번호·None 항목은
        # 그대로 두어 다음 조회에서 버려지게 한다(다른 워커의 무효화를 되살리지 않는다).
        for key, entry in list(self._entries.items()):
            if (_scope_of_key(key) == scope and len(entry) == 4
                    and type(entry[3]) is int and entry[3] == old):
                self._entries[key] = (entry[0], entry[1], entry[2], number)

    async def _get_or_load(self, key: str, user_ref: str, loader,
                           ttl: float | None = None, ref_of=None) -> Any:
        methods = {'authsession': 'resolve_current_auth_session', 'authsess': 'resolve_auth_session',
                   'ownerscope': 'resolve_connector_owner_scope', 'productuser': 'resolve_product_user_for_subject'}
        now = self._clock()
        current = await self._current_generation(key)
        entry = self._entries.get(key)
        if entry is not None and entry[0] > now:
            stored = entry[3] if len(entry) == 4 else None
            if generation.is_stale(stored, current):
                # Another worker invalidated this scope: the answer is dropped and
                # the authority is asked again, exactly as a local invalidation.
                self._entries.pop(key, None)
            elif stored is None and isinstance(current, int):
                # 번호 없이 저장된 항목은 지금 번호가 생긴 이상 신뢰할 수 없다:
                # 번호를 채택하지 않고 버리고 원본을 다시 부른다. 지금 번호도
                # 없으면(표 없음) 아래 적중 경로가 지금 동작을 유지한다.
                self._entries.pop(key, None)
            else:
                record('wrapper', methods[key.split(':', 1)[0]], True)
                return entry[1]
        record('wrapper', methods[key.split(':', 1)[0]], False)
        self._entries.pop(key, None)
        task = self._inflight.get(key)
        if task is None:
            epoch = self._epoch
            task = asyncio.create_task(self._load(
                key, user_ref, loader, epoch,
                self._ttl_seconds if ttl is None else ttl, ref_of, current))
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
                    ttl: float, ref_of=None, current: int | None = None) -> Any:
        value = await loader()
        if ref_of is not None:
            user_ref = ref_of(value) or ""
        if self._epoch == epoch:
            self._entries[key] = (self._clock() + ttl, value, user_ref, current)
        return value

    async def _current_generation(self, key: str) -> int | None:
        """이 키가 속한 범위의 지금 번호(요청당 범위별 1회). 표가 없으면 ``None``."""

        if self._generation_store is None:
            return None
        return await generation.read_current(self._generation_store, _scope_of_key(key))

    async def resolve_current_auth_session(
        self, *, product_id: str, product_user_id: str,
    ) -> Any:
        """The per-turn chat-owner read, cached per (product, product user)."""
        key = "authsession:" + product_id + ":" + _hash_key(product_user_id)

        async def loader() -> Any:
            return await self._inner.resolve_current_auth_session(
                product_id=product_id, product_user_id=product_user_id,
            )

        from .connector_account_subject import remember_connector_session
        return remember_connector_session(await self._get_or_load(key, product_user_id, loader))

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
        """The request-path session read, cached per session id.

        The revocation guard calls this method too, so a revoked session is
        honoured within the unified auth-session window (300 s default, same
        env as the SQLite session cache) instead of instantly — but every
        revocation event this host serves removes this entry immediately
        through `invalidate_auth_cache`, so the window only bounds how late a
        revocation made in another product is observed. A refusal is never
        stored: the authority is asked again on the next call.
        """
        key = "authsess:" + _hash_key(session_id)

        async def loader() -> Any:
            return await self._inner.resolve_auth_session(session_id=session_id)

        session = await self._get_or_load(
            key, "", loader, ttl=_auth_session_ttl_seconds(),
        )
        if session is None:
            self._entries.pop(key, None)
        from .connector_account_subject import remember_connector_session
        return remember_connector_session(session)

    async def resolve_connector_owner_scope(self, *, session_id: str) -> dict[str, str]:
        """The PC-lane owner scope, cached per canonical session."""
        key = "ownerscope:" + _hash_key(session_id)

        async def loader() -> Any:
            return await self._inner.resolve_connector_owner_scope(session_id=session_id)

        scope = await self._get_or_load(key, "", loader, ttl=_owner_scope_ttl_seconds())
        # The scope answers with the account the session belongs to, so a
        # user-level invalidation can find and drop this entry later.
        if isinstance(scope, dict):
            account_ref = scope.get("account_ref")
            entry = self._entries.get(key)
            if isinstance(account_ref, str) and account_ref and entry is not None:
                self._entries[key] = (entry[0], scope, account_ref, entry[3])
        return scope

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
