"""Short-lived identity results shared by COM2 workers in the existing SQLite DB.

The canonical authority remains the sole producer. Permissions are never stored
here, and an expired entry is never served on an upstream failure. Owner and
session keys come only from verified credentials; credential values are not kept.

The account-link cohort keeps the same discipline on a longer clock. It answers
only "which Chat account is this verified subject", which a new session does not
change, and it shares this module's revision fence and invalidation calls.

#7084: the revocation guard's canonical-session rows keep a longer window than
the shared account mapping. A successful session check is reused for
``session_ttl_seconds`` (300 s by default,
``PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS``) because 7 days of COM2 journalling
showed 7,736 checks paying 420 upstream calls of ~1.2 s each - the 30 s window
expired between request bursts faster than the short refresh margin could renew
it. Every revocation event this host serves (logout, self-service password
change, account deletion, admin membership and role changes) deletes that row and
bumps the revision fence before it answers, so the window only bounds how late a
revocation made in another product is observed.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from .history import _row_to_dict
from .identity_cache_metrics import record as record_cache_metric
from .shared_login_timing import record_login_timing


def _sql_timing_operation(sql: str) -> str | None:
    normalized = ' '.join(str(sql).lower().split())
    if normalized.startswith('select product_user_id from auth_validation_cache ') or \
            normalized.startswith('select product_user_id, valid_until from auth_validation_cache '):
        return 'session_read'
    if normalized.startswith('select product_user_id from auth_account_link_cache '):
        return 'link_read'
    if normalized.startswith('select revision from auth_validation_cache_revision '):
        return 'revision_read'
    if normalized.startswith('insert into auth_validation_cache '):
        return 'session_upsert'
    if normalized.startswith('insert into auth_account_link_cache '):
        return 'link_upsert'
    if normalized.startswith('delete from auth_validation_cache '):
        return 'session_expired_delete'
    if normalized.startswith('delete from auth_account_link_cache '):
        return 'link_expired_delete'
    return None


def _record_cache_sql(operation: str | None, started: float) -> None:
    if operation is None:
        return
    duration_ms = (time.perf_counter() - started) * 1000
    record_login_timing('sqlite_auth_' + operation, duration_ms)


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
    from .identity_call_cache import CachedIdentityAuthority

    # The wrapped per-turn identity reads (chat owner, PC owner scope) share
    # the same invalidation events: logout, deletion, permission change and
    # session revocation must not leave a cached answer standing.
    authority = getattr(_state_for_request(request),
                        'control_plane_identity_authority', None)
    if isinstance(authority, CachedIdentityAuthority):
        authority.invalidate_user(user_id)
        if session_id:
            authority.invalidate_session(session_id)
    cache = cache_for_request(request)
    if cache is None:
        return
    if session_id:
        await cache.invalidate_session('legacy', user_id, session_id)
    else:
        await cache.invalidate_user(user_id)


def drop_cached_owner_scope_of(request: Any, user_id: Any) -> None:
    """Drop one user's cached connector-owner scope answers (no session kill).

    Pairing, unpairing/disconnect and PC designation mutate answer spaces
    other than the session itself; this single dropped answer cold-checks
    the authority on the next read. In contrast with `invalidate_auth_cache`
    (logout/deletion/admin change — sessions die too) this touches no
    auth-session row: the user stays signed in, only the stale scope
    answer goes.
    """
    from .identity_call_cache import CachedIdentityAuthority

    if not isinstance(user_id, str) or not user_id:
        return
    authority = getattr(_state_for_request(request),
                        'control_plane_identity_authority', None)
    if isinstance(authority, CachedIdentityAuthority):
        authority.invalidate_owner_scope_of_user(user_id)


#: Upper bound for the canonical-session window (#7084). Deliberately longer
#: than the 60 s cap on the shared account mapping: a session row is refused
#: from the same table it was written to, and every revocation event this host
#: serves deletes it before answering.
_MAX_SESSION_TTL_SECONDS = 900

#: #7078 B: minimum retention for revocation markers in auth_validation_cache.
#: 20 minutes (1,200 s) covers the 15-minute access lifetime + 60 s verifier
#: leeway + 60 s host clock skew with margin, without adding a second table.
DENYLIST_TTL_SECONDS = 20 * 60
_REVOKED_MARKER = '__revoked__'
_RESERVED_OWNER_PREFIXES = ('deny:', 'allow:')


async def record_auth_revocation(
    request: Any,
    *,
    session_ids: tuple[str, ...] = (),
    account_ids: tuple[str, ...] = (),
    user_ids: tuple[str, ...] = (),
    permanent: bool = False,
    ttl_seconds: float | None = None,
) -> None:
    """Record revocation markers in the shared SQLite auth_validation_cache.

    Raises ``RuntimeError`` when the cache is absent or cannot write, so a
    caller that requires confirmed revocation fails closed. ``ttl_seconds``
    lengthens the markers past the default window (#7554: a session the
    authority could not revoke stays denied for as long as its cookie lives).
    """
    cache = cache_for_request(request)
    record = getattr(cache, 'record_revocation', None) if cache is not None else None
    if not callable(record):
        raise RuntimeError('auth_validation_cache_unavailable')
    extra = {} if ttl_seconds is None else {'ttl_seconds': ttl_seconds}
    await record(
        session_ids=session_ids,
        account_ids=account_ids,
        user_ids=user_ids,
        permanent=permanent,
        **extra,
    )


class SqliteAuthValidationCache:
    def __init__(self, db, *, ttl_seconds=30, link_ttl_seconds=0,
                 refresh_ahead_seconds=0, session_ttl_seconds=None,
                 clock=time.time):
        if not 0 < ttl_seconds <= 60:
            raise ValueError('invalid_auth_cache_ttl')
        if session_ttl_seconds is None:
            session_ttl_seconds = ttl_seconds
        if not 0 < session_ttl_seconds <= _MAX_SESSION_TTL_SECONDS:
            raise ValueError('invalid_auth_cache_session_ttl')
        if not 0 <= link_ttl_seconds <= 900:
            raise ValueError('invalid_account_link_ttl')
        if not 0 <= refresh_ahead_seconds:
            raise ValueError('invalid_auth_cache_refresh_ahead')
        self.db, self.ttl_seconds, self.clock = db, float(ttl_seconds), clock
        # #7084: the guard's 'legacy' session rows use this window; the
        # 'shared' account mapping keeps ``ttl_seconds``.
        self.session_ttl_seconds = float(session_ttl_seconds)
        self.link_ttl_seconds = float(link_ttl_seconds)
        # #7084: reload an entry shortly before it expires so the request that
        # would have paid for the reload already has a valid answer. The margin
        # can never reach the window it applies to, so no expired answer is ever
        # served and the revocation bound stays exactly that window.
        self.refresh_ahead_seconds = min(float(refresh_ahead_seconds),
                                         self.session_ttl_seconds / 2)
        # Coordination only, not authority: completed entries live in SQLite.
        self._inflight: dict[tuple[str, ...], asyncio.Task] = {}

    @staticmethod
    def _key(kind, owner_id, session_id):
        if (kind not in ('legacy', 'shared')
                or not all(isinstance(value, str) and value for value in (owner_id, session_id))
                or owner_id.startswith(_RESERVED_OWNER_PREFIXES)):
            raise ValueError('invalid_auth_cache_key')
        digest = hashlib.sha256(session_id.encode('utf-8')).hexdigest()
        return kind, owner_id, digest

    async def _first(self, sql, *values):
        operation = _sql_timing_operation(sql)
        started = time.perf_counter()
        try:
            return _row_to_dict(await self.db.prepare(sql).bind(*values).first())
        finally:
            _record_cache_sql(operation, started)

    async def _run(self, sql, *values):
        operation = _sql_timing_operation(sql)
        started = time.perf_counter()
        try:
            statement = self.db.prepare(sql)
            if values:
                statement = statement.bind(*values)
            return await statement.run()
        finally:
            _record_cache_sql(operation, started)

    async def _cached_row(self, key):
        return await self._first(
            'SELECT product_user_id, valid_until FROM auth_validation_cache '
            'WHERE kind=? AND owner_id=? AND session_hash=? AND valid_until>? AND product_user_id!=?',
            *key, self.clock(), _REVOKED_MARKER)

    async def _get(self, key):
        row = await self._cached_row(key)
        value = row.get('product_user_id') if row else None
        return value if isinstance(value, str) and value else None

    def _schedule(self, key, loader, *, force=False):
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._load(key, loader, force=force))
            self._inflight[key] = task
            def finished(done):
                if self._inflight.get(key) is done:
                    self._inflight.pop(key, None)
                # A disconnected caller must not leave an unobserved exception.
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        return task

    async def get_or_load(self, kind, owner_id, session_id, loader):
        """Return the authority's user ID; loader returns (user_id, expiry)."""
        key = self._key(kind, owner_id, session_id)
        cached = await self._get(key)
        if cached is not None:
            return cached
        return await asyncio.shield(self._schedule(key, loader))

    async def get_or_load_ahead(self, kind, owner_id, session_id, loader,
                                background_loader=None):
        """Like ``get_or_load``, but reload shortly before the entry expires.

        A still-valid entry within ``refresh_ahead_seconds`` of its expiry is
        returned immediately and one single-flight reload runs behind the
        response. Customers therefore pay the authority call on a background
        task instead of inside the request. Only a still-valid answer is served:
        an expired entry takes the same blocking path as before, so a revoked
        session is still refused within the TTL and an authority outage still
        reports the same retryable failure.
        """
        if not self.refresh_ahead_seconds:
            return await self.get_or_load(kind, owner_id, session_id, loader)
        key = self._key(kind, owner_id, session_id)
        row = await self._cached_row(key)
        value = row.get('product_user_id') if row else None
        if not (isinstance(value, str) and value):
            return await self.get_or_load(kind, owner_id, session_id, loader)
        try:
            remaining = float(row.get('valid_until')) - self.clock()
        except (TypeError, ValueError):
            remaining = 0.0
        if remaining <= self.refresh_ahead_seconds:
            # Not awaited: the answer is already valid, the reload only replaces
            # it. ``force`` is required because the entry is still fresh, and a
            # normal load would return that same entry without asking again. A
            # failure leaves the current entry in place until it expires.
            scheduled = key not in self._inflight
            self._schedule(key, background_loader or loader, force=True)
            if scheduled:
                # Bounded per-minute aggregate, so the move off the request path
                # stays measurable without a log line per reload.
                record_cache_metric('auth_validation', 'refresh_ahead', True)
        return value

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
        await self._run('DELETE FROM auth_account_link_cache WHERE valid_until<=?', now)
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

    async def _load(self, key, loader, *, force=False):
        if not force:
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
        # #7084: only the guard's session verdict uses the long window.
        ttl = self.session_ttl_seconds if key[0] == 'legacy' else self.ttl_seconds
        expiry = min(float(authority_expiry), now + ttl)
        if expiry <= now:
            raise ValueError('expired_auth_cache_result')
        await self._run('DELETE FROM auth_validation_cache WHERE valid_until<=?', now)
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
        # Denylist ('deny:*') and post-revocation allow ('allow:*') markers live
        # in the same table and must survive positive-cache invalidations.
        statements = [
            self.db.prepare('UPDATE auth_validation_cache_revision SET revision=revision+1 WHERE id=1'),
            self.db.prepare(
                "DELETE FROM auth_validation_cache "
                "WHERE owner_id NOT LIKE 'deny:%' AND owner_id NOT LIKE 'allow:%' AND ("
                + where + ")"
            ).bind(*values),
        ]
        if link_where is not None and self.link_ttl_seconds:
            statements.append(self.db.prepare(
                'DELETE FROM auth_account_link_cache WHERE ' + link_where).bind(*link_values))
        await self.db.batch(statements)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    async def record_revocation(
        self,
        *,
        session_ids: tuple[str, ...] = (),
        account_ids: tuple[str, ...] = (),
        user_ids: tuple[str, ...] = (),
        permanent: bool = False,
        ttl_seconds: float = DENYLIST_TTL_SECONDS,
    ) -> None:
        """Persist revocation markers in ``auth_validation_cache`` across workers."""
        if ttl_seconds <= 0:
            raise ValueError('invalid_denylist_ttl')
        now = self.clock()
        until = now + float(ttl_seconds)
        upsert_sql = (
            "INSERT INTO auth_validation_cache "
            "(kind, owner_id, session_hash, product_user_id, valid_until) "
            "VALUES ('shared', ?, ?, ?, ?) "
            "ON CONFLICT(kind,owner_id,session_hash) DO UPDATE SET "
            "product_user_id=excluded.product_user_id, "
            "valid_until=MAX(auth_validation_cache.valid_until, excluded.valid_until)"
        )
        statements = [
            self.db.prepare('UPDATE auth_validation_cache_revision SET revision=revision+1 WHERE id=1'),
            self.db.prepare('DELETE FROM auth_validation_cache WHERE valid_until<=?').bind(now),
        ]
        seen_sids: set[str] = set()
        for sid in session_ids:
            if isinstance(sid, str) and sid and sid not in seen_sids:
                seen_sids.add(sid)
                digest = self._digest(sid)
                statements.append(self.db.prepare(
                    "DELETE FROM auth_validation_cache "
                    "WHERE kind='shared' AND owner_id='allow:sid' AND session_hash=?"
                ).bind(digest))
                statements.append(self.db.prepare(upsert_sql).bind(
                    'deny:sid', digest, _REVOKED_MARKER, until))
        account_tag = 'deny:del' if permanent else 'deny:acc'
        user_tag = 'deny:del' if permanent else 'deny:usr'
        seen_uids: set[str] = set()
        for uid in user_ids:
            if isinstance(uid, str) and uid and uid not in seen_uids:
                seen_uids.add(uid)
                digest = self._digest(uid)
                statements.append(self.db.prepare(
                    "DELETE FROM auth_validation_cache "
                    "WHERE kind='shared' AND owner_id='allow:sid' AND product_user_id=?"
                ).bind(uid))
                statements.append(self.db.prepare(
                    "DELETE FROM auth_validation_cache "
                    "WHERE owner_id NOT LIKE 'deny:%' AND owner_id NOT LIKE 'allow:%' "
                    "AND (product_user_id=? OR owner_id=?)"
                ).bind(uid, uid))
                statements.append(self.db.prepare(upsert_sql).bind(
                    user_tag, digest, _REVOKED_MARKER, until))
        seen_aids: set[str] = set()
        for aid in account_ids:
            if isinstance(aid, str) and aid and aid not in seen_aids:
                seen_aids.add(aid)
                digest = self._digest(aid)
                statements.append(self.db.prepare(
                    "DELETE FROM auth_validation_cache "
                    "WHERE owner_id NOT LIKE 'deny:%' AND owner_id NOT LIKE 'allow:%' "
                    "AND owner_id=?"
                ).bind(aid))
                statements.append(self.db.prepare(upsert_sql).bind(
                    account_tag, digest, _REVOKED_MARKER, until))
        await self.db.batch(statements)

    async def record_allowed_session(
        self,
        *,
        session_id: str,
        user_id: str,
        account_id: str | None = None,
        valid_until: float | None = None,
    ) -> None:
        """Mark a freshly issued/refreshed padiem-auth session and its user mapping."""
        if not (isinstance(session_id, str) and session_id
                and isinstance(user_id, str) and user_id):
            return
        now = self.clock()
        expiry = max(float(valid_until or 0.0), now + DENYLIST_TTL_SECONDS)
        digest = self._digest(session_id)
        upsert_sql = (
            "INSERT INTO auth_validation_cache "
            "(kind, owner_id, session_hash, product_user_id, valid_until) "
            "VALUES ('shared', ?, ?, ?, ?) "
            "ON CONFLICT(kind,owner_id,session_hash) DO UPDATE SET "
            "product_user_id=excluded.product_user_id, valid_until=excluded.valid_until"
        )
        statements = [
            self.db.prepare(upsert_sql).bind('allow:sid', digest, user_id, expiry),
        ]
        if isinstance(account_id, str) and account_id.startswith('sub_'):
            statements.append(
                self.db.prepare(upsert_sql).bind(account_id, digest, user_id, expiry)
            )
        await self.db.batch(statements)

    async def is_revoked(
        self,
        *,
        session_ids: tuple[str, ...] = (),
        account_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Check whether the session/account/user is revoked in ``auth_validation_cache``.

        Any database or schema failure propagates so the caller fails closed.
        """
        clauses: list[str] = []
        params: list[Any] = [self.clock()]
        primary_sid_digest: str | None = None
        for idx, sid in enumerate(session_ids):
            if isinstance(sid, str) and sid:
                digest = self._digest(sid)
                if idx == 0:
                    primary_sid_digest = digest
                clauses.append("(owner_id='deny:sid' AND session_hash=?)")
                params.append(digest)
        if primary_sid_digest is not None:
            clauses.append("(owner_id='allow:sid' AND session_hash=?)")
            params.append(primary_sid_digest)
        if isinstance(account_id, str) and account_id:
            digest = self._digest(account_id)
            clauses.append("(owner_id IN ('deny:acc','deny:del') AND session_hash=?)")
            params.append(digest)
        if isinstance(user_id, str) and user_id:
            digest = self._digest(user_id)
            clauses.append("(owner_id IN ('deny:usr','deny:del') AND session_hash=?)")
            params.append(digest)
        if not clauses:
            raise ValueError('missing_revocation_keys')
        sql = (
            "SELECT owner_id, session_hash, product_user_id FROM auth_validation_cache "
            "WHERE kind='shared' AND valid_until>? AND (" + " OR ".join(clauses) + ")"
        )
        started = time.perf_counter()
        try:
            statement = self.db.prepare(sql).bind(*params)
            raw_result = await statement.all()
        finally:
            _record_cache_sql('session_read', started)
        raw_rows = getattr(raw_result, 'results', raw_result) or ()
        rows = [r for r in (_row_to_dict(item) for item in raw_rows) if r]
        if not rows:
            return False
        allow_user: str | None = None
        hard_denied = False
        soft_denied = False
        for row in rows:
            owner = row.get('owner_id')
            marker = row.get('product_user_id')
            if owner == 'allow:sid' and row.get('session_hash') == primary_sid_digest:
                if isinstance(marker, str) and marker and marker != _REVOKED_MARKER:
                    allow_user = marker
            elif owner in ('deny:sid', 'deny:del') and marker == _REVOKED_MARKER:
                hard_denied = True
            elif owner in ('deny:usr', 'deny:acc') and marker == _REVOKED_MARKER:
                soft_denied = True
        if hard_denied:
            return True
        if soft_denied:
            if user_id and allow_user == user_id:
                return False
            return True
        return False

    @staticmethod
    def _is_missing_optional_table(exc: Exception) -> bool:
        return 'no such table' in str(exc).lower()

    async def resolve_local_product_user(self, account_id: str) -> str | None:
        """Resolve a verified ``sub_...`` to its Chat ``usr_...`` using local SQLite only."""
        if not isinstance(account_id, str) or not account_id.startswith('sub_'):
            return None
        now = self.clock()
        row = await self._first(
            "SELECT product_user_id FROM auth_validation_cache "
            "WHERE kind='shared' AND owner_id=? AND valid_until>? AND product_user_id!=? "
            "ORDER BY valid_until DESC LIMIT 1",
            account_id, now, _REVOKED_MARKER,
        )
        uid = row.get('product_user_id') if row else None
        if isinstance(uid, str) and uid:
            return uid
        for sql, args in (
            (
                "SELECT product_user_id FROM auth_account_link_cache "
                "WHERE owner_id=? AND valid_until>?",
                (account_id, now),
            ),
            (
                "SELECT product_user_id FROM control_plane_identity_shadow "
                "WHERE canonical_subject_id=? LIMIT 1",
                (account_id,),
            ),
            (
                "SELECT id AS product_user_id FROM users "
                "WHERE provider_subject=? LIMIT 1",
                ('shared:' + account_id,),
            ),
        ):
            try:
                found = await self._first(sql, *args)
            except Exception as exc:
                if self._is_missing_optional_table(exc):
                    continue
                raise
            candidate = found.get('product_user_id') if found else None
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

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
