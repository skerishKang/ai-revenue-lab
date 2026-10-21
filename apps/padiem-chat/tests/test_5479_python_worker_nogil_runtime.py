"""#5479 — the Chat Python Worker must run the Python 3.14 Pyodide snapshot.

Production evidence (the ``padiem-chat`` Workers tail of 2026-10-19/20)
recorded eleven ``NoGilError: Attempted to use PyProxy when Python GIL not
held`` exceptions. Every one of them was raised inside the Cloudflare runtime
while it initialized the Python instance (``preparePython`` -> ``initPyInstance``
-> ``Proxy``), so it happened *before* any application code ran, and every one
of them landed on the repeated ``POST /api/claw/connector/mesh-reads/poll``
request, which is the traffic that keeps landing on a cold isolate.

That signature is the known upstream platform race
(``cloudflare/workerd#6624``). Cloudflare published the fix as a Python Workers
runtime update — Python 3.14 with the memory-leak fixes — and asked every
affected Worker to move its compatibility date to ``2026-09-08`` or later. The
runtime snapshot is selected by the compatibility date: ``2026-09-08`` is the
first date that implies the ``python_workers_314`` flag (Pyodide 314.0.6 /
CPython 3.14.2). The previous date, ``2026-08-25``, still selected the
Pyodide 3.13 snapshot, which is the runtime that raises the error.

Two things are pinned here:

1. the Chat Worker manifest stays on a compatibility date that selects the
   published runtime, and
2. the real Workerd/Pyodide CI lane boots *that same* compatibility date, so a
   green CI lane proves the runtime Production actually runs instead of a
   runtime that only exists inside the probe script.
"""
from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_ROOT = Path(__file__).resolve().parents[1]
CHAT_MANIFEST = CHAT_ROOT / "wrangler.toml"

#: First compatibility date that implies ``python_workers_314``
#: (Pyodide 314.0.6 / CPython 3.14.2), the runtime Cloudflare published as the
#: fix for the ``NoGilError`` initialization race (cloudflare/workerd#6624).
PYTHON_314_COMPATIBILITY_DATE = "2026-09-08"

#: The compatibility date this Worker used before #5479. It selects the
#: Pyodide 3.13 snapshot, which is the runtime that raises ``NoGilError``.
VULNERABLE_COMPATIBILITY_DATE = "2026-08-25"

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


def _python_runtime_is_current(compatibility_date: str) -> bool:
    """True when the compatibility date selects the published Python runtime."""
    return compatibility_date >= PYTHON_314_COMPATIBILITY_DATE


def _load_deploy_config_module():
    script = REPO_ROOT / ".github/scripts/b62_cloudflare_production_deploy_config.py"
    spec = importlib.util.spec_from_file_location(
        "b62_cloudflare_production_deploy_config", script
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_chat_worker_runs_the_published_python_runtime():
    """The manifest must select Pyodide 3.14, not the 3.13 snapshot."""
    manifest = _manifest()
    compatibility_date = manifest["compatibility_date"]
    assert isinstance(compatibility_date, str) and compatibility_date
    assert _python_runtime_is_current(compatibility_date), (
        "the Chat Python Worker must use a compatibility date of "
        f"{PYTHON_314_COMPATIBILITY_DATE} or later; found {compatibility_date}"
    )
    assert "python_workers" in manifest["compatibility_flags"]


def test_the_pre_fix_compatibility_date_is_rejected():
    """Differential proof: the guard fails for the runtime that raised the error.

    Without this, the guard above could pass for any date and the regression
    would not be load-bearing.
    """
    assert not _python_runtime_is_current(VULNERABLE_COMPATIBILITY_DATE)
    assert not _python_runtime_is_current("2026-09-07")
    assert _python_runtime_is_current(PYTHON_314_COMPATIBILITY_DATE)
    assert _python_runtime_is_current("2026-10-13")


def test_the_production_deploy_config_carries_the_python_runtime_compatibility_date(
    tmp_path,
):
    """The released Worker must run the runtime the manifest declares.

    The production deploy config is generated from the repository manifest, so
    the compatibility date has to survive that generation. A manifest change
    that never reached the deployed config would leave Production on the old
    snapshot while the source claimed the fix.
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


def test_the_real_worker_probe_asserts_the_running_python_runtime():
    """A green probe must state which Python runtime it actually booted."""
    text = (REPO_ROOT / ".github/scripts/b62_worker_probe_shared_runtime.sh").read_text(
        encoding="utf-8"
    )
    assert "B62_WORKER_PYTHON_RUNTIME" in text
    assert "3.14" in text
    probe = (CHAT_ROOT / "worker_runtime_combined_probe.py").read_text(encoding="utf-8")
    assert "sys.version_info" in probe
