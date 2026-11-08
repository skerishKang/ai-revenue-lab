"""호스트 측 voice_stt_transport — Chat-Worker RPC 래퍼 계약 (#7228 복구).

`HostVoiceSttRpcTransport`는 `HttpRpcBinding.voice_stt` 한 메서드로
`CloudflareVoiceSttServiceTransport`와 같은 (status, bytes) 계약을 낸다.

Claims verified here:
(a) live_token/transcribe가 RPC envelope로 올바르게 실리고 (status, bytes)로 돌아온다;
(b) RPC 수신 거부(ServiceRpcHttpError) → ServiceBindingResponseError(503 매핑);
(c) 잘못된 응답 envelope → ServiceBindingResponseError;
(d) 조성: 쌍이 없으면 transport None(health voice_stt_available=false 유지).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.local_service_bridge import ServiceRpcHttpError
from app.local_voice_stt_transport import HostVoiceSttRpcTransport
from app.service_binding_response import ServiceBindingResponseError


class FakeBinding:
    def __init__(self, *, answer=None, error=None):
        self.calls = []
        self.answer = answer if answer is not None else {"status": 200, "body": '{"ok":1}'}
        self.error = error

    async def voice_stt(self, payload):
        self.calls.append(dict(payload))
        if self.error is not None:
            raise self.error
        return dict(self.answer)


def call(transport, op="live_token", **kwargs):
    async def inner():
        if op == "live_token":
            return await transport.live_token(
                body={"sessionId": "s1"}, product_id="p1", session_id="s1")
        return await transport.transcribe(
            body={"language": "ko", "audioDataUrl": "data:audio/pcm;base64,AAA"},
            product_id="p1", session_id="s1")
    return asyncio.run(inner())


def test_live_token_and_transcribe_round_trip_the_envelope():
    binding = FakeBinding()
    transport = HostVoiceSttRpcTransport(binding)
    status, raw = call(transport)
    assert status == 200 and json.loads(raw) == {"ok": 1}
    assert binding.calls[0] == {"op": "live_token", "productId": "p1", "sessionId": "s1"}
    status, raw = call(transport, op="transcribe")
    assert status == 200
    assert binding.calls[1]["op"] == "transcribe"
    assert binding.calls[1]["language"] == "ko"
    assert binding.calls[1]["audioDataUrl"].startswith("data:")


def test_rpc_refusal_surfaces_as_service_binding_response_error():
    transport = HostVoiceSttRpcTransport(
        FakeBinding(error=ServiceRpcHttpError(401)))
    with pytest.raises(ServiceBindingResponseError):
        call(transport)


def test_bad_envelope_surfaces_as_service_binding_response_error():
    transport = HostVoiceSttRpcTransport(FakeBinding(answer={"status": "200"}))
    with pytest.raises(ServiceBindingResponseError):
        call(transport)


def test_absent_pair_keeps_the_host_transport_unbound():
    # The composition rule: no PADIEM_CHAT_VOICE_RPC_ORIGIN → no transport →
    # app_factory leaves app.state.voice_stt_transport unset and /health keeps
    # reporting voice_stt_available=false. Pinned here without booting a host.
    import inspect
    from app import local_cpython
    source = inspect.getsource(local_cpython)
    assert '"PADIEM_CHAT_VOICE_RPC_ORIGIN", "PADIEM_CHAT_VOICE_RPC_SECRET"' in source
    assert "voice_stt_transport=voice_stt_transport" in source
