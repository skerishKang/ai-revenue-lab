import asyncio
import importlib.util
import json
from pathlib import Path

from app.shared_auth_compare_flow import WorkerJwksVerifier


def test_shared_vectors_use_cached_jwks_and_fail_closed():
    root = Path(__file__).resolve().parents[3] / 'packages' / 'padiem-auth-verify'
    spec = importlib.util.spec_from_file_location('shared_auth_test_verifier', root / 'verify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    vector = json.loads((root / 'tests' / 'vectors.json').read_text())
    wrapper = WorkerJwksVerifier(module.Verifier, clock=lambda:vector['now'])
    # Shared vectors use LoveTree's audience. Production construction fixes b62.
    wrapper.audience = vector['audience']
    calls = []
    async def fetch():
        calls.append(1)
        wrapper.keys, wrapper.until = vector['jwks'], vector['now'] + 300
        return wrapper.keys
    wrapper._fetch = fetch

    async def exercise():
        assert (await wrapper.verify(vector['tokens']['valid']))['accountId'] == 'sub_existing'
        for name in ('wrong_audience', 'wrong_issuer', 'expired', 'forged'):
            try:
                await wrapper.verify(vector['tokens'][name])
            except Exception:
                pass
            else:
                raise AssertionError(name + ' accepted')
    asyncio.run(exercise())
    assert len(calls) == 1


def test_unknown_kid_refreshes_cached_keys_once():
    wrapper = WorkerJwksVerifier(lambda **kwargs: None, clock=lambda:1000)
    wrapper.keys, wrapper.until = {'keys':[]}, 1100
    calls = []
    async def fetch():
        calls.append(1)
        raise ValueError('jwks_unavailable')
    wrapper._fetch = fetch
    # A syntactically valid but unknown kid must trigger one refresh, then fail.
    import base64
    header = base64.urlsafe_b64encode(b'{"kid":"new-key"}').rstrip(b'=').decode()
    try:
        asyncio.run(wrapper.verify(header + '.x.y'))
    except ValueError:
        pass
    else:
        raise AssertionError('unavailable JWKS accepted')
    assert len(calls) == 1
