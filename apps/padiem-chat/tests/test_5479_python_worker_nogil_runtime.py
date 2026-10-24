"""#5479 — the Chat Python Worker's runtime contract.

Two facts from #5479 are pinned here.

**The NoGilError is a platform race, not an application defect.** The
``padiem-chat`` Workers tail of 2026-10-19/20 recorded eleven
``NoGilError: Attempted to use PyProxy when Python GIL not held`` exceptions.
Every one of them was raised inside the Cloudflare runtime while it
initialized the Python instance (``preparePython`` -> ``initPyInstance`` ->
``Proxy``), so it happened *before* any application code ran, and every one of
them landed on the repeated ``POST /api/claw/connector/mesh-reads/poll``
request, the traffic that keeps arriving on a cold isolate. That is the
upstream race ``cloudflare/workerd#6624``.

**The published fix for that race is the 3.14 runtime, which needs its own
KDF.** Cloudflare shipped the fix as a Python Workers runtime update (Python
3.14 with the memory-leak fixes) and asked affected Workers to move their
compatibility date to ``2026-09-08`` or later. The Pyodide 3.14 snapshot ships
no ``_hashlib``, and CPython 3.14 removed the pure-Python PBKDF2 fallback, so
that runtime has no ``hashlib.pbkdf2_hmac``. This Worker's stored credential
format is PBKDF2-HMAC-SHA512, and Workers WebCrypto refuses that cost above
100,000 iterations, so the runtime is only usable with a KDF the bundle
itself carries: the ``cryptography`` package's OpenSSL PBKDF2HMAC.

So the contract is:

1. the Chat Worker's runtime and its declared dependencies together provide a
   KDF that can serve the stored 220,000-iteration cost — the C path on 3.13,
   the bundled ``cryptography`` package on 3.14,
2. the real Workerd/Pyodide CI lane boots the *deployed* compatibility date and
   proves the booted Python version, the stored-cost round trip and which
   provider served it, and
3. the production deploy config carries that date into the released Worker.

A runtime bump that drops the KDF, or a dependency change that drops the
bundle, therefore fails in CI before any release.
"""
from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_ROOT = Path(__file__).resolve().parents[1]
CHAT_MANIFEST = CHAT_ROOT / "wrangler.toml"

#: First compatibility date that implies the ``python_workers_314`` flag
#: (Pyodide 314.0.6 / CPython 3.14.2). That snapshot has no ``_hashlib``, so
#: ``hashlib.pbkdf2_hmac`` does not exist there and this Worker's password
#: hashing cannot run.
PYTHON_314_COMPATIBILITY_DATE = "2026-09-08"

#: The compatibility date the Chat Worker deploys: Pyodide 3.14, the
#: published ``NoGilError`` fix, whose password KDF is the bundled
#: ``cryptography`` package rather than ``hashlib.pbkdf2_hmac``.
DEPLOYED_COMPATIBILITY_DATE = PYTHON_314_COMPATIBILITY_DATE

#: The real Workerd/Pyodide probe scripts. Each one used to hardcode a
#: compatibility date, which let the CI lane prove a runtime that Production
#: no longer ran.
PROBE_SCRIPTS = (
    ".github/scripts/b62_worker_probe_shared_runtime.sh",
    ".github/scripts/b62_worker_probe_timeout.sh",
    ".github/scripts/b62_worker_probe_web_transport.sh",
    ".github/scripts/b62_worker_probe_p01_binding.sh",
    ".github/scripts/b62_worker_probe_r2_read.sh",
)


def _manifest() -> dict:
    return tomllib.loads(CHAT_MANIFEST.read_text(encoding="utf-8"))


