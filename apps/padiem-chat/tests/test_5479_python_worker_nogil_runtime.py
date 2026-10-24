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

**The published fix for that race is the runtime this Worker now takes.**
Cloudflare shipped the fix as a Python Workers runtime update (Python
3.14 with the memory-leak fixes) and asked affected Workers to move their
compatibility date to ``2026-09-08`` or later. The Pyodide 3.14 snapshot ships
no ``_hashlib``, and CPython 3.14 removed the pure-Python PBKDF2 fallback, so
that runtime has no ``hashlib.pbkdf2_hmac``. #5732 removed that blocker: the
password KDF now dispatches to Workers' native WebCrypto bridge on such
runtimes and produces byte-identical ``pbkdf2_sha512$...`` credentials, so the
stored credential format is unchanged.

So the contract is:

1. the Chat Worker deploys the 3.14 runtime with the runtime-independent
   password KDF that #5732 shipped,
2. the real Workerd/Pyodide CI lane boots the *deployed* compatibility date and
   proves the booted Python version plus ``kdf=ok kdfasync=ok tz=ok``, and
3. the production deploy config carries that date into the released Worker.

A future runtime change that breaks (1) or (2) therefore fails in CI before
any release, and the production deploy cannot silently ship a runtime that
cannot hash a password.
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
#: ``hashlib.pbkdf2_hmac`` does not exist there and the C hashing path cannot
#: run. Since #5732 the password KDF dispatches to the Workers WebCrypto
#: bridge on such runtimes, so this date is now the deployed one.
PYTHON_314_COMPATIBILITY_DATE = "2026-09-08"

#: The compatibility date the Chat Worker deploys (Pyodide 314.0.6 /
#: CPython 3.14.2, the NoGilError fix runtime).
DEPLOYED_COMPATIBILITY_DATE = "2026-09-08"

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


def test_the_chat_worker_deploys_the_kdf_independent_314_runtime():
    """The Worker moves to the 3.14 runtime with the runtime-independent KDF.

    #5732 replaced the C-only hashing path with a runtime-dispatching KDF
    (C ``hashlib`` where available, Workers WebCrypto on the 3.14 snapshot),
    so the NoGilError fix runtime is no longer blocked. The manifest must
    carry that date and the base ``python_workers`` flag.
    """
    manifest = _manifest()
    compatibility_date = manifest["compatibility_date"]
    assert isinstance(compatibility_date, str) and compatibility_date
    assert compatibility_date == DEPLOYED_COMPATIBILITY_DATE
    assert compatibility_date >= PYTHON_314_COMPATIBILITY_DATE
    assert "python_workers" in manifest["compatibility_flags"]
    # The KDF module that makes this runtime deployable ships with the move.
    kdf_source = (CHAT_ROOT / "app/password_kdf.py").read_text(encoding="utf-8")
    assert "pbkdf2_sha512_webcrypto" in kdf_source
    assert "FORCE_NON_C_PATH" in kdf_source


def test_the_date_contract_is_explicit():
    """Differential proof: the contract pins exactly the 3.14 boundary."""
    assert DEPLOYED_COMPATIBILITY_DATE == PYTHON_314_COMPATIBILITY_DATE
    assert not DEPLOYED_COMPATIBILITY_DATE < PYTHON_314_COMPATIBILITY_DATE
    assert "2026-08-25" < PYTHON_314_COMPATIBILITY_DATE


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
    assert parsed["compatibility_date"] >= PYTHON_314_COMPATIBILITY_DATE
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
    assert "B62_WORKER_PASSWORD_KDF" in shared
    assert "kdf=ok" in shared
    probe = (CHAT_ROOT / "worker_runtime_combined_probe.py").read_text(encoding="utf-8")
    assert "sys.version_info" in probe
    assert "_password_kdf_state" in probe
    assert "hash_password" in probe and "verify_password" in probe
