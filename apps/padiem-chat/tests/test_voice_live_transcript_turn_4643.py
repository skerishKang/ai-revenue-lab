"""Hosts the ported Global Classroom #87 gates for the shared voice authority.

`voice_live_transcript_turn_4643.cjs` is the behavioural port of
global-classroom tests/unit/interviewTranscriptionTurn87.test.ts and the pure
describe blocks of interviewSessionRotation87.test.ts. A bare `.cjs` in this
directory is not collected by pytest, so this file runs it — the same host
pattern tests/test_voice_composer_4643.py uses for its Node harness.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
AUTHORITY_JS = STATIC / "voice-live-transcript-turn.js"
ADAPTER_JS = STATIC / "voice-stt-input.js"
INDEX_HTML = STATIC / "index.html"
NODE_SPEC = Path(__file__).with_name("voice_live_transcript_turn_4643.cjs")

# Values recorded in global-classroom @ ffa27e6a utils/liveTranscriptTurn.ts.
# A drift here is the two repos diverging, which is the failure #87 was about.
GC_CONTRACT = {
    "LIVE_TRANSCRIBE_MODEL": '"gemini-3.5-transcribe-live"',
    "LIVE_VAD_SILENCE_MS": "1300",
    "LIVE_SESSION_ROTATE_MS": "9 * 60 * 1000 + 20 * 1000",
    "LIVE_AUDIO_HANDOFF_FRAMES": "40",
    "LIVE_TAIL_FLUSH_DRAIN_MS": "1200",
    "GROQ_MIN_CHUNK_MS": "4000",
    "GROQ_SILENCE_CUT_MS": "700",
    "GROQ_MAX_CHUNK_MS": "20000",
    "TRANSCRIPT_TURN_STALL_MS": "2500",
}


def _run_node_spec() -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node, "node runtime is required for the shared voice authority spec"
    return subprocess.run(
        [node, str(NODE_SPEC)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )


def test_ported_global_classroom_gates_pass() -> None:
    result = _run_node_spec()
    tail = (result.stdout.strip().splitlines() or [""])[-1]
    assert result.returncode == 0, f"node spec failed: {result.stdout[-3000:]} {result.stderr[-2000:]}"
    passed = re.search(r"^# pass (\d+)$", result.stdout, re.MULTILINE)
    failed = re.search(r"^# fail (\d+)$", result.stdout, re.MULTILINE)
    assert passed and failed, f"no TAP summary in node output: {tail}"
    # 31 = every pure case of the two Global Classroom files plus the PADIEM-side
    # contract cases. A lost case must show up as a smaller count, not a green run.
    assert int(failed.group(1)) == 0
    assert int(passed.group(1)) == 31, result.stdout[-1500:]


def test_authority_ships_the_global_classroom_values_verbatim() -> None:
    source = AUTHORITY_JS.read_text(encoding="utf-8")
    for name, value in GC_CONTRACT.items():
        pattern = rf"const {name} = {re.escape(value)};"
        assert re.search(pattern, source), f"authority drifted from global-classroom: {name}"
    assert "GLOBAL_CLASSROOM_DIRECT_PORT" in source
    assert "ffa27e6a93605614031fed314ef33571c85b8f18" in source


def test_authority_exports_the_full_shared_surface() -> None:
    source = AUTHORITY_JS.read_text(encoding="utf-8")
    for name in [
        "mergeLiveTranscriptChunk", "createAudioHandoffBuffer", "flushLiveTranscriptTail",
        "createTranscriptTurnBuffer", "shouldCutGroqChunk", "shouldFlushStalledTurn",
        "startSpeechSilenceProbe", "resolveRecognitionLanguage",
    ]:
        assert f"{name}: {name}" in source, f"authority does not export {name}"


def test_page_loads_the_authority_before_any_consumer_of_it() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert html.count('<script src="./voice-live-transcript-turn.js"></script>') == 1
    order = [
        html.index("voice-live-transcript-turn.js"),
        html.index("voice-stt-input.js"),
        html.index("voice-composer.js"),
        html.index("voice-stt-wiring.js"),
        html.index('<script src="./app.js">'),
    ]
    assert order == sorted(order), "the authority must load first and app.js last"


def test_adapter_has_no_local_copy_of_the_turn_logic() -> None:
    source = ADAPTER_JS.read_text(encoding="utf-8")
    # The adapter delegates; a re-landed numeric copy is the drift the gate in the
    # Node spec counts, and here it is named exactly.
    for name in GC_CONTRACT:
        if name == "LIVE_TRANSCRIBE_MODEL":
            continue
        assert not re.search(rf"const {name} = \d", source), f"voice-stt-input.js restates {name}"
    assert "turnAuthority.LIVE_VAD_SILENCE_MS" in source
    assert "voice_live_transcript_turn_authority_missing" in source, (
        "the adapter must fail closed when the authority did not load, not fall back to a copy"
    )
