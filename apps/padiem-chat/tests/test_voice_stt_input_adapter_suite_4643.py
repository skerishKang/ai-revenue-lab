"""#4643: the shared voice input adapter contract runs in the Chat pytest lane.

``test_voice_stt_input_adapter_4643.cjs`` is the behavioural spec of
``static/voice-stt-input.js``: the turn buffer, the utterance de-duplication,
the live draft in the composer input and the boundaries that keep a late
event out of a live input. A bare ``.cjs`` in this directory is not collected
by pytest, so this file runs it -- the same host pattern
``test_voice_gemini_live_4643.py`` uses.

The adapter is the one place that decides what reaches the composer input, so
its contract must not be able to drift unnoticed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_JS = ROOT / "static" / "voice-stt-input.js"
NODE_SPEC = Path(__file__).with_name("test_voice_stt_input_adapter_4643.cjs")


def _run_node_spec() -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node, "node runtime is required for the voice input adapter spec"
    return subprocess.run(
        [node, "--test", "--test-reporter=tap", str(NODE_SPEC)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
    )


def test_voice_input_adapter_gates_pass() -> None:
    result = _run_node_spec()
    tail = (result.stdout.strip().splitlines() or [""])[-1]
    assert result.returncode == 0, f"node spec failed: {result.stdout[-3000:]} {result.stderr[-2000:]}"
    passed = re.search(r"^# pass (\d+)$", result.stdout, re.MULTILINE)
    failed = re.search(r"^# fail (\d+)$", result.stdout, re.MULTILINE)
    assert passed and failed, f"no summary in node output: {tail}"
    assert int(failed.group(1)) == 0
    # A lost case must show up as a smaller count, not a green run.
    assert int(passed.group(1)) >= 30, result.stdout[-1500:]


def test_the_adapter_owns_the_live_draft_contract() -> None:
    source = ADAPTER_JS.read_text(encoding="utf-8")
    # The live draft is written into the composer input, so the composer must
    # not repeat the same words in its preview line.
    assert "writeLiveInput" in source
    assert "rollbackLiveInput" in source
    assert "writesLiveInput" in source
    # The adapter still owns no transport of its own.
    for primitive in ("fetch(", "XMLHttpRequest", "WebSocket", "SpeechRecognition"):
        assert primitive not in source, "transport primitive in the adapter: " + primitive
