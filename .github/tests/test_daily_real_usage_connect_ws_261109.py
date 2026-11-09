"""#7293 후속 계약: 릴레이 연결자는 ``async with`` 로 여는 객체여야 한다.

``websockets.connect`` 는 그 자체가 비동기 컨텍스트 매니저인 연결자다. 이걸
``async def _connect_ws`` 로 감싸 await 해서 돌려주면 ``async with`` 가 연결자
대신 코루틴을 받고, 매 실행

    TypeError: 'coroutine' object does not support the asynchronous context
    manager protocol

로 죽는다 — 실행 42664572275가 보고한 ``voice_relay_transport_error_TypeError``
(음성 흐름 100% 실패, 서버는 정상). 앞선 시험은 ``_connect_ws`` 를 동기 가짜로
갈아 끼워서 이 결함을 가렸다. 이 파일은 가짜를 끼우지 않고 실제 함수를 통과시켜
세 가지를 고정한다:

  1. 실제 ``_connect_ws`` 는 코루틴이 아니라 컨텍스트 매니저를 돌려준다,
  2. 헤더 인자 이름이 다른 websockets(<14)에서도 연결자를 돌려준다(반대쪽 계약),
  3. 전송 계층 실패 코드는 예외 클래스와 스크럽한 메시지를 담는다.
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE.parent / "scripts" / "daily_real_usage_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("daily_real_usage_check", CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeWs:
    """The relay's browser side, scripted. Sends are recorded for assertions."""

    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        if not self._incoming:
            raise TimeoutError()
        return self._incoming.pop(0)


class FakeConnect:
    """Stand-in for ``websockets.connect``: records the call, opens ``ws``."""

    def __init__(self, ws, reject=()):
        self.ws = ws
        self.reject = set(reject)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for name in self.reject:
            if name in kwargs:
                raise TypeError(f"connect() got an unexpected keyword argument {name!r}")
        ws = self.ws

        class _Ctx:
            async def __aenter__(self):
                return ws

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _fake_frames():
    return [
        json.dumps({"setupComplete": {}}),
        json.dumps({"serverContent": {"inputTranscription": {"text": "안녕하세요 반갑"}}}),
        json.dumps({"serverContent": {"inputTranscription": {"finished": {}}}}),
    ]


def test_the_real_connect_ws_returns_a_context_manager_not_a_coroutine():
    """The defect: a coroutine is not an async context manager."""
    mod = _load_module()
    assert not inspect.iscoroutinefunction(mod._connect_ws), (
        "async with _connect_ws(...) receives a coroutine and fails every run "
        "with TypeError: 'coroutine' object does not support the asynchronous "
        "context manager protocol")
    connector = mod._connect_ws("wss://example.invalid/api/voice/relay", {})
    assert not inspect.iscoroutine(connector), type(connector).__name__
    assert hasattr(connector, "__aenter__") and hasattr(connector, "__aexit__"), (
        "the connector must be usable directly as 'async with', as websockets "
        "documents", type(connector).__name__)


def test_the_relay_opens_the_connector_the_real_shim_builds():
    """Load-bearing: the flow must reach the audio stage through _connect_ws."""
    mod = _load_module()
    ws = FakeWs(_fake_frames())
    fake = FakeConnect(ws)
    real = __import__("websockets").connect
    __import__("websockets").connect = fake
    try:
        transcript, close_code = asyncio.run(mod._relay_transcribe("cookie-x", {
            "response_modalities": ["AUDIO"],
            "vad_silence_ms": 500,
            "input_audio_transcription_mode": "auto",
        }, b"\x00\x00" * 4000))
    finally:
        __import__("websockets").connect = real
    assert transcript == "안녕하세요 반갑", transcript
    assert close_code == 0
    assert len(fake.calls) == 1, fake.calls
    url, kwargs = fake.calls[0]
    assert url.startswith("wss://") and url.endswith("/api/voice/relay"), url
    assert any("realtimeInput" in s for s in ws.sent), ws.sent


def test_the_older_header_argument_name_still_yields_a_connector():
    """Opposite side: websockets < 14 rejects additional_headers."""
    mod = _load_module()
    ws = FakeWs(_fake_frames())
    fake = FakeConnect(ws, reject=("additional_headers",))
    real = __import__("websockets").connect
    __import__("websockets").connect = fake
    try:
        transcript, close_code = asyncio.run(mod._relay_transcribe("cookie-x", {
            "response_modalities": ["AUDIO"],
            "vad_silence_ms": 500,
            "input_audio_transcription_mode": "auto",
        }, b"\x00\x00" * 4000))
    finally:
        __import__("websockets").connect = real
    assert transcript == "안녕하세요 반갑", transcript
    assert close_code == 0
    assert len(fake.calls) == 2, fake.calls
    assert "extra_headers" in fake.calls[1][1]
    assert fake.calls[1][1]["extra_headers"].get("Origin")


def test_a_transport_failure_names_the_class_and_scrubs_the_message():
    mod = _load_module()
    flow = mod.Flow("voice_relay")
    mod.bounded_call = lambda *a, **k: (
        200, {"session": {"input_audio_transcription_mode": "auto"}}, {})
    mod._tts_pcm16k = lambda: b"\x00\x00"

    async def boom(*a, **k):
        raise TypeError(
            "'coroutine' object does not support\n  the asynchronous context "
            "manager protocol Cookie=padiem_session=cookie-value-1")

    mod._voice_flow = boom
    mod.flow_voice(flow, "cookie-x")
    assert flow.verdict == "FAIL"
    assert flow.code.startswith("voice_relay_transport_error_TypeError_"), flow.code
    assert "coroutine" in flow.code
    assert "\n" not in flow.code
    # the session cookie's name never reaches a public report line
    assert "padiem_session=" not in flow.code
    assert "Cookie=session=" in flow.code
