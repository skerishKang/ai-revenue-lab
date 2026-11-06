import asyncio
import pytest
from app.identity_call_cache import CachedIdentityAuthority

@pytest.mark.asyncio
async def test_invalidation_does_not_join_old_inflight_lookup():
    started = asyncio.Event()
    release = asyncio.Event()
    class Inner:
        calls = 0
        async def resolve_auth_session(self, *, session_id):
            self.calls += 1
            n = self.calls
            if n == 1:
                started.set()
                await release.wait()
            return n
    inner = Inner()
    cache = CachedIdentityAuthority(inner)
    old = asyncio.create_task(cache.resolve_auth_session(session_id='synthetic'))
    await started.wait()
    cache.invalidate_session('synthetic')
    new = asyncio.create_task(cache.resolve_auth_session(session_id='synthetic'))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()
    assert await old == 1
    assert await new == 2
    assert await cache.resolve_auth_session(session_id='synthetic') == 2
