"""#7078 B: JWKS cache refresh behaviour of the ES256 verifier.

Covers the production failure where an empty/expired in-memory JWKS cache made
request-time verification answer 503 (fail-closed) instead of fetching keys on
the request. The verifier now refreshes once (single-flight), reuses the last
good keys for a bounded stale window, and reports a reason code.

Run:
    python -m pytest packages/padiem-auth-verify/tests/test_verify_jwks_refresh.py -q
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verify as v  # noqa: E402

KEY = ec.generate_private_key(ec.SECP256R1())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwk(kid: str) -> dict:
    numbers = KEY.public_key().public_numbers()
    return {
        "kid": kid,
        "kty": "EC",
        "crv": "P-256",
        "x": _b64(numbers.x.to_bytes(32, "big")),
        "y": _b64(numbers.y.to_bytes(32, "big")),
        "alg": "ES256",
        "use": "sig",
    }


def _token(kid: str, *, iat: int) -> str:
    header = _b64(json.dumps({"alg": "ES256", "typ": "JWT", "kid": kid}).encode())
    body = _b64(json.dumps({
        "iss": v.ISSUER,
        "aud": "b62",
        "token_use": "access",
        "iat": iat,
        "exp": iat + 600,
        "sub": "user-1",
        "account_id": "sub_" + "a" * 10,
        "sid": "sid-1",
    }).encode())
    der = KEY.sign((header + "." + body).encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return header + "." + body + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


class Clock:
    def __init__(self, now: float = 1_700_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class Fetcher:
    def __init__(self, payload: dict, *, fail_after: int | None = None, delay: float = 0.0):
        self.payload = payload
        self.fail_after = fail_after
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self) -> dict:
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.calls += 1
            calls = self.calls
        if self.fail_after is not None and calls > self.fail_after:
            raise OSError("jwks down")
        return self.payload


def _verifier(fetcher, clock, **kwargs):
    return v.Verifier(audience="b62", fetcher=fetcher, clock=clock, **kwargs)


def test_cold_cache_fetches_once_and_verifies(clock=None):
    clock = Clock()
    fetcher = Fetcher({"keys": [_jwk("k1")]})
    verifier = _verifier(fetcher, clock)
    assert verifier.cached is None
    result = verifier.verify(_token("k1", iat=int(clock.now)))
    assert result["accountId"].startswith("sub_")
    assert fetcher.calls == 1
    assert verifier.last_refresh_reason == "jwks_refreshed"


def test_refresh_failure_uses_stale_keys_within_the_hour():
    clock = Clock()
    fetcher = Fetcher({"keys": [_jwk("k1")]}, fail_after=1)
    verifier = _verifier(fetcher, clock, cache_seconds=60)
    verifier.verify(_token("k1", iat=int(clock.now)))
    clock.now += 120  # past TTL, inside the one-hour stale window
    result = verifier.verify(_token("k1", iat=int(clock.now)))
    assert result["sessionId"] == "sid-1"
    assert fetcher.calls == 2
    assert verifier.last_refresh_reason == "jwks_stale_used"


def test_refresh_failure_without_keys_is_unavailable():
    clock = Clock()
    fetcher = Fetcher({"keys": []}, fail_after=0)
    verifier = _verifier(fetcher, clock)
    with pytest.raises(OSError):
        verifier.verify(_token("k1", iat=int(clock.now)))
    assert verifier.last_refresh_reason == "jwks_unavailable"


def test_stale_window_expiry_refuses():
    clock = Clock()
    fetcher = Fetcher({"keys": [_jwk("k1")]}, fail_after=1)
    verifier = _verifier(fetcher, clock, cache_seconds=60, stale_seconds=3600)
    verifier.verify(_token("k1", iat=int(clock.now)))
    clock.now += 3601
    with pytest.raises(OSError):
        verifier.verify(_token("k1", iat=int(clock.now)))
    assert verifier.last_refresh_reason == "jwks_unavailable"


def test_unknown_kid_refreshes_onces():
    clock = Clock()
    keys = {"keys": [_jwk("k1")]}
    fetcher = Fetcher(keys)
    verifier = _verifier(fetcher, clock)
    verifier.verify(_token("k1", iat=int(clock.now)))
    keys["keys"] = [_jwk("k1"), _jwk("k2")]  # rotation
    verifier.verify(_token("k2", iat=int(clock.now)))
    assert fetcher.calls == 2


def test_unknown_kid_still_absent_after_refresh_is_invalid():
    clock = Clock()
    fetcher = Fetcher({"keys": [_jwk("k1")]})
    verifier = _verifier(fetcher, clock)
    verifier.verify(_token("k1", iat=int(clock.now)))
    with pytest.raises(ValueError):
        verifier.verify(_token("nope", iat=int(clock.now)))
    assert fetcher.calls == 2


def test_concurrent_cold_requests_fetch_once():
    clock = Clock()
    fetcher = Fetcher({"keys": [_jwk("k1")]}, delay=0.05)
    verifier = _verifier(fetcher, clock)
    results: list[bool] = []
    errors: list[Exception] = []

    def worker():
        try:
            verifier.verify(_token("k1", iat=int(clock.now)))
            results.append(True)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(results) == 8
    assert fetcher.calls == 1
