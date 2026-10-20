"""#4643: the Chat Worker live-token route for the Gemini Live session.

The browser needs a short-lived, model-locked token to open a real-time Live
transcription session. The long-lived provider key stays in the private STT
Worker, which is reachable only over a Service Binding from the Chat Worker,
and the Control Plane admits the call against the same voice entitlement and
cost authority the transcription route uses.

These are offline tests: the STT Worker is a fake, so no provider call, no
paid request and no credential read happens here.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
ROUTES_PY = APP / "voice_stt_routes.py"
APP_FACTORY = APP / "app_factory.py"
INDEX_HTML = ROOT / "static" / "index.html"


def _routes_module():
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import voice_stt_routes  # type: ignore

    return voice_stt_routes


def test_the_live_token_route_exists_for_chat_and_claw() -> None:
    routes = _routes_module()
    assert routes.LIVE_TOKEN_PATH == "/api/voice/live-token"
    assert routes.CLAW_LIVE_TOKEN_PATH == "/api/claw/voice/live-token"
    # The internal path stays internal: the browser never addresses it.
    assert routes.STT_LIVE_TOKEN_PATH == "/internal/v1/voice/live-token"
    assert routes.STT_INTERNAL_ORIGIN.startswith("https://")
    factory = APP_FACTORY.read_text(encoding="utf-8")
    assert "voice_live_token" in factory
    assert "VOICE_LIVE_TOKEN_PATH" in factory
    assert "CLAW_VOICE_LIVE_TOKEN_PATH" in factory


def test_the_transport_forwards_both_opaque_clues_to_the_stt_worker() -> None:
    routes = _routes_module()
    seen: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self._payload = payload

        async def text(self):
            return self._payload

    class FakeBinding:
        async def fetch(self, req):
            seen["url"] = req["url"]
            seen["headers"] = req["headers"]
            seen["body"] = req["body"]
            return FakeResponse(json.dumps({"token": "auth_tokens/x", "session": {"model": "m"}}))

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

    transport = routes.CloudflareVoiceSttServiceTransport(FakeBinding(), FakeRequest)
    status, raw = asyncio.run(
        transport.live_token(
            body={"sessionId": "sess-xyz"},
            product_id="b62",
            session_id="sess-xyz",
        )
    )
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["token"] == "auth_tokens/x"
    assert seen["headers"]["x-padiem-product-id"] == "b62"
    assert seen["headers"]["x-padiem-auth-session-id"] == "sess-xyz"
    # The private origin is never browser-addressable.
    assert routes.STT_INTERNAL_ORIGIN in seen["url"]


def _route_body() -> str:
    """Only the route function, not the transport class below it."""
    source = ROUTES_PY.read_text(encoding="utf-8")
    return source.split("async def voice_live_token", 1)[1].split("\nclass ", 1)[0]


def test_the_route_refuses_without_an_authenticated_canonical_session() -> None:
    routes = _routes_module()
    body = _route_body()
    # No session, no provider call.
    assert "voice_signin_required" in body
    assert body.index("voice_signin_required") < body.index("transport.live_token")
    # No transport, no token.
    assert "voice_stt_unavailable" in body
    assert body.index("voice_stt_unavailable") < body.index("transport.live_token")
    assert callable(routes.voice_live_token)


def test_the_route_never_returns_a_provider_key() -> None:
    body = _route_body()
    # The long-lived key belongs to the private STT Worker. Only the
    # short-lived token and the browser-safe session block cross back.
    assert "PADIEM_GEMINI_API_KEY" not in body
    assert "x-goog-api-key" not in body
    assert '"token"' in body
    assert '"session"' in body
    # The browser never learns the internal origin or the internal path.
    assert "STT_INTERNAL_ORIGIN" not in body
    assert "STT_LIVE_TOKEN_PATH" not in body


def test_the_route_is_origin_and_media_type_guarded() -> None:
    body = _route_body()
    assert "origin_rejected" in body
    assert "unsupported_media_type" in body
    assert "request_too_large" in body
    assert "invalid_json" in body
    assert "unsupported_field" in body
    # The body is bounded by a small dedicated limit, not the audio envelope.
    assert "MAX_VOICE_LIVE_TOKEN_BYTES" in body
    routes = _routes_module()
    assert routes.MAX_VOICE_LIVE_TOKEN_BYTES <= 16 * 1024


def test_the_browser_reaches_the_token_over_the_same_origin_only() -> None:
    wiring = (ROOT / "static" / "voice-stt-wiring.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", wiring, flags=re.DOTALL)
    code = re.sub(r"//[^\n]*", "", code)
    assert '"/api/voice/live-token"' in code
    assert '"/api/claw/voice/live-token"' in code
    # The private worker origin and the provider endpoint are not in the
    # browser wiring: the token request is same-origin.
    assert "padiem-voice-stt" not in code
    assert "generativelanguage" not in code
    assert "credentials: \"same-origin\"" in code


def test_the_stt_worker_owns_the_live_token_route() -> None:
    worker = (ROOT.parent / "padiem-voice-stt" / "worker.py").read_text(encoding="utf-8")
    assert 'LIVE_TOKEN_PATH = "/internal/v1/voice/live-token"' in worker
    assert "CAPABILITY_LIVE_TOKEN" in worker
    # The worker reads the provider key from its own binding only.
    assert "GEMINI_API_KEY_BINDING" in worker
    contract = (ROOT.parent / "padiem-voice-stt" / "voice_stt_contract.py").read_text(encoding="utf-8")
    assert "liveConnectConstraints" in contract
    assert "def to_public_dict" in contract
