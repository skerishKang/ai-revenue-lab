"""#4643 live-token route: browser -> Chat Worker -> private STT Worker.

These are offline tests. They exercise the reviewed fail-closed decisions of
the live-token bridge with fakes only. They perform no provider call, no
Secret read and no paid request.

The route exists because the browser must never hold a long-lived provider
key and must never reach the private STT Worker directly. What the browser
receives is one short-lived, model-locked, single-use ephemeral token plus the
browser-safe session parameters.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _routes_module():
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import voice_stt_routes

    return voice_stt_routes


# ---------------------------------------------------------------------------
# Registration and closed request surface
# ---------------------------------------------------------------------------


def test_live_token_route_is_registered_for_chat_and_claw():
    source = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert "VOICE_LIVE_TOKEN_PATH" in source
    assert "CLAW_VOICE_LIVE_TOKEN_PATH" in source
    assert "voice_live_token" in source
    routes = _routes_module()
    assert routes.LIVE_TOKEN_PATH == "/api/voice/live-token"
    assert routes.CLAW_LIVE_TOKEN_PATH == "/api/claw/voice/live-token"
    assert routes.STT_LIVE_TOKEN_PATH == "/internal/v1/voice/live-token"


def test_the_browser_request_surface_is_closed():
    routes = _routes_module()
    # Exactly one opaque marker field. No identity, tenant, entitlement,
    # plan, product, cost or budget field may be accepted from the browser.
    assert routes._LIVE_TOKEN_BROWSER_FIELDS == {"sessionId"}
    for forbidden in (
        "product_id",
        "tenant_id",
        "entitlement",
        "cost",
        "budget",
        "plan",
        "token",
        "api_key",
    ):
        assert forbidden not in routes._LIVE_TOKEN_BROWSER_FIELDS


def test_the_internal_stt_route_is_never_exposed_to_the_browser():
    routes = _routes_module()
    assert routes.STT_INTERNAL_ORIGIN.startswith("https://")
    assert routes.STT_INTERNAL_ORIGIN not in (routes.LIVE_TOKEN_PATH, routes.CLAW_LIVE_TOKEN_PATH)
    assert routes.STT_LIVE_TOKEN_PATH not in (routes.LIVE_TOKEN_PATH, routes.CLAW_LIVE_TOKEN_PATH)


def test_the_live_token_request_body_is_bounded():
    routes = _routes_module()
    assert 0 < routes.MAX_LIVE_TOKEN_REQUEST_BYTES <= 64 * 1024


# ---------------------------------------------------------------------------
# Service Binding transport
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    async def text(self) -> str:
        return self._payload.decode("utf-8")


class _FakeBinding:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.seen: dict = {}

    async def fetch(self, request):
        self.seen["url"] = request["url"]
        self.seen["method"] = request["method"]
        self.seen["headers"] = request["headers"]
        self.seen["body"] = request["body"]
        return _FakeResponse(self.payload, self.status)


class _FakeRequest:
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


def test_the_transport_sends_the_reviewed_opaque_clues_to_the_private_worker():
    routes = _routes_module()
    binding = _FakeBinding(
        json.dumps(
            {
                "ok": True,
                "token": "auth_tokens/abc",
                "expireTime": "2026-10-20T00:30:00Z",
                "session": {"model": "gemini-3.5-transcribe-live", "vad_silence_ms": 1300},
            }
        ).encode("utf-8")
    )
    transport = routes.CloudflareVoiceSttServiceTransport(binding, _FakeRequest)
    status, raw = asyncio.run(
        transport.live_token(product_id="b62", session_id="sess-xyz")
    )
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["token"] == "auth_tokens/abc"
    assert binding.seen["headers"]["x-padiem-product-id"] == "b62"
    assert binding.seen["headers"]["x-padiem-auth-session-id"] == "sess-xyz"
    assert binding.seen["method"] == "POST"
    assert binding.seen["url"].endswith(routes.STT_LIVE_TOKEN_PATH)
    # The forwarded body carries the reviewed opaque marker only.
    forwarded = json.loads(binding.seen["body"])
    assert set(forwarded) == {"sessionId"}


def test_the_transport_never_leaks_a_secret_value():
    routes = _routes_module()
    source = (ROOT / "app" / "voice_stt_routes.py").read_text(encoding="utf-8")
    # The Chat Worker reads no Cloudflare Secret for this route: the key stays
    # inside the private Worker.
    assert "PADIEM_GEMINI_API_KEY" not in source
    assert "secrets_store" not in source
    assert "read_bounded_service_binding_body" in source


def test_the_browser_response_carries_only_the_token_and_the_session_parameters():
    routes = _routes_module()
    source = (ROOT / "app" / "voice_stt_routes.py").read_text(encoding="utf-8")
    # The minted token and the browser-safe session parameters only.
    assert '"token": token.strip()' in source
    assert 'payload_out["session"] = session_config' in source
    # No provider key, no entitlement and no account identity is forwarded.
    for forbidden in ("api_key", "secret", "tenant_id", "entitlement"):
        assert f'"{forbidden}"' not in source


def test_a_refused_private_worker_keeps_its_bounded_code():
    routes = _routes_module()
    source = (ROOT / "app" / "voice_stt_routes.py").read_text(encoding="utf-8")
    # The STT Worker's own refusal code is passed through so the UI can stay
    # truthful about a cost or authority refusal.
    assert "voice_stt_denied" in source
    assert "live_token_unavailable" in source
    assert "voice_stt_unavailable" in source


def test_the_browser_never_holds_a_long_lived_provider_key():
    """The wiring and the live engine carry no provider credential."""
    for name in ("voice-stt-wiring.js", "voice-live-transcript.js"):
        source = (ROOT / "static" / name).read_text(encoding="utf-8")
        code = source.replace("/*", "\n/*").split("*/")[-1]
        # Strip comments the same way the reviewed wiring guard does.
        import re

        code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        code = re.sub(r"//[^\n]*", "", code)
        for forbidden in (
            "PADIEM_GEMINI_API_KEY",
            "PADIEM_GROQ_API_KEY",
            "x-goog-api-key",
            "Authorization",
            "padiem-voice-stt",
        ):
            assert forbidden not in code, f"{name} exposes {forbidden}"


def test_the_live_engine_is_loaded_before_the_wiring_that_selects_it():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "./voice-live-transcript.js" in html
    assert "./voice-stt-input.js" in html
    # The shared adapter owns the turn buffer, so it loads first.
    assert html.index("./voice-stt-input.js") < html.index("./voice-live-transcript.js")
    # The live engine must be available before the wiring selects it.
    assert html.index("./voice-live-transcript.js") < html.index("./voice-stt-wiring.js")


def test_the_audio_worklet_module_is_served():
    worklet = ROOT / "static" / "voice-live-pcm-worklet.js"
    assert worklet.exists()
    source = worklet.read_text(encoding="utf-8")
    assert "registerProcessor('padiem-voice-live-pcm'" in source
    # The render thread must never play the microphone back to the user.
    assert "channel.fill(0)" in source
