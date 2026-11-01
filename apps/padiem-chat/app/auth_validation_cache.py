"""Short-lived identity results shared by COM2 workers in the existing SQLite DB.

The canonical authority remains the sole producer. Permissions are never stored
here, and an expired entry is never served on an upstream failure. Owner and
session keys come only from verified credentials; credential values are not kept.

The account-link cohort keeps the same discipline on a longer clock. It answers
only "which Chat account is this verified subject", which a new session does not
change, and it shares this module's revision fence and invalidation calls.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from .history import _row_to_dict


class AuthValidationInvalidated(RuntimeError):
    """A logout or permission change completed during an authority lookup."""


def _state_for_request(request: Any):
    try:
        app = getattr(request, 'app', None)
    except KeyError:
        app = None
    return getattr(app, 'state', None)


def cache_for_request(request: Any):
    return getattr(_state_for_request(request), 'auth_validation_cache', None)


def cache_configured_for_request(request: Any) -> bool:
    """Distinguish explicit host cache-off from an unchanged Worker setup."""
    return hasattr(_state_for_request(request), 'auth_validation_cache')


async def invalidate_auth_cache(request: Any, *, user_id: str,
                                session_id: str | None = None) -> None:
    cache = cache_for_request(request)
    if cache is None:
        return
    if session_id:
        await cache.invalidate_session('legacy', user_id, session_id)
    else:
        await cache.invalidate_user(user_id)


class SqliteAuthValidationCache:
    def __init__(self, db, *, ttl_seconds=30, link_ttl_seconds=0, clock=time.time):
        if not 0 < ttl_seconds <= 60:
            raise ValueError('invalid_auth_cache_ttl')
        if not 0 <= link_ttl_seconds <= 900:
            raise ValueError('invalid_account_link_ttl')
        self.db, self.ttl_seconds, self.clock = db, float(ttl_seconds), clock
        self.link_ttl_seconds = float(link_ttl_seconds)
        # Coordination only, not authority: completed entries live in SQLite.
        self._inflight: dict[tuple[str, ...], asyncio.Task] = {}

    @staticmethod
    def _key(kind, owner_id, session_id):
        if kind not in ('legacy', 'shared') or not all(
                isinstance(value, str) and value for value in (owner_id, session_id)):
            raise ValueError('invalid_auth_cache_key')
        digest = hashlib.sha256(session_id.encode('utf-8')).hexdigest()
        return kind, owner_id, digest

    async def _first(self, sql, *values):
        return _row_to_dict(await self.db.prepare(sql).bind(*values).first())

    async def _get(self, key):
        row = await self._first(
            'SELECT product_user_id FROM auth_validation_cache '
            'WHERE kind=? AND owner_id=? AND session_hash=? AND valid_until>?',
            *key, self.clock())
        value = row.get('product_user_id') if row else None
        return value if isinstance(value, str) and value else None

    async def get_or_load(self, kind, owner_id, session_id, loader):
        """Return the authority's user ID; loader returns (user_id, expiry)."""
        key = self._key(kind, owner_id, session_id)
        cached = await self._get(key)
        if cached is not None:
            return cached
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._load(key, loader))
            self._inflight[key] = task
            def finished(done):
                if self._inflight.get(key) is done:
                    self._inflight.pop(key, None)
                # A disconnected caller must not leave an unobserved exception.
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _get_account_link(self, subject):
        row = await self._first(
            'SELECT product_user_id FROM auth_account_link_cache '
            'WHERE owner_id=? AND valid_until>?', subject, self.clock())
        value = row.get('product_user_id') if row else None
        return value if isinstance(value, str) and value else None

    async def get_or_load_account_link(self, subject, loader):
        """Return the Chat account for a verified subject; loader gives (id, expiry).

        Off unless the host asks for it, so a process without migration 088 or
        with caching disabled makes a fresh authority lookup and never reads or
        writes the table, invalidation included.
        """
        if not self.link_ttl_seconds:
            return (await loader())[0]
        if not isinstance(subject, str) or not subject:
            raise ValueError('invalid_account_link_key')
        key = ('link', subject)
        cached = await self._get_account_link(subject)
        if cached is not None:
            return cached
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._load_link(key, loader))
            self._inflight[key] = task
            def finished(done):
                if self._inflight.get(key) is done:
                    self._inflight.pop(key, None)
                # A disconnected caller must not leave an unobserved exception.
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _load_link(self, key, loader):
        subject = key[1]
        cached = await self._get_account_link(subject)
        if cached is not None:
            return cached
        epoch = await self._first('SELECT revision FROM auth_validation_cache_revision WHERE id=1')
        if not epoch or type(epoch.get('revision')) is not int:
            raise RuntimeError('auth_cache_schema_unavailable')
        user_id, authority_expiry = await loader()
        if not isinstance(user_id, str) or not user_id:
            raise ValueError('invalid_auth_cache_result')
        now = self.clock()
        expiry = min(float(authority_expiry), now + self.link_ttl_seconds)
        await self.db.prepare('DELETE FROM auth_account_link_cache WHERE valid_until<=?').bind(now).run()
        row = await self._first(
            'INSERT INTO auth_account_link_cache (owner_id, product_user_id, valid_until) '
            'SELECT ?, ?, ? WHERE ?=(SELECT revision FROM auth_validation_cache_revision WHERE id=1) '
            'ON CONFLICT(owner_id) DO UPDATE SET '
            'product_user_id=excluded.product_user_id, valid_until=excluded.valid_until '
            'RETURNING product_user_id',
            subject, user_id, expiry, epoch['revision'])
        if row is None:
            raise AuthValidationInvalidated('auth_validation_invalidated')
        return row['product_user_id']

    async def _load(self, key, loader):
        cached = await self._get(key)
        if cached is not None:
            return cached
        epoch = await self._first('SELECT revision FROM auth_validation_cache_revision WHERE id=1')
        if not epoch or type(epoch.get('revision')) is not int:
            raise RuntimeError('auth_cache_schema_unavailable')
        user_id, authority_expiry = await loader()
        if not isinstance(user_id, str) or not user_id:
            raise ValueError('invalid_auth_cache_result')
        now = self.clock()
        expiry = min(float(authority_expiry), now + self.ttl_seconds)
        if expiry <= now:
            raise ValueError('expired_auth_cache_result')
        await self.db.prepare('DELETE FROM auth_validation_cache WHERE valid_until<=?').bind(now).run()
        row = await self._first(
            'INSERT INTO auth_validation_cache '
            '(kind, owner_id, session_hash, product_user_id, valid_until) '
            'SELECT ?, ?, ?, ?, ? WHERE ?=(SELECT revision FROM auth_validation_cache_revision WHERE id=1) '
            'ON CONFLICT(kind,owner_id,session_hash) DO UPDATE SET '
            'product_user_id=excluded.product_user_id, valid_until=excluded.valid_until '
            'RETURNING product_user_id',
            *key, user_id, expiry, epoch['revision'])
        if row is None:
            raise AuthValidationInvalidated('auth_validation_invalidated')
        return row['product_user_id']

    async def _invalidate(self, where, values, *, link_where=None, link_values=()):
        # D1 batch / SqliteD1 transaction makes the fence and deletion atomic.
        statements = [
            self.db.prepare('UPDATE auth_validation_cache_revision SET revision=revision+1 WHERE id=1'),
            self.db.prepare('DELETE FROM auth_validation_cache WHERE ' + where).bind(*values),
        ]
        if link_where is not None and self.link_ttl_seconds:
            statements.append(self.db.prepare(
                'DELETE FROM auth_account_link_cache WHERE ' + link_where).bind(*link_values))
        await self.db.batch(statements)

    async def invalidate_session(self, kind, owner_id, session_id):
        # The subject that just signed out stops resolving from the link table as
        # well. A legacy session's owner id is a Chat user, which no link row is
        # keyed by, so the second deletion matches nothing there.
        await self._invalidate('kind=? AND owner_id=? AND session_hash=?',
                               self._key(kind, owner_id, session_id),
                               link_where='owner_id=?', link_values=(owner_id,))

    async def invalidate_user(self, user_id):
        if not isinstance(user_id, str) or not user_id:
            raise ValueError('invalid_auth_cache_owner')
        await self._invalidate('product_user_id=? OR owner_id=?', (user_id, user_id),
                               link_where='product_user_id=?', link_values=(user_id,))

    async def invalidate_all(self):
        await self._invalidate('1=1', (), link_where='1=1')
