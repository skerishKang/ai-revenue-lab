import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

workers = types.ModuleType('workers')


class _WorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _DurableObject:
    def __init__(self, ctx=None, env=None):
        pass


class _Response:
    def __init__(self, *args, **kwargs):
        pass


workers.WorkerEntrypoint = _WorkerEntrypoint
workers.DurableObject = _DurableObject
workers.Response = _Response
sys.modules.setdefault('workers', workers)

from identity_account_block_notifier import BlockNotifier, URL, deliver


def test_private_sender_fixed_route_and_failure():
    observed = []
    class Binding:
        async def fetch(self, request):
            observed.append(request)
            return types.SimpleNamespace(status=200)
    factory = lambda account, secret: (URL, account, bool(secret))
    result = asyncio.run(deliver(Binding(), 'synthetic-secret', {'account_id': 'sub_test'}, factory))
    assert result == {'ok': True}
    assert observed == [(URL, 'sub_test', True)]
    assert asyncio.run(deliver(Binding(), '', {'account_id': 'sub_test'}, factory))['ok'] is False
    assert asyncio.run(deliver(Binding(), 'x', {'account_id': 'sub_test', 'extra': 1}, factory))['ok'] is False
    class Broken:
        async def fetch(self, request):
            raise RuntimeError('synthetic outage')
    assert asyncio.run(deliver(Broken(), 'x', {'account_id': 'sub_test'}, factory))['ok'] is False


def _load_identity_worker():
    path = Path(__file__).parents[1] / 'identity_authority_worker.py'
    spec = importlib.util.spec_from_file_location('padiem_identity_authority_worker_block_notifier_test', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_identity_worker_exposes_named_entrypoint_not_default_rpc():
    worker = _load_identity_worker()
    assert worker.BlockNotifier is BlockNotifier
    assert issubclass(worker.BlockNotifier, sys.modules['workers'].WorkerEntrypoint)
    assert asyncio.iscoroutinefunction(worker.BlockNotifier.notify_account_blocked)
    assert not hasattr(worker.Default, 'notify_account_blocked')


def test_named_entrypoint_passes_both_bindings(monkeypatch):
    calls = []
    async def fake_deliver(binding, secret, payload):
        calls.append((binding, secret, payload))
        return {'ok': True}
    monkeypatch.setattr('identity_account_block_notifier.deliver', fake_deliver)
    notifier = BlockNotifier(env=SimpleNamespace(PADIEM_AUTH_ADMIN='auth-binding', PADIEM_AUTH_ADMIN_SECRET='synthetic-admin-secret'))
    result = asyncio.run(notifier.notify_account_blocked({'account_id': 'sub_test'}))
    assert result == {'ok': True}
    assert calls == [('auth-binding', 'synthetic-admin-secret', {'account_id': 'sub_test'})]


def test_named_entrypoint_fails_closed_without_bindings():
    result = asyncio.run(BlockNotifier(env=SimpleNamespace()).notify_account_blocked({'account_id': 'sub_test'}))
    assert result == {'ok': False, 'error': 'not_configured'}


if __name__ == '__main__':
    test_private_sender_fixed_route_and_failure()
    test_identity_worker_exposes_named_entrypoint_not_default_rpc()
    test_named_entrypoint_fails_closed_without_bindings()
    print('block notifier unit: PASS')
