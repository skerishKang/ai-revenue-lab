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
import base64
import json


def _fresh_key():
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.private_numbers()

    def part(value):
        return base64.urlsafe_b64encode(value.to_bytes(32, 'big')).rstrip(b'=').decode()

    private = {'kty': 'EC', 'crv': 'P-256', 'x': part(numbers.public_numbers.x),
               'y': part(numbers.public_numbers.y), 'd': part(numbers.private_value)}
    public = {'kty': 'EC', 'crv': 'P-256', 'x': private['x'], 'y': private['y'],
              'kid': 'skew-test', 'alg': 'ES256', 'use': 'sig'}
    return private, {'keys': [public]}


def _signed(private, payload):
    head = base64.urlsafe_b64encode(
        json.dumps({'alg': 'ES256', 'typ': 'JWT', 'kid': 'skew-test'},
                   separators=(',', ':')).encode()).rstrip(b'=').decode()
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode()).rstrip(b'=').decode()
    signature = asyncio.run(TestES256().sign(private, (head + '.' + body).encode()))
    return head + '.' + body + '.' + base64.urlsafe_b64encode(signature).rstrip(b'=').decode()


def _skew_verifier(now, jwks, skew=30):
    wrapper = WorkerJwksVerifier(crypto=TestES256(), clock=lambda: now,
                                 clock_skew_seconds=skew)
    wrapper.keys, wrapper.until = jwks, now + 300
    return wrapper


def _token(iat, exp, now):
    private, jwks = _fresh_key()
    token = _signed(private, {
        'iss': 'https://auth.padiem.net', 'aud': 'b62', 'sub': 'synthetic',
        'account_id': 'sub_existing', 'sid': 'synthetic_session',
        'iat': iat, 'exp': exp, 'token_use': 'access'})
    return token, jwks


def test_iat_a_few_seconds_ahead_is_accepted_within_the_skew():
    # #7699: the authority signs on its own clock; a host a second behind must
    # not turn that token into a login failure.
    now = 1_700_000_000
    token, jwks = _token(now + 2, now + 900, now)
    wrapper = _skew_verifier(now, jwks)
    assert asyncio.run(wrapper.verify(token))['accountId'] == 'sub_existing'


def test_iat_far_ahead_is_refused_with_its_own_code():
    now = 1_700_000_000
    token, jwks = _token(now + 120, now + 900, now)
    wrapper = _skew_verifier(now, jwks)
    try:
        asyncio.run(wrapper.verify(token))
    except ValueError as exc:
        assert str(exc) == 'token_not_yet_valid'
    else:
        raise AssertionError('a token minted far ahead was accepted')


def test_expired_token_keeps_failing_with_its_own_code():
    now = 1_700_000_000
    token, jwks = _token(now - 1000, now - 1, now)
    wrapper = _skew_verifier(now, jwks)
    try:
        asyncio.run(wrapper.verify(token))
    except ValueError as exc:
        assert str(exc) == 'token_expired'
    else:
        raise AssertionError('an expired token was accepted')
