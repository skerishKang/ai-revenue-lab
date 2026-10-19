"""Explicit Atria streaming UI opt-in guards. Source-only, no requests."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]

def test_preview_is_owner_opt_in_and_off_by_default():
    tpl=(ROOT/"templates/workspace.html").read_text(encoding="utf-8")
    js=(ROOT/"static/start.js").read_text(encoding="utf-8")
    assert 'id="start_atria_stream_preview"' in tpl
    assert 'id="start_atria_stream_preview" checked' not in tpl
    assert 'DOM.atriaStreamPreview = $("start_atria_stream_preview");' in js
    assert 'state.activeRouteMode !== "manual"' in js
    assert 'state.activeModel !== "atria/Atria-Dawn-Preview"' in js
    assert "state.externalFallback))" in js
    assert 'endpoint += "/stream-preview"' in js
    assert "payload.stream = true" in js
    assert "max_attempts: 1" in js
    assert "max_retries: 0" in js
    assert "allow_external_fallback: false" in js
    assert '"Content-Type": "application/json"' in js
    assert "if (DOM.externalFallback) {" in js
    assert 'DOM.externalFallback.addEventListener("change"' in js
    assert 'var endpoint = "/api/pilot/v1/chat/completions"' in js
    assert 'await readAtriaPreview(resp, model)' in js

def test_atria_sse_parser_accepts_completed_exact_route_only():
    result=subprocess.run(
        ["node",str(ROOT/"tests/atria-stream-optin.test.cjs")],
        text=True,capture_output=True,timeout=20,encoding="utf-8")
    assert result.returncode==0, result.stderr
    assert "ATRIA_STREAM_UI_PARSER_TESTS=8 PASS" in result.stdout
