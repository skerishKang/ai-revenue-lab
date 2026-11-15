"""#6460 4-1 third round: a short, owner-scoped window over the connector scope.

``resolve_pc_connector_scope`` re-read the identity authority on every Claw
read (b62 session -> b54 canonical session -> connector owner scope). COM2's
journal put ``/api/claw/local-access/devices`` at a 4.6 s identity median, and
the account-link cache (#6573, migration 088) covers only the b62 link, so this
window covers the other two reads without adding a table or a migration.

What the window is allowed to hold:

* only a successful, READY result. A refusal, an error and a timeout are never
  stored, so a permission that was just granted or withdrawn answers on the very
  next request;
* a key of (app state, identity authority, kind, owner account, workspace), with
  both objects stored next to the value and compared by identity - a recycled
  ``id`` can never hand one app or one test another's scope;
* one authority round trip per key at a time (single-flight): concurrent
  requests for the same key share the one result, the shape #6599 uses for the
  B14 roster.

Explicit invalidation inside Chat covers the places this product changes a
connector or a PC itself: pairing claim/adopt/revoke, connector consent
grant/revoke and logout. A revocation performed in another service is observed
at most ``PADIEM_CHAT_SCOPE_CACHE_SECONDS`` late (default 30 s, maximum 300 s),
which is the cost of not persisting a table here.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Awaitable, Callable

from . import worker_cache_generation as generation

SCOPE_CACHE_SECONDS_ENV = "PADIEM_CHAT_SCOPE_CACHE_SECONDS"
_SCOPE_CACHE_DEFAULT = 30.0
_SCOPE_CACHE_MAX = 300.0
#: Small on purpose: one entry per account/workspace that read Claw recently.
_MAX_ENTRIES = 512

#: The one request kind that exists today. The dimension is in the key so a
#: future resolution (e.g. a per-device target) can never read this entry.
KIND_CONNECTOR_SCOPE = "connector_scope"

#: key -> (expires_at, app_state, authority, value, generation)
_CACHE: dict[tuple[Any, ...], tuple[float, Any, Any, Any, int | None]] = {}
_LOCKS: dict[tuple[Any, ...], asyncio.Lock] = {}


def scope_cache_seconds() -> float:
    """Configured window in seconds; 0 switches the cache off."""
    raw = os.getenv(SCOPE_CACHE_SECONDS_ENV)
    if raw is None or not raw.strip():
        return _SCOPE_CACHE_DEFAULT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _SCOPE_CACHE_DEFAULT
    if value != value or value < 0 or value > _SCOPE_CACHE_MAX:
        return _SCOPE_CACHE_DEFAULT
    return value


def clear_scope_cache() -> None:
    _CACHE.clear()


def invalidate_owner_scope(owner_id: Any, *, store: Any = None) -> None:
    """Drop every cached scope of one account, in every workspace and kind.

    Called where Chat itself changes a connector or a pairing. A non-string is
    simply nothing to forget, so callers can pass a row field without a guard.

    #7543 5단계: 로컬 drop 뒤에 같은 변화를 다른 워커에도 알린다. 이 프로세스에
    살아남은 다른 계정의 항목은 새 번호로 다시 표시해 워커 1개일 때의 적중 결과를
    유지한다. 범위는 계정별로 나누지 않는다 — 무효화 이벤트가 드물고, 버린 쪽은
    다음 조회에서 원본을 다시 부르면 되기 때문이다.
    """
    if not isinstance(owner_id, str) or not owner_id:
        return
    for key in [key for key in _CACHE if key[3] == owner_id]:
        _CACHE.pop(key, None)
    generation.bump_soon(
        store if store is not None else generation.current_request_store(),
        (generation.PC_CONNECTOR_SCOPE,),
        on_bump=_restamp,
    )


def _restamp(scope: str, number: int) -> None:
    """번호를 올린 뒤 이 프로세스에 남은 항목을 새 번호로 다시 표시한다."""

    for key, entry in list(_CACHE.items()):
        if len(entry) == 5:
            _CACHE[key] = (entry[0], entry[1], entry[2], entry[3], number)


def _prune(now: float) -> None:
    if len(_CACHE) < _MAX_ENTRIES:
        return
    for key, entry in list(_CACHE.items()):
        if entry[0] <= now:
            _CACHE.pop(key, None)
    while len(_CACHE) >= _MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))
    for key, lock in list(_LOCKS.items()):
        if not lock.locked() and key not in _CACHE:
            _LOCKS.pop(key, None)


def _hit(key: tuple[Any, ...], *, state: Any, authority: Any,
         current: int | None) -> tuple[bool, Any]:
    entry = _CACHE.get(key)
    if entry is None or entry[0] <= time.monotonic():
        return False, None
    if entry[1] is not state or entry[2] is not authority:
        return False, None
    if generation.is_stale(entry[4] if len(entry) == 5 else None, current):
        # 다른 워커가 이 범위를 무효화했다: 버리고 원본을 다시 부른다.
        _CACHE.pop(key, None)
        return False, None
    return True, entry[3]


async def cached_connector_scope(
    *,
    state: Any,
    authority: Any,
    owner_id: str,
    workspace_id: str,
    loader: Callable[[], Awaitable[Any]],
    kind: str = KIND_CONNECTOR_SCOPE,
) -> Any:
    """Resolve one connector scope inside the short window, or with ``loader``.

    ``loader`` runs at most once per key per window, and only a result whose
    ``ready`` is exactly ``True`` is stored - every refusal keeps its own path.
    """
    ttl = scope_cache_seconds()
    key = (id(state), id(authority), kind, owner_id, workspace_id)
    # 요청당 한 번(이 범위에서는 한 번) 번호를 읽는다. 표가 없으면 ``None`` 이고
    # 오늘 동작 그대로다.
    current = await generation.read_current(
        generation.store_for_state(state), generation.PC_CONNECTOR_SCOPE
    )
    if ttl > 0:
        found, value = _hit(key, state=state, authority=authority, current=current)
        if found:
            return value
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    async with lock:
        if ttl > 0:
            found, value = _hit(key, state=state, authority=authority, current=current)
            if found:
                return value
        value = await loader()
        if ttl > 0 and getattr(value, "ready", False) is True:
            now = time.monotonic()
            _prune(now)
            _CACHE[key] = (now + ttl, state, authority, value, current)
        return value


__all__ = [
    "KIND_CONNECTOR_SCOPE",
    "SCOPE_CACHE_SECONDS_ENV",
    "cached_connector_scope",
    "clear_scope_cache",
    "invalidate_owner_scope",
    "scope_cache_seconds",
]
