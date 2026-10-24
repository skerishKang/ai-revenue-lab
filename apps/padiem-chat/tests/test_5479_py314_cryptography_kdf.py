"""#5479 — the 3.14 password KDF: bundled cryptography, never WebCrypto at 220k.

#5736 rolled the 3.14 runtime back because the only KDF the Worker could reach
there was Workers WebCrypto, which the Production edge refuses above 100,000
iterations while every stored credential carries 220,000. The fix is not a
lower iteration count and not a credential migration: the Worker bundle now
carries the ``cryptography`` package (Pyodide's own wasm wheel), and the async
dispatch selects it ahead of WebCrypto.

These tests pin that decision:
1. the bundled KDF produces the stored bytes exactly (byte identity, external
   RFC 2898 vector, round trip at 220,000),
2. the dispatch chooses it on a runtime without ``_hashlib`` and never sends
   the stored cost to WebCrypto — the local Workerd lane accepts 220k, which
   is exactly why #5733's green lane did not prove the edge behaviour,
3. a credential written by either runtime verifies on the other, so the move
   needs no password reset and a rollback needs no re-hash,
4. when nothing can serve the cost the dispatch raises instead of degrading
   to interpreted arithmetic, and
5. the deployed manifest and the committed dependency locks actually carry
   the runtime and the package (source contract, not a runtime claim).
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import tomllib
from pathlib import Path

import pytest

from app import password_kdf
from app.password_auth import (
    PBKDF2_DKLEN,
    PBKDF2_ITERATIONS,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_ROOT = Path(__file__).resolve().parents[1]
CHAT_MANIFEST = CHAT_ROOT / "wrangler.toml"
PYPROJECT = CHAT_ROOT / "pyproject.toml"
PYLOCK = CHAT_ROOT / "pylock.toml"
SHARED_LANE = REPO_ROOT / ".github/scripts/b62_worker_probe_shared_runtime.sh"
COMBINED_PROBE = CHAT_ROOT / "worker_runtime_combined_probe.py"

#: First compatibility date that selects the Pyodide 3.14 snapshot. That
#: snapshot has no ``_hashlib``, so ``hashlib.pbkdf2_hmac`` does not exist.
PYTHON_314_COMPATIBILITY_DATE = "2026-09-08"

#: PBKDF2-HMAC-SHA512("password", "salt", 220000, 64) — the pinned external
#: vector the isolated 3.14 lane also checks, so this test does not compare
#: the package against itself.
PBKDF2_SHA512_220K_VECTOR = (
    "3ede6b8c2ba493194db1febc21d3be4fc1c7d63f4a6bcc14ad9ae07c63432c6a"
    "867beca4a0dc50070666875567d813cc3bfd3607e634ba6087934cb5ec4bb99a"
)


class _WebCryptoMustNotRun:
    """A ``_native_runtime`` stand-in that fails the test if it is reached."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError(
            "the stored 220,000-iteration cost must never reach WebCrypto: the "
            "Production edge refuses PBKDF2 above 100,000 iterations (#5736)"
        )


def _c_reference(password: bytes, salt: bytes, dklen: int = PBKDF2_DKLEN) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha512", password, salt, PBKDF2_ITERATIONS, dklen=dklen
    )


# --------------------------------------------------------------------------- #
# 1. The bundled KDF is the stored credential, bit for bit.
# --------------------------------------------------------------------------- #
def test_the_bundled_kdf_matches_the_c_path_at_the_stored_cost() -> None:
    password, salt = b"runtime-probe-password", bytes(range(16))
    derived = password_kdf.pbkdf2_sha512_cryptography(
        password, salt, PBKDF2_ITERATIONS, PBKDF2_DKLEN
    )
    assert derived == _c_reference(password, salt)


def test_the_bundled_kdf_matches_the_pinned_external_vector() -> None:
    derived = password_kdf.pbkdf2_sha512_cryptography(
        b"password", b"salt", PBKDF2_ITERATIONS, 64
    )
    assert derived.hex() == PBKDF2_SHA512_220K_VECTOR


def test_a_member_credential_written_by_the_313_runtime_verifies_on_314(
    monkeypatch,
) -> None:
    """No re-hash, no reset: the stored string stays valid across the move."""
    stored = hash_password("member-password-2026")  # the 3.13 C path
    assert stored.startswith(f"pbkdf2_sha512${PBKDF2_ITERATIONS}$")

    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", True)
    assert asyncio.run(verify_password_async("member-password-2026", stored))
    assert not asyncio.run(verify_password_async("wrong-member-password", stored))


def test_a_credential_hashed_on_314_still_verifies_on_a_313_rollback(
    monkeypatch,
) -> None:
    """Rollback safety: hashes written by the new provider are not orphaned."""
    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", True)
    stored = asyncio.run(hash_password_async("rollback-password-2026"))
    assert stored.startswith(f"pbkdf2_sha512${PBKDF2_ITERATIONS}$")
    # The sync verifier is the untouched 3.13 C path a rollback would serve.
    assert verify_password("rollback-password-2026", stored) is True
    assert verify_password("wrong-rollback-password", stored) is False


