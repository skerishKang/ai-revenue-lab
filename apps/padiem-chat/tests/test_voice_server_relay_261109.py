"""음성 서버 중계 가드/단위 시험 (#6828, 설계 CHAT_VOICE_RELAY_20261109.md).

- 정적 voice 파일에 외부 프로바이더 주소·키·모델 패턴이 없음(가드).
- live-token 응답이 브라우저에 token/model 을 반환하지 않음(가드).
- 서버 중계: 비로그인 거부, 동시 상한, 미설정 거부, 모델 주입+양방향 중계(단위, 가짜 프로바이더).
공개 코드에 프로바이더 실명 없음(일반 외부-호스트 패턴으로 검사).
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import voice_relay
from app.voice_stt_routes import _browser_live_payload

STATIC = Path(__file__).resolve().parents[1] / "static"

EXTERNAL_WS = re.compile(r"wss://[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EXTERNAL_HTTP = re.compile(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def test_static_voice_files_carry_no_provider_address_key_or_model():
    for path in sorted(STATIC.glob("voice-*.js")):
        src = path.read_text(encoding="utf-8")
        assert not EXTERNAL_WS.search(src), f"{path.name}: external WebSocket host"
        http = [h for h in EXTERNAL_HTTP.findall(src) if "w3.org" not in h]
        assert not http, f"{path.name}: external https host {http}"
        assert "access_token" not in src, f"{path.name}: credential in browser"
        assert "models/" not in src, f"{path.name}: model name in browser"


def test_browser_live_payload_never_returns_token_or_model():
    parsed = {"token": "secret-token", "expireTime": "2026-11-09T00:00:00Z",
              "session": {"model": "some-model", "vad_silence_ms": 1300,
                          "response_modalities": ["TEXT"],
                          "input_audio_transcription_mode": "VERBATIM"}}
    out = _browser_live_payload(parsed)
    assert "token" not in out
    assert "model" not in out.get("session", {})
    assert out["session"]["vad_silence_ms"] == 1300


class FakeTransport:
    async def live_token(self, *, body, product_id, session_id):
        return 200, json.dumps({"token": "t", "session": {"model": "m"}}).encode()


class FakeLink:
    def __init__(self):
        self.sent = []
        self._recv = [json.dumps({"serverContent": {"ok": True}}), None]

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def recv(self):
        return self._recv.pop(0)

    async def close(self):
        pass


class FakeConnector:
    def __init__(self):
        self.link = FakeLink()

    async def open(self, *, token, session):
        return self.link


class FakeWS:
    def __init__(self, messages=(), connector=None):
        self.app = SimpleNamespace(state=SimpleNamespace(
            voice_stt_transport=FakeTransport(),
            voice_relay_connector=connector if connector is not None else FakeConnector()))
        self._messages = list(messages)
        self.sent = []
        self.closed = None
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed = code

    async def iter_text(self):
        for m in self._messages:
            yield m

    async def send_text(self, data):
        self.sent.append(data)


async def _resolver_ok(ws):
    return SimpleNamespace(auth_session=SimpleNamespace(session_id="s", product_id="b62"))


async def _resolver_none(ws):
    return None


@pytest.mark.asyncio
async def test_relay_rejects_anonymous(monkeypatch):
    monkeypatch.setattr(voice_relay, "_active", 0)
    ws = FakeWS()
    await voice_relay.voice_relay_ws(ws, session_resolver=_resolver_none)
    assert ws.closed == 4401


@pytest.mark.asyncio
async def test_relay_enforces_concurrency_cap(monkeypatch):
    monkeypatch.setattr(voice_relay, "_active", voice_relay.MAX_CONCURRENT_RELAYS)
    ws = FakeWS()
    await voice_relay.voice_relay_ws(ws, session_resolver=_resolver_ok)
    assert ws.closed == 4429


@pytest.mark.asyncio
async def test_relay_unconfigured_origin_closes_4503(monkeypatch):
    monkeypatch.setattr(voice_relay, "_active", 0)
    ws = FakeWS(connector=voice_relay.SettingsRelayConnector(origin=""))
    await voice_relay.voice_relay_ws(ws, session_resolver=_resolver_ok)
    assert ws.closed == 4503


@pytest.mark.asyncio
async def test_relay_injects_model_server_side_and_pipes_both_ways(monkeypatch):
    monkeypatch.setattr(voice_relay, "_active", 0)
    connector = FakeConnector()
    ws = FakeWS(messages=[json.dumps({"setup": {"generationConfig": {}}}),
                          json.dumps({"realtimeInput": {"mediaChunks": []}})],
                connector=connector)
    await voice_relay.voice_relay_ws(ws, session_resolver=_resolver_ok)
    # The browser setup had no model; the relay injected it before the provider.
    assert connector.link.sent[0]["setup"]["model"] == "models/m"
    # The provider response was piped back to the browser unchanged.
    assert any("serverContent" in m for m in ws.sent)
    assert voice_relay._active == 0
