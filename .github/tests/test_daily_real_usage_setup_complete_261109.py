"""#7293 후속 계약: 릴레이 setup 완료 판정은 키 존재로 한다.

Google Live는 setup 응답으로 ``{"setupComplete": {}}`` — 빈 메시지 객체를 돌려
준다. 빈 객체는 파이썬에서 falsy이므로, 진위(truthiness) 판정은 건강한 릴레이
세션을 매번 '미완료'로 잘못 읽는다(실행 42638392269의 voice_relay 실패 원인).
브라우저는 키 존재로 판정하므로 실제 음성은 동작한다 — 점검 스크립트만 틀렸다.
같은 함정이 ``inputTranscription.finished``에도 있다. 또한 전사 병합이
dict에 ``.text`` 속성 접근을 해 AttributeError로 \'voice_relay_transport_error\'
을 만들었다(실행 42638392269가 보고한 바로 그 코드). 이 파일은 세 판정을
모두 고정한다: 빈 객체도 완료이고, 전사는 실제로 병합되며, 진위 판정은
돌아오지 않는다.
"""
from __future__ import annotations

import asyncio
import importlib.util
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


def test_an_empty_setupcomplete_object_completes_the_setup():
    mod = _load_module()
    frames = [json.dumps({"setupComplete": {}})]
    transcript_frames = [
        json.dumps({"serverContent": {"inputTranscription": {"text": "안녕하세요 반갑"}}}),
        json.dumps({"serverContent": {"inputTranscription": {"finished": {}}}}),
    ]
    ws = FakeWs(frames + transcript_frames)

    def fake_connect(url, headers=None, **kwargs):
        class _Ctx:
            async def __aenter__(self):
                return ws

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    async def run():
        orig_connect = mod._connect_ws
        mod._connect_ws = fake_connect
        try:
            return await mod._relay_transcribe("cookie-x", {
                "response_modalities": ["AUDIO"],
                "vad_silence_ms": 500,
                "input_audio_transcription_mode": "auto",
            }, b"\x00\x00" * 4000)
        finally:
            mod._connect_ws = orig_connect

    transcript, close_code = asyncio.run(run())
    assert transcript == "안녕하세요 반갑", transcript
    # the flow actually reached the audio stage: the setup was recognized
    assert any("realtimeInput" in s for s in ws.sent), ws.sent
    assert close_code == 0


def test_the_check_never_judges_setup_by_truthiness():
    source = CHECK.read_text(encoding="utf-8")
    assert 'frame.get("setupComplete")' not in source, (
        "a truthiness test drops Google's empty SetupComplete object and "
        "turns every healthy relay session into a fake failure")
    assert '"setupComplete" in frame' in source
    assert 'final.get("finished")' not in source
    assert '"finished" in final' in source