# --------------------------------------------------------------------------- #
# 2. Dispatch priority: cryptography serves 220k, WebCrypto never sees it.
# --------------------------------------------------------------------------- #
def test_the_dispatch_prefers_the_bundled_kdf_over_webcrypto(monkeypatch) -> None:
    sentinel = _WebCryptoMustNotRun()
    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", True)
    monkeypatch.setattr(password_kdf, "_native_runtime", sentinel)

    assert (
        password_kdf.resolve_kdf_provider(PBKDF2_ITERATIONS)
        == password_kdf.PROVIDER_CRYPTOGRAPHY
    )
    derived = asyncio.run(
        password_kdf.apbkdf2_sha512(
            b"runtime-probe-password", bytes(range(16)), PBKDF2_ITERATIONS, PBKDF2_DKLEN
        )
    )
    assert derived == _c_reference(b"runtime-probe-password", bytes(range(16)))
    assert sentinel.calls == 0


def test_the_c_path_stays_first_where_the_runtime_has_it(monkeypatch) -> None:
    """3.13 keeps the fastest path — the move must not slow the old runtime."""
    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", False)
    assert (
        password_kdf.resolve_kdf_provider(PBKDF2_ITERATIONS)
        == password_kdf.PROVIDER_HASHLIB
    )


def test_webcrypto_is_only_reachable_below_the_edge_iteration_ceiling(
    monkeypatch,
) -> None:
    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", True)
    monkeypatch.setattr(password_kdf, "FORCE_CRYPTOGRAPHY_UNAVAILABLE", True)

    bounded = password_kdf.resolve_kdf_provider(
        password_kdf.WEBCRYPTO_MAX_ITERATIONS
    )
    above = password_kdf.resolve_kdf_provider(
        password_kdf.WEBCRYPTO_MAX_ITERATIONS + 1
    )
    assert bounded == password_kdf.PROVIDER_WEBCRYPTO
    assert above == password_kdf.PROVIDER_UNAVAILABLE
    # The stored cost is far above the ceiling: this is the #5736 blocker.
    assert (
        password_kdf.resolve_kdf_provider(PBKDF2_ITERATIONS)
        == password_kdf.PROVIDER_UNAVAILABLE
    )


def test_the_dispatch_fails_fast_and_names_what_is_missing(monkeypatch) -> None:
    """Never a silent downgrade to interpreted arithmetic."""
    monkeypatch.setattr(password_kdf, "FORCE_NON_C_PATH", True)
    monkeypatch.setattr(password_kdf, "FORCE_CRYPTOGRAPHY_UNAVAILABLE", True)

    with pytest.raises(password_kdf.Pbkdf2Unavailable) as raised:
        asyncio.run(
            password_kdf.apbkdf2_sha512(
                b"ceiling-probe", bytes(range(16)), PBKDF2_ITERATIONS, 32
            )
        )
    message = str(raised.value)
    assert "cryptography" in message
    assert str(password_kdf.WEBCRYPTO_MAX_ITERATIONS) in message


def test_the_pure_python_reference_is_kept_but_never_an_automatic_switch() -> None:
    """It remains byte-identical evidence, not a hidden login path."""
    pure = password_kdf.pbkdf2_sha512_python(b"password", b"salt", 2, 64)
    assert pure == hashlib.pbkdf2_hmac("sha512", b"password", b"salt", 2, dklen=64)
    source = (CHAT_ROOT / "app/password_kdf.py").read_text(encoding="utf-8")
    # The fallback is reachable only through the hermetic ``runtime_loader``
    # seam; a deployed Worker raises instead.
    assert "if runtime_loader is None:" in source


# --------------------------------------------------------------------------- #
# 3. The deployed configuration carries the runtime and the package.
# --------------------------------------------------------------------------- #
def _declared_dependencies() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def test_the_deployed_compatibility_date_selects_python_314() -> None:
    manifest = tomllib.loads(CHAT_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["compatibility_date"] == PYTHON_314_COMPATIBILITY_DATE
    assert "python_workers" in manifest["compatibility_flags"]


def test_the_worker_bundle_declares_the_kdf_the_314_runtime_needs() -> None:
    declared = _declared_dependencies()
    assert "cryptography==47.0.0" in declared, declared
    # cffi 2.1.1 has no wasm wheel and cannot be built for emscripten.
    assert "cffi==2.0.0" in declared, declared


def test_the_committed_pylock_targets_the_314_runtime_and_carries_the_wheel() -> None:
    text = PYLOCK.read_text(encoding="utf-8")
    lock = tomllib.loads(text)
    assert re.fullmatch(r">=3\.14(\.\d+)?", lock["requires-python"]), lock["requires-python"]
    packages = {package["name"]: package for package in lock["packages"]}
    assert packages["cryptography"]["version"] == "47.0.0"
    assert packages["cffi"]["version"] == "2.0.0"
    wheels = " ".join(
        wheel["url"] for wheel in packages["cryptography"].get("wheels", [])
    )
    assert "pyemscripten" in wheels and "cryptography-47.0.0" in wheels
    assert "pycparser" in packages  # cffi's runtime dependency


def test_the_runtime_lane_reports_the_provider_that_served_the_stored_cost() -> None:
    lane = SHARED_LANE.read_text(encoding="utf-8")
    probe = COMBINED_PROBE.read_text(encoding="utf-8")
    assert "B62_WORKER_KDF220K_PROVIDER" in lane
    assert "EXPECTED_KDF_PROVIDER" in lane
    assert "'hashlib'" in lane and "'cryptography'" in lane
    assert "resolve_kdf_provider" in probe
    assert '"provider"' in probe
