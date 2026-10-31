"""Simulate the Worker's js.fetch boundary without contacting production."""
import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import app
from app.shared_auth_compare_flow import TOKEN_URL, exchange_with_httpx
from tests.test_httpx_compat_workers_timeout import FakeHeaders, _load_workers_shim


def test_exchange_runs_over_workers_fetch_compatibility_shim():
    calls = []
    class Reader:
        def __init__(self): self.first = True
        async def read(self):
            if self.first:
                self.first = False
                return SimpleNamespace(done=False, value=b'{"access_token":"synthetic"}')
            return SimpleNamespace(done=True, value=None)
        async def cancel(self): pass
    class Body:
        def getReader(self): return Reader()
    async def fetch(url, init):
        calls.append((url, init))
        return SimpleNamespace(status=200, headers=FakeHeaders(), body=Body())
    shim = _load_workers_shim(fetch)
    fake_auth = types.ModuleType('app.auth')
    fake_auth.MAX_AUTH_RESPONSE_BYTES = 1024 * 1024
    with patch.dict(sys.modules, {'app.httpx_compat':shim, 'app.auth':fake_auth}):
        with patch.object(app, 'httpx_compat', shim, create=True):
            result = asyncio.run(exchange_with_httpx(TOKEN_URL, {'code':'synthetic'}))
    assert result == {'access_token':'synthetic'}
    assert calls[0][0] == TOKEN_URL
    assert calls[0][1]['method'] == 'POST'
    assert calls[0][1]['redirect'] == 'manual'
