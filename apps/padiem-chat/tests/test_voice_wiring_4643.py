"""#7628: the #4643 voice wiring contract as CI-collected pytest checks.

browser_voice_wiring_4643.py proved the shared Chat/Claw microphone wiring at
runtime: it served static/, loaded the real voice scripts in Chromium, mocked
the STT backend at the network layer and asserted the wiring result. The CI
Chat pytest lanes run no browser and no external network, so the same checks
live here as fail-closed static/unit checks over the exact shipped sources
that produced those runtime results. The direct-run browser proof stays in
the tests tree as the manual Chromium harness for local verification.

Check mapping (runtime proof -> this module):
  wiring/composer/adapter globals defined  -> script tags + UMD export lines
  mic_button_present                       -> composer mount target and button id
  factory_registered                       -> wiring registers the recognizer
                                              factory on the composer, health-
                                              gated, default-off
  mic_enabled_when_mock_authenticated      -> composer auth-state listener and
                                              the signed-in availability gate
  stop_final_in_editable_input             -> adapter final writes land in
                                              #messageInput only
  auto_submit_count == 0                   -> no transport and no chat send
                                              route in any voice module
  composer/factory uploads all INIT        -> one fresh MediaRecorder per
                                              chunk cycle, restarted before
                                              the next upload
  factory finals == cuts, no errors        -> one final per assembled chunk
                                              through the same stop pipeline
  permissions_policy_header                -> worker_config serves the header
                                              on every worker response
  no js console errors at load             -> turn authority is loaded before
                                              the adapter that fail-closes on
                                              its absence
"""

from __future__ import annotations

from pathlib import Path

