"""#4643: the Gemini Live real-time transcription engine for Chat/Claw.

`voice_gemini_live_4643.cjs` is the behavioural spec of
`static/voice-live-session.js`: the Live session, the real-time interim and
final split, the turn commit, the session rotation with the audio carry-over,
the provider fallback and the teardown that leaves nothing running. A bare
`.cjs` in this directory is not collected by pytest, so this file runs it --
the same host pattern `test_voice_live_transcript_turn_4643.py` uses.

The engine is a port of global-classroom's `hooks/useGeminiLive.ts`; the
authority it reads is the already-ported shared turn module. No test here
performs a provider call: the Live socket, the microphone and the token route
are fakes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

# #8060: shipped reads live in _support; the source and behavior checks stay.
from _support import voice_gemini_live_source as sheets

NODE_SPEC = Path(__file__).with_name("voice_gemini_live_4643.cjs")


def _run_node_spec() -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node, "node runtime is required for the Gemini Live engine spec"
    return subprocess.run(
        [node, str(NODE_SPEC)],
        capture_output=True,
        text=True, encoding="utf-8",
        timeout=180,
        cwd=sheets.chat_root(),
    )


def test_gemini_live_engine_gates_pass() -> None:
    result = _run_node_spec()
    tail = (result.stdout.strip().splitlines() or [""])[-1]
    assert result.returncode == 0, f"node spec failed: {result.stdout[-3000:]} {result.stderr[-2000:]}"
    passed = re.search(r"^# pass (\d+)$", result.stdout, re.MULTILINE)
    failed = re.search(r"^# fail (\d+)$", result.stdout, re.MULTILINE)
    assert passed and failed, f"no summary in node output: {tail}"
    assert int(failed.group(1)) == 0
    # A lost case must show up as a smaller count, not a green run.
    assert int(passed.group(1)) == 11, result.stdout[-1500:]


def test_engine_is_the_global_classroom_port_with_its_provenance() -> None:
    source = sheets.sheet("voice-live-session.js")
    assert "GLOBAL_CLASSROOM_DIRECT_PORT" in source
    assert "ffa27e6a93605614031fed314ef33571c85b8f18" in source
    # The original's own names, so a drift is visible in review. The one whose
    # name carried a provider is described by role instead; the repository,
    # commit and upstream path above still identify it.
    for name in ("liveTranscriptTurn.ts", "audioUtils.ts"):
        assert name in source, name
    assert "the upstream live-session hook" in source
    assert "float32ToInt16" in source
    assert "arrayBufferToBase64" in source
    assert "audio/pcm;rate=16000" in source


def test_engine_never_holds_a_long_lived_provider_key() -> None:
    source = sheets.sheet("voice-live-session.js")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"//[^\n]*", "", code)
    # The only credential the browser may hold is the short-lived,
    # model-locked token the same-origin route mints.
    assert "PADIEM_GEMINI_API_KEY" not in code
    assert "PADIEM_GROQ_API_KEY" not in code
    assert "x-goog-api-key" not in code
    assert "ai_client" not in code
    # #6828 voice-relay: the browser holds no credential at all; the relay
    # presents the ephemeral token server-side. No token or key in the URL.
    assert "access_token" not in code
    assert "?key=" not in source


def test_engine_reads_the_window_from_the_server_contract_but_never_the_model() -> None:
    source = sheets.sheet("voice-live-session.js")
    # #6828 voice-relay: the activity-detection window, rotation window and
    # transcription mode come from the server's public session block; the model
    # is injected by the COM2 relay and must NOT be read or sent by the browser.
    for field in ("cfg.vad_silence_ms", "cfg.response_modalities",
                  "cfg.input_audio_transcription_mode", "liveSession.rotate_after_ms"):
        assert field in source, field
    assert "cfg.model" not in source, "the browser must not read the model"
    assert "/api/voice/relay" in source, "the browser only knows the same-origin relay"
    # Model selection belongs solely to the server session response.
    assert 'LIVE_TRANSCRIBE_MODEL' not in source
    literals = re.findall(r'"gemini-[0-9a-z.\-]+"', source)
    assert literals == [], f"the engine must not pin a model id: {literals}"


def test_wiring_uses_the_live_engine_first_and_keeps_the_recorded_fallback() -> None:
    source = sheets.sheet("voice-stt-wiring.js")
    assert "PadiemVoiceLiveSession" in source
    assert "fallbackFactory: recordedFactory" in source
    # The recorded-chunk path stays reachable as the next provider.
    assert "createRecognizerFactory" in source
    # The token route is same-origin and product-specific.
    assert 'LIVE_TOKEN_PATH = "/api/voice/live-token"' in source
    assert 'CLAW_LIVE_TOKEN_PATH = "/api/claw/voice/live-token"' in source


def test_page_loads_the_engine_before_the_wiring_that_uses_it() -> None:
    html = sheets.sheet("index.html")
    assert html.count('<script src="./voice-live-session.js"></script>') == 1
    order = [
        html.index("voice-live-transcript-turn.js"),
        html.index("voice-stt-input.js"),
        html.index("voice-composer.js"),
        html.index("voice-live-session.js"),
        html.index("voice-stt-wiring.js"),
    ]
    assert order == sorted(order), "the engine must load before the wiring"


def test_m1_live_transcript_lands_in_the_input_box() -> None:
    adapter = sheets.sheet("voice-stt-input.js")
    composer = sheets.sheet("voice-composer.js")
    # The shared adapter writes the live words into the input itself.
    assert "writeLiveInput" in adapter
    assert "writeFinalInput" in adapter
    assert "writesLiveInput" in adapter
    # The composer must not repeat the same words in its preview line.
    assert "writesLiveInput" in composer


def test_no_voice_path_sends_a_chat_message() -> None:
    for name in ("voice-live-session.js", "voice-stt-wiring.js", "voice-stt-input.js"):
        source = sheets.sheet(name)
        code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        code = re.sub(r"//[^\n]*", "", code)
        for forbidden in ("composerForm.requestSubmit", "form.submit", "requestSubmit"):
            assert forbidden not in code, f"{name} must never send a message"


def test_the_engine_opens_nothing_before_the_microphone_runs() -> None:
    source = sheets.sheet("voice-live-session.js")
    # The factory is the microphone seam. The token request and the socket are
    # created inside it, never at module load.
    assert "fetchLiveToken()" in source
    load_index = source.index("function createRecognizerFactory")
    assert "fetchLiveToken()" in source[load_index:]
    # No module-level connection: the module body only defines functions.
    module_tail = source[source.index("function createRecognizerFactory"):]
    assert "new AudioContext" not in module_tail.split("return function liveRecognizerFactory")[0]
