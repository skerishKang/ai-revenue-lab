"""#5479/#5664 — the NoGilError runtime path: repro, dispatch and enablement.

Three layers are pinned here; each states where it genuinely runs.

1. REAL LOCAL PROOF — the pure-Python RFC 2898 reference in
   ``app/password_kdf.py`` is byte-identical to CPython's C-accelerated
   ``hashlib.pbkdf2_hmac`` for every vector tried here. These tests run on
   COM2's plain CPython and prove the stored ``pbkdf2_sha512$...`` credential
   format is runtime-independent.
2. DISPATCH CONTRACT — the auth routes call the runtime-dispatching async
   twins, which use the C path on the deployed 3.13 runtime and the Workers
   WebCrypto bridge on a KDF-less 3.14 snapshot. Forced-path tests run the
   bridge and the pure-Python reference against hermetic fakes and against
   the C reference.
3. LANE CONTRACT — the sequential/concurrent cold-init repro probe exists for
   the real Workerd lane (it cannot run on COM2: no Workerd on Windows), and
   the deployed compatibility date stays pinned by the #5479 guards.

What is deliberately NOT claimed here: that the upstream workerd#6624 race
is fixed, or that the compatibility date can move today. The bridge removes
the ``_hashlib`` blocker; the runtime move itself is a protected-deploy
decision with its own live verification (COM1 handover in the PR).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_MANIFEST = ROOT / "wrangler.toml"
PROBE_SCRIPT = REPO_ROOT / ".github/scripts/b62_worker_probe_nogil_repro.sh"
COMBINED_PROBE = ROOT / "worker_runtime_combined_probe.py"

sys.path.insert(0, str(ROOT))
from app import password_kdf  # noqa: E402
from app.password_auth import (  # noqa: E402
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)

_VECTORS = [
    (b"runtime-probe-password", b"0123456789abcdef", 1, 32),
    (b"runtime-probe-password", b"0123456789abcdef", 2, 32),
    (b"padiem", b"s", 3, 1),
    (b"padiem", b"s", 3, 64),
    (b"padiem", b"s", 3, 65),
    (b"padiem", b"s", 3, 129),
    (b"multi-byte \xea\xb0\x80 test", bytes(range(16)), 5, 32),
]


def test_python_reference_is_byte_identical_to_hashlib() -> None:
    """REAL LOCAL PROOF: RFC 2898 output does not depend on the implementation."""
    for password, salt, iterations, dklen in _VECTORS:
        expected = hashlib.pbkdf2_hmac("sha512", password, salt, iterations, dklen=dklen)
        actual = password_kdf.pbkdf2_sha512_python(password, salt, iterations, dklen)
        assert actual == expected, (password, salt, iterations, dklen)


def test_stored_format_survives_the_pure_python_path() -> None:
    """A hash written by the C path verifies through the pure-Python path."""
    stored = hash_password("credential-format-password")
    prefix, iterations_raw, salt_raw, digest_raw = stored.split("$", 3)
    assert prefix == "pbkdf2_sha512"
    salt = base64.b64decode(salt_raw)
    expected = base64.b64decode(digest_raw)
    reference = password_kdf.pbkdf2_sha512_python(
        b"credential-format-password", salt, int(iterations_raw), len(expected)
    )
    assert reference == expected
    assert verify_password("credential-format-password", stored)


def test_async_dispatch_matches_the_c_path(monkeypatch) -> None:
    """REAL LOCAL PROOF: the async twins equal the sync path on this runtime."""
    import asyncio

    stored = hash_password("dispatch-password")
    assert asyncio.run(verify_password_async("dispatch-password", stored))
    assert not asyncio.run(verify_password_async("wrong", stored))
    # hash_password_async draws a fresh salt; the format must still verify.
    rotated = asyncio.run(hash_password_async("dispatch-password"))
    assert rotated != stored
    assert asyncio.run(verify_password_async("dispatch-password", rotated))
    # The dispatch routes through the provider, so the runtime detection the
    # 3.14 move relies on is the same one the routes exercise.
    assert password_kdf.pbkdf2_hmac_available() is hasattr(hashlib, "pbkdf2_hmac")


def test_forced_non_c_path_serves_the_same_bytes_via_hermetic_webcrypto(monkeypatch) -> None:
    """The WebCrypto bridge is exercised with a hermetic fake, not js."""
    password_material = b"bridged-password"
    salt_material = bytes(range(16))
    expected = hashlib.pbkdf2_hmac(
        "sha512", password_material, salt_material, 4, dklen=32,
    )

    class _FakeUint8:
        def __init__(self, length):
            self._data = bytearray(length)

        @classmethod
        def new(cls, length):
            return cls(length)

        def __setitem__(self, index, value):
            self._data[index] = value

        def __iter__(self):
            return iter(self._data)

        def to_py(self):
            return bytes(self._data)

    class _FakeKey:
        pass

    captured = {}

    class _FakeSubtle:
        async def importKey(self, fmt, data, algorithm, extractable, usages):
            assert fmt == "raw" and algorithm == "PBKDF2"
            assert usages == ["deriveBits"]
            captured["key_material"] = bytes(data)
            return _FakeKey()

        async def deriveBits(self, params, key, length):
            captured["params"] = dict(params)
            assert params["name"] == "PBKDF2"
            assert params["hash"] == "SHA-512"
            assert params["iterations"] == 4
            assert length == 32 * 8
            return expected

    def loader():
        return _FakeSubtle(), _FakeUint8, lambda value: value

    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", True)

    import asyncio

    bridged = asyncio.run(password_kdf.pbkdf2_sha512_webcrypto(
        password_material, salt_material, 4, 32, runtime_loader=loader,
    ))
    assert bridged == expected
    assert captured["key_material"] == password_material
    assert bytes(captured["params"]["salt"]) == salt_material


def test_auth_routes_call_the_runtime_dispatching_twins() -> None:
    """The 3.14 enablement is wired: routes await the async twins."""
    source = (ROOT / "app/auth_routes.py").read_text(encoding="utf-8")
    assert "hash_password_async" in source
    assert "verify_password_async" in source
    assert "await hash_password_async(" in source
    assert "await verify_password_async(" in source
    assert "hash_password(" not in source.replace("hash_password_async(", "")
    assert "verify_password(" not in source.replace("verify_password_async(", "")


def test_password_auth_keeps_the_sync_c_path_for_the_deployed_runtime() -> None:
    """Production (3.13) keeps the untouched fast path; async adds, not replaces."""
    source = (ROOT / "app/password_auth.py").read_text(encoding="utf-8")
    assert "hashlib.pbkdf2_hmac(" in source
    assert "async def hash_password_async" in source
    assert "async def verify_password_async" in source
    assert "def _verify_parameters" in source


def test_repro_probe_declares_both_traffic_phases() -> None:
    """The sequential/concurrent cold-init probe exists for the real lane."""
    script = PROBE_SCRIPT.read_text(encoding="utf-8")
    assert "B62_NOGIL_SEQUENTIAL" in script
    assert "B62_NOGIL_CONCURRENT_COLD" in script
    assert 'main = "worker_runtime_combined_probe.py"' in script
    assert 'compatibility_date = "$COMPAT_DATE"' in script
    # The probe carries the deployed compatibility date, never a literal.
    assert "PYTHON_314_COMPATIBILITY_DATE" not in script


def test_combined_probe_ready_line_carries_the_async_kdf_state() -> None:
    source = COMBINED_PROBE.read_text(encoding="utf-8")
    assert "_password_kdf_async_state" in source
    assert "kdfasync=" in source
    assert "pbkdf2_sha512_webcrypto" in source


def test_the_deployed_compatibility_date_is_still_pinned() -> None:
    """The runtime move itself stays with the protected deploy (COM1)."""
    import tomllib

    manifest = tomllib.loads(CHAT_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["compatibility_date"] == "2026-08-25"
    assert "python_workers" in manifest["compatibility_flags"]


# --------------------------------------------------------------------------- #
# #5736 — why the 3.14 move could not stay deployed, and what must prove it
# before anyone attempts it again.
#
# The deployed 3.14 Worker answered every register/login/reset with HTTP 500
# from ``app/password_kdf.py``:
#
#   js.crypto.subtle.deriveBits -> NotSupportedError: Pbkdf2 failed:
#   iteration counts above 100000 are not supported (requested 220000).
#
# Workers WebCrypto caps PBKDF2 at 100,000 iterations; stored credentials carry
# 220,000. The bridge check that CI ran used 2,000 iterations, so it passed a
# runtime that could not verify a single member. These tests pin the ceiling and
# the checks that see it.
# --------------------------------------------------------------------------- #

#: Measured on Production, not read off a specification.
WEBCRYPTO_ITERATION_CEILING = 100_000
SHARED_RUNTIME_SCRIPT = REPO_ROOT / ".github/scripts/b62_worker_probe_shared_runtime.sh"


class _JsException(Exception):
    """Stand-in for ``pyodide.ffi.JsException``, the type Workers raises through."""


def _ceiling_subtle(raises_at: int):
    """A hermetic ``subtle`` that refuses PBKDF2 above ``raises_at`` iterations."""

    class _Subtle:
        calls: list[int] = []

        async def importKey(self, fmt, data, algorithm, extractable, usages):
            return object()

        async def deriveBits(self, params, key, length):
            iterations = params["iterations"]
            self.calls.append(iterations)
            if iterations > raises_at:
                raise _JsException(
                    "Pbkdf2 failed: iteration counts above "
                    f"{raises_at} are not supported (requested {iterations})."
                )
            return hashlib.pbkdf2_hmac(
                "sha512", b"ceiling-probe-password", bytes(range(16)), iterations, dklen=32
            )

    return _Subtle()


def _ceiling_loader(subtle):
    class _Uint8:
        def __init__(self, data):
            self._data = data

        @classmethod
        def new(cls, length_or_data):
            return cls(bytes(length_or_data) if isinstance(length_or_data, bytes) else b"\0" * length_or_data)

        def __setitem__(self, index, value):
            pass

        def to_py(self):
            return self._data

    return subtle, _Uint8, lambda value: value


def probe_constant(name: str):
    """Read one module-level constant out of the Workerd-only probe source."""
    import ast

    tree = ast.parse(COMBINED_PROBE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", None) == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a module-level constant in the probe")


def test_stored_password_cost_is_above_the_platform_ceiling() -> None:
    """The single reason a 3.14 deploy cannot serve the existing members."""
    from app.password_auth import PBKDF2_ITERATIONS

    assert PBKDF2_ITERATIONS == 220_000
    assert PBKDF2_ITERATIONS > WEBCRYPTO_ITERATION_CEILING
    # If the stored cost ever drops to or below the ceiling the blocker this
    # test documents is gone, and the 3.14 move becomes a fresh decision.


def test_dispatch_fails_fast_when_the_platform_refuses_the_stored_cost() -> None:
    """A refused KDF must raise, never be reported as a wrong password.

    Mutation proof: if :func:`apbkdf2_sha512` swallowed the platform refusal
    (returning empty bytes or falling through to a different cost), a member
    would be locked out with HTTP 401 and the outage would be invisible.
    """
    import asyncio

    from app.password_auth import PBKDF2_ITERATIONS

    subtle = _ceiling_subtle(WEBCRYPTO_ITERATION_CEILING)
    with pytest.raises(_JsException, match="iteration counts above"):
        asyncio.run(
            password_kdf.pbkdf2_sha512_webcrypto(
                b"ceiling-probe-password",
                bytes(range(16)),
                PBKDF2_ITERATIONS,
                32,
                runtime_loader=lambda: _ceiling_loader(subtle),
            )
        )
    assert subtle.calls == [PBKDF2_ITERATIONS]


def test_verify_password_async_refusal_reaches_the_route(monkeypatch) -> None:
    """The exact Production shape: verify raises, so the route answers HTTP 500.

    On a runtime whose only KDF refuses the stored cost, the auth route cannot
    tell a real credential from a platform refusal, so the refusal must reach
    the caller. A change that turned this into ``return False`` would convert
    the outage into a silent permanent lockout behind a 401 with no traceback.
    """
    import asyncio

    from app import password_auth
    from app.password_auth import PBKDF2_ITERATIONS

    stored = password_auth.hash_password("ceiling-probe-password")
    prefix, iterations_raw, salt_raw, digest_raw = stored.split("$", 3)
    assert int(iterations_raw) == PBKDF2_ITERATIONS

    subtle = _ceiling_subtle(WEBCRYPTO_ITERATION_CEILING)
    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", True)
    monkeypatch.setattr(
        password_kdf, "_native_runtime", lambda: _ceiling_loader(subtle)
    )
    with pytest.raises(_JsException, match="not supported"):
        asyncio.run(
            password_auth.verify_password_async("ceiling-probe-password", stored)
        )
    assert subtle.calls == [PBKDF2_ITERATIONS]


def test_probe_carries_an_authentic_legacy_credential_at_the_stored_cost() -> None:
    """The cross-runtime vector must be a real credential, not a made-up string.

    ``stored=`` only proves anything if this hash is one the 3.13 C path
    actually produced for this password at the stored iteration count.
    """
    from app.password_auth import PBKDF2_ITERATIONS, verify_password

    stored = probe_constant("LEGACY_PYODIDE_313_STORED_HASH")
    password = probe_constant("LEGACY_PYODIDE_313_PASSWORD")
    wrong = probe_constant("LEGACY_PYODIDE_313_WRONG_PASSWORD")

    prefix, iterations_raw, _salt_raw, digest_raw = stored.split("$", 3)
    assert prefix == "pbkdf2_sha512"
    assert int(iterations_raw) == PBKDF2_ITERATIONS
    assert len(base64.b64decode(digest_raw)) == 32
    assert verify_password(password, stored) is True
    assert verify_password(wrong, stored) is False


def test_probe_digest_vectors_equal_the_published_openssl_values() -> None:
    """The digest oracle is external, so a wrong literal fails here first."""
    assert probe_constant("_SHA256_ABC") == hashlib.sha256(b"abc").hexdigest()
    assert probe_constant("_SHA512_ABC") == hashlib.sha512(b"abc").hexdigest()
    key, message = probe_constant("_HMAC_KEY"), probe_constant("_HMAC_MESSAGE")
    assert probe_constant("_HMAC_SHA256_FIXED") == hmac.new(
        key, message, hashlib.sha256
    ).hexdigest()
    assert probe_constant("_HMAC_SHA512_FIXED") == hmac.new(
        key, message, hashlib.sha512
    ).hexdigest()


def test_lane_requires_the_stored_cost_not_just_the_low_iteration_bridge() -> None:
    """The probe must report the ceiling, not hide it behind a low-iteration pass.

    The 2,000-iteration bridge check is still there, and it passed the revision
    #5736 had to roll back; the readiness line now has to say why a runtime that
    passes it still cannot serve a member.
    """
    probe_source = COMBINED_PROBE.read_text(encoding="utf-8")
    assert "_legacy_stored_credential_state" in probe_source
    assert "_digest_surface_state" in probe_source
    assert "stored={stored}" in probe_source
    assert "digest={" in probe_source
    # A blocked ceiling reports the raising type instead of a bare "missing".
    assert 'f"blocked:{type(error).__name__}"' in probe_source

    gate = SHARED_RUNTIME_SCRIPT.read_text(encoding="utf-8")
    # The gate no longer rests on the sync C path being present, and the old
    # single-token PASS marker is gone.
    assert "B62_WORKER_PASSWORD_KDF=PASS" not in gate
    assert "LEGACY_PYODIDE_313_STORED_HASH" in probe_source
    assert "220000" in probe_source
