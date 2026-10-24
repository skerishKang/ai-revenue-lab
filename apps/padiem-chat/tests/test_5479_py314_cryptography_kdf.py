"""#5479 — the 3.14 password KDF: bundled cryptography, never WebCrypto at 220k.

#5736 rolled the 3.14 runtime back because the only KDF the Worker could reach
there was Workers WebCrypto, which the Production edge refuses above 100,000
iterations while every stored credential carries 220,000. The KDF half of that
is solved here: the dispatch selects the bundled ``cryptography`` package
(Pyodide's own wasm wheel) ahead of WebCrypto, and the stored credential stays
byte-identical.

The runtime itself is NOT shipped: the 3.14 Worker was deployed on 2026-10-24
and answered 6 of 25 sequential ``/health`` requests with HTTP 500 (``SystemError:
Cannot enter a promising task from inside another running promising task. This
is a bug in Pyodide.``), so Production was rolled back to the recorded 3.13
version. The KDF code and its evidence stay, the bundle does not, until that
platform path serves traffic. These tests pin all of it:
1. the bundled KDF produces the stored bytes exactly (byte identity, external
   RFC 2898 vector, round trip at 220,000),
2. the dispatch chooses it on a runtime without ``_hashlib`` and never sends
   the stored cost to WebCrypto — the local Workerd lane accepts 220k, which
   is exactly why #5733's green lane did not prove the edge behaviour,
3. a credential written by either runtime verifies on the other, so the move
   needs no password reset and a rollback needs no re-hash,
4. when nothing can serve the cost the dispatch raises instead of degrading
   to interpreted arithmetic, and
5. the deployed manifest still names the runtime the edge serves cleanly, and
   the unproven 3.14 bundle is not shipped as a production dependency.
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


def test_the_deployed_worker_stays_on_the_runtime_that_serves_auth() -> None:
    """The measured 3.14 failure keeps Production on the 3.13 snapshot."""
    manifest = tomllib.loads(CHAT_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["compatibility_date"] == "2026-08-25"
    assert manifest["compatibility_date"] < PYTHON_314_COMPATIBILITY_DATE
    assert "python_workers" in manifest["compatibility_flags"]


def test_the_unproven_314_kdf_bundle_is_not_shipped() -> None:
    """The provider stays testable without being vendored into Production.

    The 3.14 wasm wheel is only reachable by generating a 3.14 pylock, so
    declaring it here would ship a dependency the deployed runtime neither
    resolves nor needs. When the 3.14 edge path is fixed, re-declare it with a
    fresh 3.14 pylock and a 3.14 lane run.
    """
    declared = _declared_dependencies()
    assert "cryptography==47.0.0" not in declared, declared
    assert "cffi==2.0.0" not in declared, declared
    # It remains a dev dependency, so the provider above is exercised on every
    # test run instead of becoming dead code.
    dev = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["dev"]
    assert any(entry.startswith("cryptography") for entry in dev), dev

    lock = tomllib.loads(PYLOCK.read_text(encoding="utf-8"))
    assert re.fullmatch(r">=3\.13(\.\d+)?", lock["requires-python"]), lock[
        "requires-python"
    ]
    packages = {package["name"] for package in lock["packages"]}
    assert "cryptography" not in packages
    assert "cffi" not in packages


def test_the_incident_record_keeps_the_measured_314_failure() -> None:
    """The rollback reason must survive in the evidence document."""
    document = (
        REPO_ROOT / "docs/operations/5479-py314-runtime-incident-20261024.md"
    ).read_text(encoding="utf-8")
    assert "Cannot enter a promising task" in document
    assert "3.14" in document and "3.13" in document


def test_the_runtime_lane_reports_the_provider_that_served_the_stored_cost() -> None:
    lane = SHARED_LANE.read_text(encoding="utf-8")
    probe = COMBINED_PROBE.read_text(encoding="utf-8")
    assert "B62_WORKER_KDF220K_PROVIDER" in lane
    assert "EXPECTED_KDF_PROVIDER" in lane
    assert "'hashlib'" in lane and "'cryptography'" in lane
    assert "resolve_kdf_provider" in probe
    assert '"provider"' in probe
