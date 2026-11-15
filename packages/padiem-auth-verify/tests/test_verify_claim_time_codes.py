"""#7821: the verifier names the time conditions and keeps the rest unchanged.

Before this test file a token whose ``iat`` sat one second ahead of the host
clock — a normal token when the host clock trails the issuer by a fraction of a
second — was refused as ``invalid_claims``, which read like a forged claim in the
login-callback log. The refusal is still a refusal; only the code it reports and
the bounded tolerance changed.

Run:
    python -m pytest packages/padiem-auth-verify/tests/test_verify_claim_time_codes.py -q
"""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("padiem_verify_7821", ROOT / "verify.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

NOW = 1_794_000_000
KID = "k7821"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _key():
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    jwk = {
        "kty": "EC", "crv": "P-256", "kid": KID, "use": "sig", "alg": "ES256",
        "x": _b64u(numbers.x.to_bytes(32, "big")),
        "y": _b64u(numbers.y.to_bytes(32, "big")),
    }
    return private, jwk


PRIVATE, JWK = _key()
JWKS = {"keys": [JWK]}


def _token(**overrides) -> str:
    kid = overrides.pop("kid", KID)
    claims = {
        "iss": MODULE.ISSUER, "aud": "b62", "sub": "user_1", "account_id": "sub_7821",
        "sid": "session_1", "amr": ["pwd"], "iat": NOW, "exp": NOW + 900,
        "token_use": "access",
    }
    claims.update(overrides)
    head = _b64u(json.dumps({"alg": "ES256", "typ": "JWT", "kid": kid}, separators=(",", ":")).encode())
    body = _b64u(json.dumps(claims, separators=(",", ":")).encode())
    der = PRIVATE.sign((head + "." + body).encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return head + "." + body + "." + _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _verify(token: str, *, clock=lambda: NOW, leeway=0, fetcher=None):
    calls: list = []

    def fetch():
        calls.append(1)
        return JWKS

    verifier = MODULE.Verifier("b62", fetcher=fetcher or fetch, clock=clock, leeway_seconds=leeway)
    try:
        verifier.verify(token)
    except ValueError as exc:
        return (exc.args[0] if exc.args else ""), len(calls)
    return "ok", len(calls)


def test_cold_verifier_accepts_a_fresh_token():
    """A new process (empty JWKS cache) must not refuse a good token."""
    code, fetches = _verify(_token())
    assert (code, fetches) == ("ok", 1)


def test_token_minted_one_second_ahead_is_named_not_called_forged():
    code, _ = _verify(_token())
    assert code == "ok"
    assert _verify(_token(), clock=lambda: NOW - 0.6)[0] == "token_not_yet_valid"


def test_bounded_leeway_accepts_clock_trail_and_still_refuses_beyond_it():
    assert _verify(_token(), clock=lambda: NOW - 0.6, leeway=60)[0] == "ok"
    assert _verify(_token(iat=NOW + 60), clock=lambda: NOW, leeway=60)[0] == "ok"
    assert _verify(_token(iat=NOW + 61), clock=lambda: NOW, leeway=60)[0] == "token_not_yet_valid"


def test_expired_token_is_refused_with_its_own_code():
    stale = _token(iat=NOW - 1020, exp=NOW - 120)
    assert _verify(stale)[0] == "token_expired"
    assert _verify(stale, leeway=60)[0] == "token_expired"


def test_lifetime_longer_than_the_contract_is_still_a_claim_failure():
    assert _verify(_token(exp=NOW + 901))[0] == "invalid_claims"


@pytest.mark.parametrize("overrides", [
    {"iss": "https://example.invalid"},
    {"aud": "b61"},
    {"token_use": "refresh"},
    {"iat": "1794000000"},
    {"exp": "1794000900"},
    {"sub": ""},
    {"account_id": "usr_7821"},
    {"account_id": ""},
    {"sid": ""},
    {"account_created_at": NOW + 1},
    {"account_created_at": -1},
    {"amr": []},
    {"amr": "pwd"},
])
def test_other_claim_failures_keep_the_original_code(overrides):
    assert _verify(_token(**overrides))[0] == "invalid_claims"


def test_unknown_key_refreshes_once_and_does_not_loop():
    """A token signed with a kid the cache does not hold costs one extra fetch."""
    code, fetches = _verify(_token(kid="k7821-unknown"))
    assert code == "unknown_key"
    assert fetches == 2
