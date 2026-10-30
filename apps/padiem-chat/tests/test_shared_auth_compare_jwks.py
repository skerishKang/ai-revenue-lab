import asyncio
import json
from pathlib import Path

from app.shared_auth_compare_flow import WorkerJwksVerifier
from tests.shared_es256_test_crypto import TestES256


def test_shared_vectors_use_cached_jwks_and_fail_closed():
    root = Path(__file__).resolve().parents[3] / 'packages' / 'padiem-auth-verify'
    vector = json.loads((root / 'tests' / 'vectors.json').read_text())
    from worker_runtime_shared_auth_fixture import VECTOR
    assert VECTOR == vector
    wrapper = WorkerJwksVerifier(crypto=TestES256(), clock=lambda:vector['now'])
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
    wrapper = WorkerJwksVerifier(crypto=TestES256(), clock=lambda:1000)
    wrapper.keys, wrapper.until = {'keys':[]}, 1100
    calls = []
    async def fetch():
        calls.append(1)
        raise ValueError('jwks_unavailable')
    wrapper._fetch = fetch
    # A syntactically valid but unknown kid must trigger one refresh, then fail.
    import base64
    header = base64.urlsafe_b64encode(b'{"alg":"ES256","typ":"JWT","kid":"new-key"}').rstrip(b'=').decode()
    body = base64.urlsafe_b64encode(b'{}').rstrip(b'=').decode()
    try:
        asyncio.run(wrapper.verify(header + '.' + body + '.AA'))
    except ValueError:
        pass
    else:
        raise AssertionError('unavailable JWKS accepted')
    assert len(calls) == 1
