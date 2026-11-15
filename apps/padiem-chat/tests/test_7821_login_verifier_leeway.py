"""#7821: the login-callback verifier tolerates a host clock trailing the issuer.

The callback used to build its verifier with zero tolerance, so a normal token
whose ``iat`` sat one second ahead (host clock behind the authority by a fraction
of a second) was refused as ``invalid_claims`` and the login answered 503. The
request-time verifier has always allowed the same bound for every request; this
test pins the callback to it, and pins that forged, expired and tampered tokens
are still refused.
"""
from __future__ import annotations

import base64
import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app import cpython_shared_login as login
from app.session_revocation_guard import LOCAL_VERIFY_LEEWAY_SECONDS

NOW = 1_794_000_000
KID = "login-7821"
VERIFY_PATH = Path(__file__).resolve().parents[3] / "packages" / "padiem-auth-verify" / "verify.py"


@pytest.fixture()
def verify_module(monkeypatch):
    """Point ``NativeTokenVerifier`` at the reviewed repo implementation."""
    spec = importlib.util.spec_from_file_location("padiem_auth_verify_repo_7821", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "padiem_auth_verify", module)
    return module


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _signed(module, *, iat=None, exp=None, issuer=None):
    """A token of this product plus the key set that verifies it."""
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    claims = {
        "iss": issuer or module.ISSUER, "aud": "b62", "sub": "user_1",
        "account_id": "sub_7821", "sid": "session_1", "amr": ["pwd"],
        "iat": NOW if iat is None else iat,
        "exp": (NOW + 900) if exp is None else exp,
        "token_use": "access",
    }
    head = _b64u(json.dumps({"alg": "ES256", "typ": "JWT", "kid": KID}, separators=(",", ":")).encode())
    body = _b64u(json.dumps(claims, separators=(",", ":")).encode())
    der = private.sign((head + "." + body).encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = head + "." + body + "." + _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    jwks = {"keys": [{
        "kty": "EC", "crv": "P-256", "kid": KID, "use": "sig", "alg": "ES256",
        "x": _b64u(numbers.x.to_bytes(32, "big")),
        "y": _b64u(numbers.y.to_bytes(32, "big")),
    }]}
    return token, jwks


def _call(module, token, jwks, *, clock):
    """Verify the way the callback does: built leeway, fixed key set, given clock."""
    verifier = module.Verifier("b62", fetcher=lambda: jwks, clock=lambda: clock,
                               leeway_seconds=login.LOGIN_VERIFY_LEEWAY_SECONDS)
    try:
        return verifier.verify(token)["accountId"]
    except ValueError as exc:
        return exc.args[0] if exc.args else ""


def test_login_verifier_uses_the_same_bounded_leeway_as_request_time(verify_module):
    assert login.LOGIN_VERIFY_LEEWAY_SECONDS == LOCAL_VERIFY_LEEWAY_SECONDS > 0


def test_native_verifier_passes_the_leeway_to_the_linked_implementation(verify_module):
    verifier = login.NativeTokenVerifier("b62")
    assert "leeway_seconds" in inspect.signature(verify_module.Verifier.__init__).parameters
    assert verifier._verifier.leeway_seconds == LOCAL_VERIFY_LEEWAY_SECONDS
    explicit = login.NativeTokenVerifier("b62", leeway_seconds=5)
    assert explicit._verifier.leeway_seconds == 5


def test_token_minted_one_second_ahead_now_passes_the_callback(verify_module):
    """The exact production shape: host clock 0.6s behind the issuer."""
    token, jwks = _signed(verify_module)
    assert _call(verify_module, token, jwks, clock=NOW - 0.6) == "sub_7821"


def test_callback_still_refuses_foreign_expired_and_tampered_tokens(verify_module):
    foreign, keys = _signed(verify_module, issuer="https://example.invalid")
    assert _call(verify_module, foreign, keys, clock=NOW) == "invalid_claims"

    expired, keys = _signed(verify_module, iat=NOW - 3600, exp=NOW - 2700)
    assert _call(verify_module, expired, keys, clock=NOW) == "token_expired"

    good, keys = _signed(verify_module)
    tampered = good.rsplit(".", 1)[0] + "." + _b64u(b"\x01" * 64)
    assert _call(verify_module, tampered, keys, clock=NOW) == "invalid_signature"