def _load_deploy_config_module():
    script = REPO_ROOT / ".github/scripts/b62_cloudflare_production_deploy_config.py"
    spec = importlib.util.spec_from_file_location(
        "b62_cloudflare_production_deploy_config", script
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_worker_password_hash_uses_the_runtime_pbkdf2():
    """The constraint above is derived from the source, not from a guess."""
    source = (CHAT_ROOT / "app/password_auth.py").read_text(encoding="utf-8")
    assert "hashlib.pbkdf2_hmac" in source
    assert "PBKDF2_ALGORITHM" in source
    kdf_source = (CHAT_ROOT / "app/password_kdf.py").read_text(encoding="utf-8")
    assert "PBKDF2HMAC" in kdf_source


def _declared_dependencies() -> list[str]:
    data = tomllib.loads((CHAT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def _runtime_provides_password_kdf(compatibility_date: str, *, bundled: bool) -> bool:
    """Can this runtime + bundle serve the stored 220,000-iteration cost?

    Below ``PYTHON_314_COMPATIBILITY_DATE`` the snapshot ships ``_hashlib``
    and CPython provides ``hashlib.pbkdf2_hmac``. From that date on it does
    not, so the Worker bundle itself must carry the ``cryptography`` package.
    """
    if compatibility_date < PYTHON_314_COMPATIBILITY_DATE:
        return True
    return bundled


def test_the_chat_worker_stays_on_a_runtime_with_the_password_kdf():
    """The deployed date and the declared bundle must together serve 220k."""
    manifest = _manifest()
    compatibility_date = manifest["compatibility_date"]
    assert isinstance(compatibility_date, str) and compatibility_date
    assert _runtime_provides_password_kdf(
        compatibility_date, bundled="cryptography==47.0.0" in _declared_dependencies()
    ), (
        "the Chat Worker hashes passwords with PBKDF2-HMAC-SHA512 at 220,000 "
        f"iterations from {compatibility_date}: the Pyodide 3.14 snapshot has "
        "no hashlib.pbkdf2_hmac and Workers WebCrypto refuses that cost, so "
        "the bundle must declare cryptography==47.0.0"
    )
    assert compatibility_date == DEPLOYED_COMPATIBILITY_DATE
    assert "python_workers" in manifest["compatibility_flags"]


def test_the_blocked_compatibility_dates_are_rejected():
    """Differential proof: the guard fails for the cases it has to fail for."""
    # The previous 3.13 date needs no bundle; every 3.14 date does.
    assert _runtime_provides_password_kdf("2026-08-25", bundled=False)
    assert not _runtime_provides_password_kdf(
        PYTHON_314_COMPATIBILITY_DATE, bundled=False
    )
    assert not _runtime_provides_password_kdf("2026-10-13", bundled=False)
    assert not _runtime_provides_password_kdf("2027-01-01", bundled=False)
    # The declared bundle is what makes those dates usable.
    assert _runtime_provides_password_kdf(
        PYTHON_314_COMPATIBILITY_DATE, bundled=True
    )
    assert _runtime_provides_password_kdf(
        DEPLOYED_COMPATIBILITY_DATE, bundled=True
    )


def test_the_production_deploy_config_carries_the_deployed_compatibility_date(
    tmp_path,
):
    """The released Worker must run the runtime the manifest declares.

    The production deploy config is generated from the repository manifest, so
    the compatibility date has to survive that generation. A manifest change
    that never reached the deployed config would leave Production on another
    runtime while the source claimed the fix.
    """
    module = _load_deploy_config_module()
    manifest = _manifest()
    repo_config = tmp_path / "wrangler.toml"
    repo_config.write_text(
        'name = "padiem-chat"\n'
        'main = "worker.py"\n'
        f'compatibility_date = "{manifest["compatibility_date"]}"\n'
        'compatibility_flags = ["python_workers"]\n'
        'base_dir = ".b66-worker-src"\n'
        "\n"
        "[assets]\n"
        'directory = "static"\n'
        'binding = "ASSETS"\n',
        encoding="utf-8",
    )
    live = module.parse_live_bindings({
        "success": True,
        "result": {
            "bindings": [
                {"type": "assets", "name": "ASSETS"},
                {
                    "type": "service",
                    "name": "B14_SERVICE",
                    "service": "ai-revenue-korean-ai-platform",
                },
                {
                    "type": "service",
                    "name": "IDENTITY_AUTHORITY_SERVICE",
                    "service": "padiem-control-plane-identity",
                },
                {
                    "type": "d1",
                    "name": "PADIEM_CHAT_DB",
                    "id": "702bb62b-36f5-41a0-973f-c4f663ee01e6",
                },
                {"type": "secret_text", "name": "PADIEM_CHAT_QUOTA_SALT"},
                {
                    "type": "plain_text",
                    "name": "PADIEM_CHAT_RUNTIME_MODE",
                    "text": "b14",
                },
                {
                    "type": "plain_text",
                    "name": "PADIEM_CHAT_LIVE_ENABLED",
                    "text": "true",
                },
                {
                    "type": "plain_text",
                    "name": "PADIEM_CHAT_TIMEOUT_SECONDS",
                    "text": "600",
                },
                {
                    "type": "plain_text",
                    "name": "PADIEM_CHAT_PUBLIC_BASE_URL",
                    "text": "https://chat.padiem.net",
                },
            ]
        },
    })
    generated = module.build_production_config(
        live, repo_config, "https://chat.padiem.net"
    )
    parsed = tomllib.loads(generated)
    assert parsed["compatibility_date"] == manifest["compatibility_date"]
    assert parsed["compatibility_date"] == PYTHON_314_COMPATIBILITY_DATE
    assert "python_workers" in parsed["compatibility_flags"]


def test_the_real_worker_probe_boots_the_deployed_compatibility_date():
    """The CI Pyodide lane must prove the runtime Production actually runs."""
    for relative in PROBE_SCRIPTS:
        script = REPO_ROOT / relative
        text = script.read_text(encoding="utf-8")
        assert 'compatibility_date = "20' not in text, (
            f"{relative} hardcodes a compatibility date; the real Workerd probe "
            "must read the deployed manifest instead of proving another runtime"
        )
        assert "wrangler.toml" in text, (
            f"{relative} must derive the compatibility date from the Chat manifest"
        )


def test_the_real_worker_probe_asserts_the_runtime_and_the_password_kdf():
    """A green probe must state which runtime it booted and that it can hash."""
    shared = (REPO_ROOT / ".github/scripts/b62_worker_probe_shared_runtime.sh").read_text(
        encoding="utf-8"
    )
    assert "B62_WORKER_PYTHON_RUNTIME" in shared
    assert "get_python_version" in shared
    # #5736: the gate asserts the invariant the auth routes actually serve. The
    # sync C path (kdf=) is printed, not gated, because a 3.14 snapshot has no
    # hashlib.pbkdf2_hmac by design — and "stored=ok" is the check that was
    # missing when the 3.14 deploy was rolled back: it exercises the 220,000
    # iterations the stored credentials carry.
    # #5479: "stored=ok" alone is not enough — the lane must also report WHICH
    # provider served it, because the local Workerd accepts 220k through
    # WebCrypto while the Production edge refuses it.
    assert "B62_WORKER_PASSWORD_KDF_C_PATH" in shared
    assert '*"kdfasync=ok"*' in shared
    assert '*"stored=ok"*' in shared
    assert '*"digest=ok"*' in shared
    assert "B62_WORKER_PASSWORD_AUTH=FAIL" in shared
    assert "B62_WORKER_KDF220K_PROVIDER" in shared
    probe = (CHAT_ROOT / "worker_runtime_combined_probe.py").read_text(encoding="utf-8")
    assert "sys.version_info" in probe
    assert "_password_kdf_state" in probe
    assert "hash_password" in probe and "verify_password" in probe
