#!/usr/bin/env python3
"""Controlled before/after Chat request experiment, NOT production route evidence.

Run from any directory. The actual request telemetry, canonical session guard,
auth cache and SQLite facade execute against synthetic identity and five small
SELECT-only ASGI endpoints. Their labels match first-screen GET routes, but
their handlers intentionally do not call external services or customer stores.
One synthetic writer holds its transaction while five requests arrive together.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for source in ('apps/padiem-chat', 'packages/padiem-control-plane',
               'packages/padiem-ai-core', 'apps/padiem-ai-engine/clients/python',
               'apps/korean-ai-code-agent/src'):
    sys.path.insert(0, str(ROOT / source))

from starlette.routing import Route

from app.auth import SESSION_COOKIE, create_session_token
from app.auth_validation_cache import SqliteAuthValidationCache
from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.request_telemetry import RequestTelemetryMiddleware
from app.request_timing import measure
from app.session_revocation_guard import SESSION_VERDICT_STATE_KEY, SessionRevocationGuardMiddleware

ROUTES = (
    ('/api/claw/inbox/alerts', '/api/claw/inbox/{kind}'),
    ('/api/claw/local-access/devices', '/api/claw/local-access/devices'),
    ('/api/claw/local-access/connect', '/api/claw/local-access/connect'),
    ('/api/projects', '/api/projects'),
    ('/api/conversations', '/api/conversations'),
)


async def scenario(*, improved: bool, writer_hold_ms: float = 120,
                   identity_delay_ms: float = 25) -> dict:
    """One burst; the improved cache is warm, just as repeated page GETs are."""
    with tempfile.TemporaryDirectory(prefix='chat-request-benchmark-') as folder:
        connection = sqlite3.connect(str(Path(folder) / 'sample.sqlite3'),
                                     isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE sample (value INTEGER NOT NULL)')
        connection.execute('INSERT INTO sample VALUES (1)')
        connection.executescript((ROOT / 'apps/padiem-chat/migrations/087_auth_validation_cache.sql').read_text())
        writer_entered = threading.Event()

        def hold(value):
            writer_entered.set()
            time.sleep(writer_hold_ms / 1000)
            return value + 1

        connection.create_function('hold', 1, hold)
        options = {'read_workers': 2} if improved else {}
        db = SqliteD1(connection, threaded=True, **options)
        events = []
        authority_calls = 0
        settings = Settings.from_values(runtime_mode='mock', auth_mode='password',
            session_secret='synthetic-benchmark-only-not-a-live-secret',
            public_base_url='https://benchmark.example.invalid')
        session = SimpleNamespace(product_id='b62',
            subject=SimpleNamespace(subject_type='user'),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            effective_state=lambda **kwargs: 'active')

        class Authority:
            async def resolve_auth_session(self, *, session_id):
                nonlocal authority_calls
                authority_calls += 1
                with measure('identity'):
                    await asyncio.sleep(identity_delay_ms / 1000)
                return session

        async def handler(scope, receive, send):
            assert scope['state'][SESSION_VERDICT_STATE_KEY].authenticated
            row = await db.prepare('SELECT value FROM sample').first()
            assert row['value'] in (1, 2)
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{}'})

        app = SimpleNamespace(
            state=SimpleNamespace(settings=settings, control_plane_identity_authority=Authority(),
                auth_validation_cache=SqliteAuthValidationCache(db) if improved else None),
            routes=[Route(template, handler) for _, template in ROUTES])
        wrapped = RequestTelemetryMiddleware(SessionRevocationGuardMiddleware(handler), emitter=events.append)
        cookie = SESSION_COOKIE + '=' + create_session_token(
            settings, 'usr_' + 'a' * 32, canonical_session_id='synthetic-benchmark-session')

        async def invoke(path):
            async def receive():
                return {'type': 'http.disconnect'}

            async def send(message):
                pass

            await wrapped({'type': 'http', 'method': 'GET', 'path': path, 'root_path': '',
                'query_string': b'', 'headers': [(b'cookie', cookie.encode())], 'app': app}, receive, send)

        try:
            if improved:
                await invoke('/api/projects')
                events.clear()
            warmup_calls = authority_calls
            writer = asyncio.create_task(db.prepare('UPDATE sample SET value=hold(value)').run())
            if not await asyncio.to_thread(writer_entered.wait, 5):
                await writer
                raise RuntimeError('synthetic_writer_did_not_enter')
            await asyncio.gather(*(invoke(path) for path, _ in ROUTES))
            await writer
            return {'cache': improved, 'read_workers': 2 if improved else 0,
                    'warmup_identity_calls': warmup_calls,
                    'measured_identity_calls': authority_calls - warmup_calls,
                    'requests': [{key: event[key] for key in ('route', 'status', 'duration_ms', 'timings_ms')}
                                 for event in sorted(events, key=lambda event: event['route'])]}
        finally:
            close_readers = getattr(db, 'close_readers', None)
            if close_readers is not None:
                await close_readers()
            connection.close()


async def benchmark() -> dict:
    before = await scenario(improved=False)
    after = await scenario(improved=True)
    before_rows = {row['route']: row for row in before['requests']}
    comparison = []
    for row in after['requests']:
        old = before_rows[row['route']]
        comparison.append({'route': row['route'], 'before_ms': old['duration_ms'],
            'after_ms': row['duration_ms'], 'before_stages_ms': old['timings_ms'],
            'after_stages_ms': row['timings_ms']})
    return {'source': 'offline_synthetic_request_burst', 'production_measurement': False,
            'handlers': 'SELECT-only fixtures, not product route handlers',
            'writer_hold_ms': 120, 'identity_delay_ms': 25,
            'before': before, 'after': after, 'comparison': comparison}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-only', action='store_true',
                        help='Measure uncached serialized-reader baseline only.')
    args = parser.parse_args()
    if args.before_only:
        result = {'source': 'offline_synthetic_request_burst', 'production_measurement': False,
                  'before': asyncio.run(scenario(improved=False))}
    else:
        result = asyncio.run(benchmark())
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
