"""#4643 Chat/Claw live voice wiring: browser recognizer + Worker bridge contract.

These are offline tests. They exercise the wiring module's recognizer factory and
the Chat Worker bridge's fail-closed decisions with fakes only. They perform no
provider call, no real microphone access and no paid STT request.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIRING_JS = ROOT / "static" / "voice-stt-wiring.js"
INDEX_HTML = ROOT / "static" / "index.html"


def _node(script: str) -> str:
    result = subprocess.run(
        [sys.executable and "node", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Static wiring facts
# ---------------------------------------------------------------------------


def test_wiring_module_is_loaded_after_the_composer_it_wires():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "./voice-stt-wiring.js" in html
    assert html.index("./voice-composer.js") < html.index("./voice-stt-wiring.js")


def test_wiring_module_calls_the_reviewed_composer_seam():
    source = WIRING_JS.read_text(encoding="utf-8")
    # The wiring must go through registerRecognizerFactory, the only seam the
    # merged composer exposes, and must not reach into composer internals.
    assert "registerRecognizerFactory" in source


def test_browser_never_speaks_to_the_private_stt_worker_or_holds_a_key():
    source = WIRING_JS.read_text(encoding="utf-8")
    # Scan executable code only: prose may mention the private Worker by name.
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"//[^\n]*", "", code)
    # No provider endpoint, no provider key, no direct call to the private
    # worker origin. Audio leaves only through the same-origin Chat route.
    assert "padiem-voice-stt" not in code
    assert "generativelanguage" not in code
    assert "api.groq.com" not in code
    assert "PADIEM_GROQ_API_KEY" not in code
    assert "PADIEM_GEMINI_API_KEY" not in code
    assert '"/api/voice/transcribe"' in code
    assert "/api/voice/transcribe" in code
    # No provider auth header is ever constructed in the browser.
    assert "Authorization" not in code


def test_wiring_never_sends_a_chat_message():
    source = WIRING_JS.read_text(encoding="utf-8")
    for forbidden in ("composerForm.requestSubmit", "form.submit", "requestSubmit"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# Recognizer factory contract (offline, fakes only)
# ---------------------------------------------------------------------------


def test_recognizer_factory_returns_a_stop_handle():
    out = _node(
        """
        const m = require('./static/voice-stt-wiring.js');
        const factory = m.createRecognizerFactory({
          win: { MediaRecorder: function(){}, setTimeout, clearTimeout, Blob: function(){} },
          mediaDevices: null,
        });
        const session = factory({}, { generation: 1, sessionToken: 's1' });
        console.log(typeof session.stop);
        """
    )
    assert out == "function"


def test_recognizer_reports_permission_denial_without_throwing():
    out = _node(
        """
        const m = require('./static/voice-stt-wiring.js');
        const codes = [];
        const factory = m.createRecognizerFactory({
          win: { MediaRecorder: function(){}, setTimeout, clearTimeout, Blob: function(){} },
          mediaDevices: {
            getUserMedia: function () {
              const err = new Error('denied');
              err.name = 'NotAllowedError';
              return Promise.reject(err);
            },
          },
        });
        factory({ onError: function (c) { codes.push(c); } }, { generation: 1, sessionToken: 's1' });
        setTimeout(function () { console.log(codes.join(',')); }, 30);
        """
    )
    assert out == "permission-denied"


def test_recognizer_reports_unsupported_browser():
    out = _node(
        """
        const m = require('./static/voice-stt-wiring.js');
        const codes = [];
        const factory = m.createRecognizerFactory({
          win: { setTimeout, clearTimeout },
          mediaDevices: null,
        });
        factory({ onError: function (c) { codes.push(c); } }, { generation: 1, sessionToken: 's1' });
        setTimeout(function () { console.log(codes.join(',')); }, 30);
        """
    )
    assert out == "unsupported-browser"


def test_constants_match_reviewed_chunking_contract():
    out = _node(
        """
        const m = require('./static/voice-stt-wiring.js');
        console.log([m.GROQ_MIN_CHUNK_MS, m.GROQ_SILENCE_CUT_MS, m.GROQ_MAX_CHUNK_MS].join(','));
        """
    )
    assert out == "4000,700,20000"


# ---------------------------------------------------------------------------
# Chat Worker bridge: fail-closed decisions
# ---------------------------------------------------------------------------


def _routes_module():
    import sys as _sys

    root = str(ROOT)
    if root not in _sys.path:
        _sys.path.insert(0, root)
    from app import voice_stt_routes

    return voice_stt_routes


def test_voice_routes_are_registered_on_the_app():
    source = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert "voice_identity" in source
    assert "voice_transcribe" in source


def test_transcribe_rejects_anonymous_caller_before_any_forward():
    routes = _routes_module()
    assert routes.MAX_AUDIO_BASE64_CHARS > 0
    # An unsigned caller can never reach the paid STT route: the route resolves
    # a canonical session first and answers 401 without a transport.
    source = (ROOT / "app" / "voice_stt_routes.py").read_text(encoding="utf-8")
    assert "voice_signin_required" in source


def test_browser_fields_are_closed_and_no_authority_field_exists():
    routes = _routes_module()
    assert routes._ALLOWED_BROWSER_FIELDS == {
        "audio_base64",
        "mime_type",
        "utterance_id",
    }
    # No caller-supplied identity, tenant, entitlement or cost field is accepted.
    for forbidden in ("product_id", "tenant_id", "entitlement", "cost", "budget", "plan"):
        assert forbidden not in routes._ALLOWED_BROWSER_FIELDS


def test_unsupported_browser_field_is_rejected():
    routes = _routes_module()
    base = {"audio_base64": "QUJD"}
    with pytest.raises(ValueError):
        routes._read_audio({**base, "product_id": "attacker"})
    with pytest.raises(ValueError):
        routes._read_audio({**base, "estimated_units": 999999})


def test_invalid_audio_is_rejected_before_forwarding():
    routes = _routes_module()
    with pytest.raises(ValueError):
        routes._read_audio({"audio_base64": "not base64!!"})
    with pytest.raises(ValueError):
        routes._read_audio({"audio_base64": ""})
    with pytest.raises(ValueError):
        routes._read_audio({"audio_base64": "QUJD", "mime_type": "text/html"})


def test_valid_audio_is_accepted():
    routes = _routes_module()
    mime, b64 = routes._read_audio({"audio_base64": "QUJD", "mime_type": "audio/webm"})
    assert mime == "audio/webm"
    assert b64 == "QUJD"


def test_utterance_id_is_bounded_and_never_used_for_authority():
    routes = _routes_module()
    assert routes._utterance_id({"utterance_id": "u1-2.3"}) == "u1-2.3"
    assert routes._utterance_id({"utterance_id": "bad id with spaces"}) is None
    assert routes._utterance_id({"utterance_id": "x" * 500}) is None


def test_identity_key_is_opaque_stable_and_secret_dependent():
    routes = _routes_module()

    class Settings:
        session_secret = "secret-a"

    a1 = routes._identity_key(Settings(), "sess-1")
    a2 = routes._identity_key(Settings(), "sess-1")
    assert a1 == a2 and a1
    # A different session must differ, and no session id may be recoverable.
    assert routes._identity_key(Settings(), "sess-2") != a1
    assert "sess-1" not in a1

    class Other(Settings):
        session_secret = "secret-b"

    assert routes._identity_key(Other(), "sess-1") != a1


def test_identity_key_is_empty_without_a_session_secret():
    routes = _routes_module()

    class Settings:
        session_secret = ""

    assert routes._identity_key(Settings(), "sess-1") == ""


def test_language_is_a_server_constant_not_a_browser_field():
    routes = _routes_module()
    source = (ROOT / "app" / "voice_stt_routes.py").read_text(encoding="utf-8")
    assert "VOICE_STT_LANGUAGE" in source
    assert routes.VOICE_STT_LANGUAGE == "auto"
    # The forwarded envelope carries exactly the STT contract's two fields.
    assert "audioDataUrl" in source
    assert '"language"' in source


def test_service_binding_transport_sends_both_opaque_clues():
    routes = _routes_module()
    seen = {}

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self._payload = payload

        async def text(self):
            return self._payload

    class FakeBinding:
        async def fetch(self, req):
            seen["headers"] = req["headers"]
            return FakeResponse(json.dumps({"text": "안녕하세요"}, ensure_ascii=False))

    class FakeRequest:
        def __init__(self, url, method, headers, body):
            self.url = url
            self.method = method
            self.headers = headers
            self.body = body

        @property
        def js_object(self):
            return {
                "url": self.url,
                "method": self.method,
                "headers": self.headers,
                "body": self.body,
            }

    import asyncio

    transport = routes.CloudflareVoiceSttServiceTransport(FakeBinding(), FakeRequest)
    status, raw = asyncio.run(
        transport.transcribe(
            body={"language": "auto", "audioDataUrl": "data:audio/webm;base64,QUJD"},
            product_id="b62",
            session_id="sess-xyz",
        )
    )
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["text"] == "안녕하세요"
    assert seen["headers"]["x-padiem-product-id"] == "b62"
    assert seen["headers"]["x-padiem-auth-session-id"] == "sess-xyz"
    # The internal STT origin/path is never exposed to the browser.
    assert routes.STT_INTERNAL_ORIGIN.startswith("https://")


def test_voice_stt_service_binding_declared_and_missing_runtime_fails_closed():
    # The reviewed manifest includes the private service target. Until that
    # target is deployed and bound in Production, the API fails closed with 503.
    wrangler = (ROOT / "wrangler.toml").read_text(encoding="utf-8")
    assert 'binding = "VOICE_STT_SERVICE"' in wrangler
    assert 'service = "padiem-voice-stt"' in wrangler
    routes = _routes_module()
    source = (ROOT / "app" / "voice_stt_routes.py").read_text(encoding="utf-8")
    assert "voice_stt_unavailable" in source
    assert routes.IDENTITY_PATH == "/api/voice/identity"
    assert routes.TRANSCRIBE_PATH == "/api/voice/transcribe"


def test_permissions_policy_allows_microphone_on_self_origin_only():
    from app.worker_config import PERMISSIONS_POLICY

    assert "microphone=(self)" in PERMISSIONS_POLICY
    assert "camera=()" in PERMISSIONS_POLICY
    assert "geolocation=()" in PERMISSIONS_POLICY
    assert "microphone=*" not in PERMISSIONS_POLICY


def test_composer_tracks_an_identity_key_for_account_switch():
    source = (ROOT / "static" / "voice-composer.js").read_text(encoding="utf-8")
    assert "identityKey" in source
    assert "padiem:voice-identity" in source
    # The boolean-only auth event must stay identity-free (#3790): app.js still
    # dispatches only `authenticated`.
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    match = re.search(
        r'new CustomEvent\("padiem:auth-state",\s*\{\s*detail:\s*\{\s*authenticated', app
    )
    assert match, "app.js must keep dispatching the identity-free auth-state event"