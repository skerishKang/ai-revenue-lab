"""Count a failed password login without losing concurrent failures (#7556).

The failure count used to be read with the credential, increased in Python and
written back as an absolute value. Requests that read the same count all wrote
the same next value, so N concurrent wrong passwords counted as one failure and
the lock after ``limit`` failures could be pushed back N-fold.

Every change here is a single conditional statement in the store:

1. a lapsed lock restarts the count — only the request that still sees that
   exact lapsed lock clears it, so concurrent requests cannot restart twice;
2. the count is increased in SQL (``failed_attempts + 1``) and the new value is
   read back from the same statement, so no increase is lost;
3. the lock is set when that new value reaches the limit and no lock is set
   yet, so a lock already written by a concurrent request is not moved.

A store that does not offer these statements (test doubles) keeps the earlier
absolute write.
"""
from __future__ import annotations

from typing import Any, Callable


async def record_failed_password_attempt(
    store: Any,
    credential: Any,
    *,
    limit: int,
    lock_until_for: Callable[[], str],
    lock_has_lapsed: bool,
) -> int | None:
    """Record one failure; return the count the store holds now when it is known."""

    user_id = credential.user.id
    increment = getattr(store, "increment_password_failures", None)
    restart = getattr(store, "restart_password_failures_after_lapsed_lock", None)
    lock = getattr(store, "lock_password_credential", None)
    if not (callable(increment) and callable(restart) and callable(lock)):
        # Earlier store contract: one absolute write, as before #7556.
        if lock_has_lapsed:
            failures, lock_until = 1, None
        else:
            failures = min(100, credential.failed_attempts + 1)
            lock_until = lock_until_for() if failures >= limit else None
        await store.record_password_failure(user_id, failures, lock_until)
        return failures

    if lock_has_lapsed and credential.locked_until:
        if await restart(user_id, expected_locked_until=credential.locked_until):
            return 1
        # Another request restarted it first; this failure is counted on top.
    failures = await increment(user_id)
    if failures is None:
        return None
    if failures >= limit:
        await lock(user_id, lock_until=lock_until_for(), min_failures=limit)
    return failures
