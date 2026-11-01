"""Request timing is isolated, private and transparent to streaming ASGI."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.routing import Route

from app.request_telemetry import RequestTelemetryMiddleware
from app.request_timing import STAGES, measure, record_duration, reset_timing, start_timing, timed_async


async def _endpoint(request):
    raise AssertionError("route matching must not call the endpoint")


def _scope(path, template=None, **overrides):
    result = {
        'type': 'http', 'method': 'GET', 'path': path, 'root_path': '',
        'query_string': b'', 'headers': [],
        'app': SimpleNamespace(routes=[Route(template or path, _endpoint)]),
    }
    result.update(overrides)
    return result


async def _receive():
    return {'type': 'http.disconnect'}


async def _discard(message):
    pass


@pytest.mark.asyncio
async def test_request_context_isolated_across_tasks_and_propagated_to_threads():
    entered = 0
    both_ready = asyncio.Event()

    async def invocation(stage, value):
        nonlocal entered
        timing, token = start_timing()
        try:
            entered += 1
            if entered == 2:
                both_ready.set()
            await both_ready.wait()
            await asyncio.to_thread(record_duration, stage, value)
            record_duration('private_path_or_sql_is_not_a_stage', 999)
            return timing.snapshot()
        finally:
            reset_timing(token)

    identity, database = await asyncio.gather(invocation('identity', 13), invocation('sqlite_execute', 7))
    assert identity == {stage: (13 if stage == 'identity' else 0) for stage in STAGES}
    assert database == {stage: (7 if stage == 'sqlite_execute' else 0) for stage in STAGES}
    # A completed request cannot supply measurements to a later request.
    record_duration('identity', 200)
    fresh, token = start_timing()
    try:
        assert fresh.snapshot() == dict.fromkeys(STAGES, 0)
    finally:
        reset_timing(token)


@pytest.mark.asyncio
async def test_duration_decorator_records_failure_without_changing_exception():
    timing, token = start_timing()

    @timed_async('p01')
    async def failure():
        await asyncio.sleep(0)
        raise RuntimeError('synthetic-private-upstream-error')

    try:
        with pytest.raises(RuntimeError, match='synthetic-private-upstream-error'):
            await failure()
        assert timing.snapshot()['p01'] > 0
    finally:
        reset_timing(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('decorated', [False, True])
async def test_measurement_preserves_frozen_canonical_exception(decorated):
    from app.control_plane_identity import IdentityBridgeError

    failure = IdentityBridgeError(401, 'inactive_auth_session', 'Synthetic canonical refusal')
    timing, token = start_timing()

    @timed_async('identity')
    async def refused():
        raise failure

    try:
        with pytest.raises(IdentityBridgeError) as caught:
            if decorated:
                await refused()
            else:
                with measure('identity'):
                    raise failure
        assert caught.value is failure
        assert caught.value.status_code == 401
        assert caught.value.code == 'inactive_auth_session'
        assert timing.snapshot()['identity'] > 0
    finally:
        reset_timing(token)


@pytest.mark.asyncio
async def test_middleware_records_only_template_and_fixed_timing_dimensions():
    private = 'synthetic-private-document-token'
    events, wire = [], []

    async def app(scope, receive, send):
        record_duration('auth', 7)
        await asyncio.to_thread(record_duration, 'sqlite_wait', 2)
        await send({'type': 'http.response.start', 'status': 403, 'headers': []})
        await send({'type': 'http.response.body', 'body': json.dumps({
            'error': {'code': 'synthetic_refusal', 'message': private},
            'profile': private,
        }).encode()})

    async def send(message):
        wire.append(message)

    scope = _scope('/api/claw/documents/' + private, '/api/claw/documents/{document_id}',
                   query_string=('token=' + private).encode(),
                   headers=[(b'authorization', ('Bearer ' + private).encode()),
                            (b'cookie', ('session=' + private).encode())])
    await RequestTelemetryMiddleware(app, emitter=events.append)(scope, _receive, send)
    assert len(events) == 1
    event = events[0]
    assert event['route'] == '/api/claw/documents/{document_id}'
    assert event['status'] == 403
    assert event['timings_ms']['auth'] == 7
    assert event['timings_ms']['sqlite_wait'] == 2
    assert set(event['timings_ms']) == set(STAGES)
    assert private not in json.dumps(event)
    assert private.encode() in wire[-1]['body']  # actual response remains intact


@pytest.mark.asyncio
async def test_concurrent_middleware_requests_do_not_mix_timing_totals():
    events = []
    arrived = 0
    ready = asyncio.Event()

    async def app(scope, receive, send):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await ready.wait()
        record_duration('queue', 20 if scope['path'].endswith('one') else 40)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})

    middleware = RequestTelemetryMiddleware(app, emitter=events.append)
    await asyncio.gather(
        middleware(_scope('/api/one'), _receive, _discard),
        middleware(_scope('/api/two'), _receive, _discard),
    )
    assert {event['route']: event['timings_ms']['queue'] for event in events} == {
        '/api/one': 20, '/api/two': 40,
    }


@pytest.mark.asyncio
async def test_first_stream_chunk_passes_before_request_finishes():
    events, bodies = [], []
    first_chunk = asyncio.Event()
    finish_stream = asyncio.Event()

    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', b'text/event-stream')]})
        with measure('p01'):
            await send({'type': 'http.response.body', 'body': b'data: first\n\n', 'more_body': True})
            await finish_stream.wait()
            await send({'type': 'http.response.body', 'body': b'data: done\n\n', 'more_body': False})

    async def send(message):
        if message['type'] == 'http.response.body':
            bodies.append(message['body'])
            first_chunk.set()

    task = asyncio.create_task(RequestTelemetryMiddleware(app, emitter=events.append)(
        _scope('/api/claw/stream'), _receive, send))
    await asyncio.wait_for(first_chunk.wait(), timeout=1)
    assert bodies == [b'data: first\n\n']
    assert not task.done() and events == []
    finish_stream.set()
    await task
    assert bodies == [b'data: first\n\n', b'data: done\n\n']
    assert len(events) == 1
    assert events[0]['duration_ms'] >= 0
    assert events[0]['timings_ms']['p01'] > 0


@pytest.mark.asyncio
async def test_failure_keeps_duration_and_does_not_log_exception_material():
    events = []

    async def app(scope, receive, send):
        with measure('identity'):
            raise RuntimeError('synthetic-private-error-with-token')

    with pytest.raises(RuntimeError, match='synthetic-private-error-with-token'):
        await RequestTelemetryMiddleware(app, emitter=events.append)(
            _scope('/api/failure'), _receive, _discard)
    assert len(events) == 1 and events[0]['status'] == 500
    assert events[0]['timings_ms']['identity'] > 0
    assert 'synthetic-private-error-with-token' not in json.dumps(events)
