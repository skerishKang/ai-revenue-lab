"""Static contract checks on the Workers adapter (``worker.py``).

``worker.py`` imports the Cloudflare ``workers`` runtime, which cannot be
imported on CPython, so its behaviour is pinned at the source level. All the
*logic* lives in ``voice_stt_contract`` and is covered by the other suites; this
file proves the adapter stays a thin, safe glue layer.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import voice_stt_contract as c

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER = APP_ROOT / "worker.py"
BUILD = APP_ROOT / "scripts" / "build_worker_dependencies.py"


def _source() -> str:
    return WORKER.read_text(encoding="utf-8")


def _imports() -> set[str]:
    tree = ast.parse(_source(), filename=str(WORKER))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_worker_uses_the_cloudflare_runtime():
    assert "from workers import Response, WorkerEntrypoint, fetch" in _source()


def test_worker_imports_only_stdlib_and_the_shared_contract():
    # ``js`` is the Pyodide runtime module used behind a guarded ``import js``
    # for the abort signal; it is runtime-provided, not a vendored dependency.
    allowed = {
        "workers",
        "voice_stt_contract",
        "json",
        "uuid",
        "urllib",
        "__future__",
        "js",
    }
    assert _imports() - allowed == set()


def test_worker_exposes_the_three_shared_routes():
    source = _source()
    assert 'TRANSCRIBE_PATH = "/internal/v1/voice/transcribe"' in source
    assert 'LIVE_TOKEN_PATH = "/internal/v1/voice/live-token"' in source
    assert 'CAPABILITIES_PATH = "/internal/v1/voice/capabilities"' in source


def test_worker_resolves_secrets_by_contract_binding_name():
    source = _source()
    assert "contract.GROQ_API_KEY_BINDING" in source
    assert "contract.GEMINI_API_KEY_BINDING" in source


def test_worker_fails_closed_when_a_key_is_missing():
    source = _source()
    assert 'return _error("stt_key_missing")' in source
    assert 'return _error("live_token_unavailable")' in source


def test_worker_never_logs_or_prints_anything():
    source = _source()
    assert "print(" not in source
    assert "console.log" not in source
    assert "import logging" not in source
    assert "logging." not in source


def test_worker_never_hardcodes_a_provider_url_or_key():
    source = _source()
    assert "api.groq.com" not in source
    assert "generativelanguage.googleapis.com" not in source
    # No long literal that could be a pasted key.
    assert not re.search(r"['\"][A-Za-z0-9_\-]{40,}['\"]", source)


def test_worker_delegates_validation_and_parsing_to_the_contract():
    source = _source()
    assert "contract.validate_transcribe_request" in source
    assert "contract.build_groq_multipart_body" in source
    assert "contract.parse_groq_transcription_response" in source
    assert "contract.build_live_token_request_body" in source
    assert "contract.extract_live_token" in source
    # No re-implemented multipart encoding in the adapter.
    assert "multipart/form-data" not in source


def test_worker_uses_the_bounded_error_envelope():
    assert '"ok": False' in _source()
    assert '"error": {"code": code}' in _source()


def test_build_script_allowlist_matches_worker_imports():
    build = BUILD.read_text(encoding="utf-8")
    assert 'ALLOWED_THIRD_PARTY = frozenset({"workers", "voice_stt_contract", "js"})' in build
    assert 'RUNTIME_FILES = ("worker.py", "voice_stt_contract.py")' in build
    # The vendored runtime must not pull any third-party dependency.
    assert c.CONTRACT_VERSION.startswith("padiem.voice.stt.")


def test_worker_reads_the_enabled_flag_before_any_secret():
    """P0-2: the gate must run before any secret read or provider path."""
    import ast

    tree = ast.parse(_source(), filename=str(WORKER))
    fetch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "fetch"
    )
    called = []
    for node in ast.walk(fetch):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        called.append(name)
    assert "_require_enabled" in called
    gate = called.index("_require_enabled")
    # Nothing that can read a Secret or reach a provider may precede the gate.
    for forbidden in ("_handle_transcribe", "_handle_live_token", "_handle_capabilities"):
        assert forbidden not in called[:gate], called[:gate]


def test_worker_uses_bounded_body_reading():
    """P0-3: no whole-body materialisation before the size check."""
    source = _source()
    assert "await request.text()" not in source
    assert "contract.read_bounded_body" in source
    assert "contract.parse_declared_content_length" in source
    assert "body.getReader()" in source


def test_worker_declares_timeout_budgets_for_both_upstreams():
    source = _source()
    assert "contract.GROQ_REQUEST_TIMEOUT_MS" in source
    assert "contract.LIVE_TOKEN_REQUEST_TIMEOUT_MS" in source


def test_contract_holds_no_secrets_store_resource_locator():
    """P0-4: the store id must not be duplicated in Python or in the tests."""
    marker = "f0b09ca" + "04a7b4324" + "8154c7737" + "045a5616"
    contract_source = (APP_ROOT / "voice_stt_contract.py").read_text(encoding="utf-8")
    assert marker not in contract_source
    for path in sorted((APP_ROOT / "tests").glob("*.py")):
        if path.name == Path(__file__).name:
            continue  # this assertion names the marker by construction
        assert marker not in path.read_text(encoding="utf-8"), path.name
    for path in sorted((APP_ROOT / "worker.py").rglob("*.py")):
        assert marker not in path.read_text(encoding="utf-8"), path
