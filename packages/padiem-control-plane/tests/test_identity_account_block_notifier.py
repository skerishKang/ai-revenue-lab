import asyncio
import sys
import types

workers = types.ModuleType('workers')
workers.WorkerEntrypoint = object
sys.modules.setdefault('workers', workers)
from identity_account_block_notifier import deliver, URL


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


if __name__ == '__main__':
    test_private_sender_fixed_route_and_failure()
    print('block notifier unit: PASS')
