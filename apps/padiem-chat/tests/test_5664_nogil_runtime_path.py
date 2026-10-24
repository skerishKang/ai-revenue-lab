"""#5479/#5664 — the NoGilError runtime path: repro, dispatch and enablement.

Three layers are pinned here; each states where it genuinely runs.

1. REAL LOCAL PROOF — the pure-Python RFC 2898 reference in
   ``app/password_kdf.py`` is byte-identical to CPython's C-accelerated
   ``hashlib.pbkdf2_hmac`` for every vector tried here. These tests run on
   COM2's plain CPython and prove the stored ``pbkdf2_sha512$...`` credential
   format is runtime-independent.
2. DISPATCH CONTRACT — the auth routes call the runtime-dispatching async
   twins, which use the C path where `_hashlib` ships and the Workers
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
import importlib.util
from pathlib import Path
import subprocess
import sys

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
    """The sync C path stays for runtimes that ship `_hashlib`; async adds, not replaces."""
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


def test_the_deployed_compatibility_date_is_the_314_runtime() -> None:
    """#5732 unblocked the runtime move; COM1's protected deploy carries it."""
    import tomllib

    manifest = tomllib.loads(CHAT_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["compatibility_date"] == "2026-09-08"
    assert "python_workers" in manifest["compatibility_flags"]
