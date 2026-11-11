import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('padiem_verify', root / 'verify.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
vector = json.loads((Path(__file__).parent / 'vectors.json').read_text())


def test_shared_es256_vectors_and_jwks_cache():
    calls = []
    def fetch():
        calls.append(1)
        return vector['jwks']
    verify = module.Verifier(vector['audience'], fetcher=fetch, clock=lambda: vector['now'])
    assert verify.verify(vector['tokens']['valid'])['accountId'] == 'sub_existing'
    for name in ('wrong_audience', 'wrong_issuer', 'expired', 'forged'):
        try:
            verify.verify(vector['tokens'][name])
        except Exception:
            pass
        else:
            raise AssertionError(name + ' was accepted')
    assert len(calls) == 1


if __name__ == '__main__':
    test_shared_es256_vectors_and_jwks_cache()
    print('shared Python vectors: PASS')


def test_jwks_fetch_sends_named_user_agent(monkeypatch):
    import io
    from unittest.mock import MagicMock
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = io.BytesIO(b'{"keys": []}')
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *a: opener)
    assert module._fetch() == {"keys": []}
    request = opener.open.call_args.args[0]
    assert request.full_url == module.JWKS_URL
    assert request.get_header("User-agent") == "padiem-boot-recovery/1.0"
    assert opener.open.call_args.kwargs["timeout"] == 5


def test_amr_claim_is_returned_when_valid_and_rejected_when_malformed():
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    priv = ec.generate_private_key(ec.SECP256R1())
    nums = priv.public_key().public_numbers()
    b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    jwk = {
        'kty': 'EC', 'crv': 'P-256', 'kid': 'k1', 'alg': 'ES256', 'use': 'sig',
        'x': b64u(nums.x.to_bytes(32, 'big')), 'y': b64u(nums.y.to_bytes(32, 'big')),
    }
    header = b64u(b'{"alg":"ES256","typ":"JWT","kid":"k1"}')

    def mint(extra):
        payload = {
            'iss': 'https://auth.padiem.net', 'aud': 'b62', 'sub': 'sub_existing',
            'account_id': 'sub_existing', 'sid': 'sid_1', 'iat': 1000, 'exp': 1900,
            'token_use': 'access', **extra,
        }
        body = b64u(json.dumps(payload).encode())
        r, s = decode_dss_signature(priv.sign(f'{header}.{body}'.encode(), ec.ECDSA(hashes.SHA256())))
        return f'{header}.{body}.' + b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))

    verifier = module.Verifier('b62', fetcher=lambda: {'keys': [jwk]}, clock=lambda: 1000)
    assert verifier.verify(mint({'amr': ['pwd']}))['amr'] == ['pwd']
    assert verifier.verify(mint({'amr': ['google']}))['amr'] == ['google']
    assert 'amr' not in verifier.verify(mint({}))
    for bad in ([], [''], [123], 'pwd', None):
        try:
            verifier.verify(mint({'amr': bad}))
        except ValueError:
            pass
        else:
            raise AssertionError(f'malformed amr {bad!r} accepted')


def test_clock_skew_leeway_bounds_iat_and_exp():
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    priv = ec.generate_private_key(ec.SECP256R1())
    nums = priv.public_key().public_numbers()
    b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    jwk = {
        'kty': 'EC', 'crv': 'P-256', 'kid': 'k1', 'alg': 'ES256', 'use': 'sig',
        'x': b64u(nums.x.to_bytes(32, 'big')), 'y': b64u(nums.y.to_bytes(32, 'big')),
    }
    header = b64u(b'{"alg":"ES256","typ":"JWT","kid":"k1"}')

    def mint(iat, exp):
        payload = {
            'iss': 'https://auth.padiem.net', 'aud': 'b62', 'sub': 'sub_existing',
            'account_id': 'sub_existing', 'sid': 'sid_leeway', 'iat': iat, 'exp': exp,
            'token_use': 'access',
        }
        body = b64u(json.dumps(payload).encode())
        r, s = decode_dss_signature(priv.sign(f'{header}.{body}'.encode(), ec.ECDSA(hashes.SHA256())))
        return f'{header}.{body}.' + b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))

    now = [1000]
    strict = module.Verifier('b62', fetcher=lambda: {'keys': [jwk]}, clock=lambda: now[0])
    skewed = module.Verifier('b62', fetcher=lambda: {'keys': [jwk]}, clock=lambda: now[0], leeway_seconds=60)

    future_60 = mint(1060, 1960)
    try:
        strict.verify(future_60)
    except ValueError:
        pass
    else:
        raise AssertionError('strict verifier accepted future iat')
    assert skewed.verify(future_60)['sessionId'] == 'sid_leeway'

    try:
        skewed.verify(mint(1061, 1961))
    except ValueError:
        pass
    else:
        raise AssertionError('iat beyond leeway accepted')

    token = mint(1000, 1900)
    now[0] = 1959
    assert skewed.verify(token)['sessionId'] == 'sid_leeway'
    now[0] = 1960
    try:
        skewed.verify(token)
    except ValueError:
        pass
    else:
        raise AssertionError('exp at leeway boundary accepted')

    for invalid_leeway in (-1, 61, True, '60'):
        try:
            module.Verifier('b62', fetcher=lambda: {'keys': [jwk]}, leeway_seconds=invalid_leeway)
        except ValueError:
            pass
        else:
            raise AssertionError(f'invalid leeway {invalid_leeway!r} accepted')

