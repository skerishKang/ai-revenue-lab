import asyncio
import sys
import types
from types import SimpleNamespace

from test_claw_automation_async_composition_seam import _load_worker


def _runtime(monkeypatch, module, observed):
    async def dispatch(app, request, env):
        assert app.state.ready is True
        observed.append(app)
        return module.Response('ok')
    asgi = types.ModuleType('asgi')
    asgi.fetch = dispatch
    monkeypatch.setitem(sys.modules, 'asgi', asgi)
    pyodide = types.ModuleType('pyodide')
    ffi = types.ModuleType('pyodide.ffi')
    ffi.create_proxy = lambda value: value
    monkeypatch.setitem(sys.modules, 'pyodide', pyodide)
    monkeypatch.setitem(sys.modules, 'pyodide.ffi', ffi)
    monkeypatch.setattr(module, 'maybe_dispatch_connector_gateway', _no_gateway)
    return module.Default(SimpleNamespace(), SimpleNamespace(waitUntil=lambda value: None))


async def _no_gateway(**kwargs):
    return None


def _request():
    return SimpleNamespace(url='https://example.invalid/health', js_object=object())


async def test_simultaneous_requests_share_completed_app(monkeypatch):
    module = _load_worker(monkeypatch)
    observed = []
    worker = _runtime(monkeypatch, module, observed)
    started, release = asyncio.Event(), asyncio.Event()
    builds = []
    app = SimpleNamespace(state=SimpleNamespace(ready=False))
    async def build(self):
        builds.append(1)
        started.set()
        await release.wait()
        app.state.ready = True
        return app
    monkeypatch.setattr(module.Default, '_build_worker_app', build)
    requests = [asyncio.create_task(worker.fetch(_request())) for _ in range(5)]
    await started.wait()
    await asyncio.sleep(0)
    assert module._worker_app is None
    assert observed == []
    release.set()
    responses = await asyncio.gather(*requests)
    assert len(responses) == 5
    assert builds == [1]
    assert observed == [app] * 5
    assert module._worker_app is app


async def test_failed_initialization_not_cached_and_next_request_retries(monkeypatch):
    module = _load_worker(monkeypatch)
    observed = []
    worker = _runtime(monkeypatch, module, observed)
    attempts = []
    app = SimpleNamespace(state=SimpleNamespace(ready=True))
    async def build(self):
        attempts.append(1)
        if len(attempts) == 1:
            raise module.ConfigError('synthetic test failure')
        return app
    monkeypatch.setattr(module.Default, '_build_worker_app', build)
    first = await worker.fetch(_request())
    assert first.status == 503
    assert module._worker_app is None
    await worker.fetch(_request())
    assert len(attempts) == 2
    assert observed == [app]
    assert module._worker_app is app


async def test_cancelled_waiter_does_not_cancel_shared_initialization(monkeypatch):
    module = _load_worker(monkeypatch)
    observed = []
    worker = _runtime(monkeypatch, module, observed)
    started, release = asyncio.Event(), asyncio.Event()
    app = SimpleNamespace(state=SimpleNamespace(ready=True))
    calls = []
    async def build(self):
        calls.append(1)
        started.set()
        await release.wait()
        return app
    monkeypatch.setattr(module.Default, '_build_worker_app', build)
    first = asyncio.create_task(worker.fetch(_request()))
    second = asyncio.create_task(worker.fetch(_request()))
    await started.wait()
    first.cancel()
    try:
        await first
    except asyncio.CancelledError:
        pass
    release.set()
    await second
    assert calls == [1]
    assert observed == [app]
    assert module._worker_app is app