from app.worker_config import (
    BASE_SECURITY_HEADERS,
    PERMISSIONS_POLICY,
    response_headers_for_path,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def _read_static(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_voice_modules_export_the_browser_globals():
    """The runtime proof required window.PadiemVoice* objects after load."""
    wiring = _read_static("voice-stt-wiring.js")
    composer = _read_static("voice-composer.js")
    adapter = _read_static("voice-stt-input.js")
    # The UMD export each runtime evaluate("typeof window.X") relied on.
    assert "root.PadiemVoiceSttWiring = api;" in wiring
    assert "root.PadiemVoiceComposer = api;" in composer
    assert "root.PadiemVoiceSttInput = api;" in adapter
    # The adapter fails closed without the #87 turn authority, and the wiring
    # prefers the realtime live-session factory when it is present.
    assert "root.PadiemVoiceLiveTranscriptTurn = api;" in _read_static(
        "voice-live-transcript-turn.js"
    )
    assert "root.PadiemVoiceLiveSession = api;" in _read_static(
        "voice-live-session.js"
    )


def test_index_loads_voice_scripts_in_dependency_order():
    """Load-time console errors are prevented by the shipped script order."""
    html = _read_static("index.html")
    script_positions = {}
    for name in (
        "voice-live-transcript-turn.js",
        "voice-stt-input.js",
        "voice-composer.js",
        "voice-live-session.js",
        "voice-stt-wiring.js",
    ):
        tag = f'<script src="./{name}"></script>'
        assert tag in html, f"index.html must load {name}"
        script_positions[name] = html.index(tag)
    # The turn authority precedes the adapter that throws without it, and the
    # composer precedes the wiring that installs the recognizer factory.
    order = list(script_positions.values())
    assert order == sorted(order), "voice scripts must load in dependency order"
    # The composer mounts into this form; the adapter writes into this input.
    assert 'id="composerForm"' in html
    assert 'id="messageInput"' in html


def test_composer_mounts_the_mic_button_into_the_composer_form():
    """mic_button_present: the composer creates #voiceMicButton itself."""
    composer = _read_static("voice-composer.js")
    assert 'const MIC_BUTTON_ID = "voiceMicButton";' in composer
    assert "button.id = MIC_BUTTON_ID;" in composer
    # The mount target comes from the shipped page, not a new document.
    assert (
        'const form = doc && typeof doc.getElementById === "function" '
        '? doc.getElementById("composerForm") : null;' in composer
    )
    assert (
        'const input = doc && typeof doc.getElementById === "function" '
        '? doc.getElementById("messageInput") : null;' in composer
    )
    # The composer auto-mounts exactly when the shipped form exists.
    assert 'if (!doc.getElementById("composerForm")) return null;' in composer


def test_wiring_registers_the_recognizer_factory_with_the_composer():
    """factory_registered: statusKey must move off voice-unavailable-wiring."""
    wiring = _read_static("voice-stt-wiring.js")
    composer = _read_static("voice-composer.js")
    # The composer accepts exactly one recognizer factory from the wiring.
    assert (
        'if (!composer || typeof composer.registerRecognizerFactory !== "function") return null;'
        in wiring
    )
    assert "const composer = options.composer || win.PadiemVoiceComposer;" in wiring
    assert (
        "composer.registerRecognizerFactory(available && canCapture ? factory : null);"
        in wiring
    )
    # STT stays default-off until the same-origin /health proves the transport.
    assert "registerFactory(false);" in wiring
    assert (
        "registerFactory(payload && payload.voice_stt_available === true);" in wiring
    )
    assert 'fetchImpl("/health", { method: "GET", credentials: "same-origin" })' in wiring
    # The runtime proof compared the controller status key against this value.
    assert 'UNAVAILABLE_WIRING: "voice-unavailable-wiring",' in composer
    assert "registerRecognizerFactory: registerRecognizerFactory," in composer
    assert "getController: function () { return controller; }," in composer


def test_composer_starts_a_run_only_when_signed_in_and_factory_registered():
    """mic_enabled_when_mock_authenticated: the auth event flips availability."""
    composer = _read_static("voice-composer.js")
    # The same `padiem:auth-state` event the proof dispatched from the page.
    assert 'detach.push(listen(win, "padiem:auth-state", function (event) {' in composer
    assert "handleAuthState(detail.authenticated, detail.identityKey);" in composer
    assert "state.authKnown = true;" in composer
    assert "state.authenticated = next;" in composer
    # Ready requires the registered factory AND a known signed-in state.
    assert (
        "    function availability() {\n"
        '      if (destroyed || !mounted) return "unavailable";\n'
        '      if (typeof factory !== "function") return "unavailable";\n'
        '      if (state.authKnown !== true || state.authenticated !== true) return "unavailable";\n'
        '      return "ready";\n'
        "    }" in composer
    )
    # A click when not ready explains itself instead of starting a run.
    assert (
        'availabilityReason() === "signin" ? "voice-login-click" : STATUS_KEYS.UNAVAILABLE_WIRING'
        in composer
    )
    # A run only starts when ready, through the real adapter.
    assert (
        "if (destroyed || !mounted || !isReady() || isActiveRun()) return false;"
        in composer
    )
    assert "const adapterApi = win ? win.PadiemVoiceSttInput : null;" in composer


def test_final_transcript_lands_in_the_message_input_without_auto_submit():
    """stop_final_in_editable_input + auto_submit_count == 0."""
    composer = _read_static("voice-composer.js")
    adapter = _read_static("voice-stt-input.js")
    wiring = _read_static("voice-stt-wiring.js")
    live_session = _read_static("voice-live-session.js")
    # The finalized utterance goes through the adapter into the existing input.
    assert "return run.adapter.commitFinal(opts);" in composer
    assert "function commitFinal(opts) {" in adapter
    assert "function writeFinalInput(text) {" in adapter
    assert "writeInputValue(next);" in adapter
    # The input write mirrors a user edit and submits nothing.
    assert "input.value = next;" in composer
    assert 'input.dispatchEvent(new win.Event("input", { bubbles: true }));' in composer
    assert "Nothing is submitted here." in composer
    # Mode 1 (this wiring) never sends by itself; only voice-call modes may.
    assert "refuses to submit in the basic mode" in composer
    # No voice module carries any transport or chat-send route at all.
    for source in (composer, adapter):
        assert "fetch(" not in source
        assert "XMLHttpRequest" not in source
    for banned_route in ("/api/chat", "/api/claw/general"):
        for source in (wiring, adapter, composer, live_session):
            assert banned_route not in source


def test_each_chunk_upload_starts_a_fresh_recorder_with_its_own_init_segment():
    """composer_uploads_all_init / factory_uploads_all_init."""
    wiring = _read_static("voice-stt-wiring.js")
    # Only the first dataavailable of a recorder run carries the WebM init
    # segment, so every chunk gets its own recorder run.
    assert (
        "const active = new win.MediaRecorder(stream);" in wiring
    )
    assert "active.start(1000);" in wiring
    # The silence/stop path restarts a fresh cycle BEFORE the next upload, so
    # consecutive chunks never reuse a run without its init segment.
    assert (
        "if (!halting && !stopped && !cancelled) {\n"
        "            try { startRecorderCycle(); } catch (e) { emitError(ERROR_CODES.START_FAILED); }\n"
        "          }\n"
        "          deliverChunk(held, fromStop === true);" in wiring
    )
    # The uploaded body is the assembled chunk run, not a bare fragment.
    assert 'const blob = new win.Blob(held, { type: pickMimeType(win) || "audio/webm" });' in wiring


def test_factory_session_reports_one_final_per_cut_and_exposes_stop():
    """factory_started, factory_finals == cuts, factory_errors empty."""
    wiring = _read_static("voice-stt-wiring.js")
    composer = _read_static("voice-composer.js")
    # The composer consumes exactly this factory/handle shape from the wiring.
    assert "return function recognizerFactory(callbacks, runContext) {" in wiring
    assert "stop: function (reason) {" in wiring
    # The identity behind the run is verified before microphone access.
    assert 'if (typeof deps.verifyIdentity === "function") {' in wiring
    # Each assembled chunk reports exactly one final with a stable id.
    assert (
        "callbacks.onFinal({ text: text, utteranceId: utteranceId, stopped: fromStop === true || halting });"
        in wiring
    )
    assert (
        'const utteranceId = "u" + run.generation + "-" + run.sessionToken + "-" + utteranceSeq;'
        in wiring
    )
    # The #87 chunking constants the proof's controllable clock crossed.
    assert "const RECORDED_MIN_CHUNK_MS = 4000;" in wiring
    assert "const RECORDED_SILENCE_CUT_MS = 700;" in wiring
    assert "const RECORDED_MAX_CHUNK_MS = 20000;" in wiring
    assert (
        "idle >= RECORDED_SILENCE_CUT_MS || (chunkStartedAt && at - chunkStartedAt >= RECORDED_MAX_CHUNK_MS)"
        in wiring
    )
    assert "flushChunk(false);" in wiring
    # The VAD cut flows through the same Stop pipeline as a user stop.
    assert 'if (isSameRun(myRun)) stop("user-stopped");' in composer
    assert (
        "// VAD silence cut goes through the exact same Stop pipeline as the user"
        in composer
    )


def test_worker_serves_the_microphone_permissions_policy_header():
    """permissions_policy_header: the real serving path, not the test server."""
    assert (
        PERMISSIONS_POLICY == "camera=(), microphone=(self), geolocation=()"
    )
    assert BASE_SECURITY_HEADERS["Permissions-Policy"] == PERMISSIONS_POLICY
    # Every worker response path starts from the same security header set.
    for path in ("/", "/index.html", "/voice-stt-wiring.js", "/health"):
        headers = response_headers_for_path(path)
        assert headers["Permissions-Policy"] == PERMISSIONS_POLICY, path
    # The Worker entrypoint applies that header builder to its responses.
    worker = (ROOT / "worker.py").read_text(encoding="utf-8")
    assert "response_headers_for_path(" in worker
    assert "_apply_headers(" in worker
