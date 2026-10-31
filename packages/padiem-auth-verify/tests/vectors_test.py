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
