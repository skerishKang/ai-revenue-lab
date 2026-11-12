import asyncio
from app import identity_cache_metrics as metrics
from app.identity_call_cache import CachedIdentityAuthority
from app.control_plane_identity_worker import _product_user_cache, _product_user_cache_get, _product_user_cache_put

def test_minute_counts_both_layers_without_keys(capsys):
    class Inner:
        async def resolve_auth_session(self, *, session_id):
            return object()
    async def run():
        cache = CachedIdentityAuthority(Inner())
        await cache.resolve_auth_session(session_id='private-session')
        await cache.resolve_auth_session(session_id='private-session')
    metrics._counts.clear()
    _product_user_cache.clear()
    asyncio.run(run())
    assert _product_user_cache_get('product', 'private-subject') is None
    _product_user_cache_put('product', 'private-subject', 'private-user')
    assert _product_user_cache_get('product', 'private-subject') == 'private-user'
    metrics.flush()
    line = capsys.readouterr().out
    assert 'wrapper.resolve_auth_session:hit=1,miss=1' in line
    assert 'subject.resolve_product_user_for_subject:hit=1,miss=1' in line
    assert 'private' not in line
    _product_user_cache.clear()
