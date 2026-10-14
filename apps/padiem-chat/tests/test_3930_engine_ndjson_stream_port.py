"""#3930 — opt-in bounded Engine orchestration NDJSON stream transport."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from padiem_ai_engine_client import (
    ENGINE_INTERNAL_ORIGIN, ENGINE_ORCHESTRATE_STREAM_PATH,
    EngineStreamTransportResponse, PadiemAiEngineClient, PadiemAiEngineClientError,
)
from padiem_ai_engine_client.orchestration_stream import (
    EngineNdjsonContractError, decode_orchestration_ndjson,
    MAX_NDJSON_TERMINAL_LINE_BYTES, MAX_NDJSON_LINE_BYTES,
)
from app.service_binding_response import ServiceBindingResponseTooLarge
from app.worker_orchestration import CloudflareEngineServiceTransport


def wire(kind: str, obj=None) -> bytes:
    body = {"ok": True, kind: obj or {"kind": "run_started", "sequence": 1}}
    return (json.dumps(body, separators=(",", ":")) + "\n").encode()


def consume(chunks):
    async def go():
        return [x async for x in decode_orchestration_ndjson(chunks)]
    return asyncio.run(go())


async def chunks_of(*data):
    for chunk in data:
        yield chunk


def test_ndjson_chunk_split_and_real_terminal():
    data = wire("event") + wire("orchestration", {"events": [], "result": True})
    parsed = consume(chunks_of(data[:7], data[7:28], data[28:]))
    assert len(parsed) == 2
    assert parsed[0]["event"]["kind"] == "run_started"
    assert parsed[1]["orchestration"]["result"] is True


@pytest.mark.parametrize("data,reason", [
    (b"", "truncated_stream"),
    (wire("event"), "truncated_stream"),
    (wire("orchestration"), "invalid_stream_terminal"),
    (wire("event") + b'{"ok":false,"error":{"code":"provider_fail"}}\n', "engine_stream_error"),
    (wire("event") + b'{"ok":true,"other":3}\n', "invalid_stream_record"),
    (wire("event") + b'{"ok":true,"orchestration":{}', "truncated_stream"),
    (wire("event") + wire("orchestration") + b'EXTRA', "trailing_data_after_result"),
    (b"A" * 65537, "line_too_large"),
    (wire("event") * 129, "too_many_events"),
    (wire("event") + wire("orchestration") + wire("event"), "trailing_data_after_result"),
], ids=["empty", "missing_terminal", "result_without_event", "engine_error", "bad_record", "truncated_line", "extra_bytes", "oversized_line", "too_many_events", "event_after_result"])
def test_rejects_unsafe_or_incomplete_stream(data, reason):
    with pytest.raises(EngineNdjsonContractError) as err:
        consume(chunks_of(data))
    assert err.value.code == reason


class FakeTransport:
    def __init__(self, *, status=200, mime="application/x-ndjson", body=None):
        self.calls = []
        self.body = body if body is not None else wire("event") + wire("orchestration", {"done": True})
        self.status = status
        self.mime = mime

    async def request(self, **kwargs):
        raise AssertionError("must not use old buffered request route")

    async def stream_request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineStreamTransportResponse(
            status=self.status, chunks=chunks_of(self.body[:9], self.body[9:]),
            headers={"content-type": self.mime},
        )


def test_engine_client_explicit_selected_stream_reuses_credentials_and_request_shape():
    async def exercise():
        transport = FakeTransport()
        client = PadiemAiEngineClient(
            transport=transport, app_id="padiem-chat", caller_id="padiem-chat",
            credential="x" * 64,
        )
        result = [e async for e in client.stream_orchestration({
            "agent": {"id": "agent:claw:test@1"}, "messages": [{"role": "user", "content": "안녕"}],
            "subject_id": "user:fixture", "trace_id": "trace.fixture",
        })]
        return transport, result
    transport, output = asyncio.run(exercise())
    assert len(output) == 2
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == ENGINE_INTERNAL_ORIGIN + ENGINE_ORCHESTRATE_STREAM_PATH
    assert call["method"] == "POST"
    assert call["headers"]["X-Padiem-Engine-Caller"] == "padiem-chat"
    assert json.loads(call["body"])["subject_id"] == "user:fixture"
    assert json.loads(call["body"])["app_id"] == "padiem-chat"


def test_stream_not_automatically_enabled_or_rerouted():
    class OldTransport:
        async def request(self, **kwargs):
            raise AssertionError("stream unsupported")

    async def exercise():
        client = PadiemAiEngineClient(
            transport=OldTransport(), app_id="claw", caller_id="claw",
            credential="x" * 64,
        )
        return [e async for e in client.stream_orchestration({
            "agent": {}, "messages": [],
        })]
    with pytest.raises(PadiemAiEngineClientError) as err:
        asyncio.run(exercise())
    assert err.value.code == "engine_stream_unavailable"


def test_non_200_and_content_type_refused_without_silent_fallback():
    for status, mime in ((404, "application/json"), (429, "application/json"), (200, "text/plain")):
        async def exercise():
            transport = FakeTransport(status=status, mime=mime)
            client = PadiemAiEngineClient(transport=transport, app_id="claw", caller_id="claw", credential="x"*64)
            return [x async for x in client.stream_orchestration({"agent": {}, "messages": []})]
        with pytest.raises(PadiemAiEngineClientError) as err:
            asyncio.run(exercise())
        assert err.value.status == status


class FakeReader:
    def __init__(self, parts):
        self.parts = list(parts)
        self.cancelled = 0
        self.released = 0

    async def read(self):
        if self.parts:
            return SimpleNamespace(done=False, value=self.parts.pop(0))
        return SimpleNamespace(done=True)

    async def cancel(self):
        self.cancelled += 1

    def releaseLock(self):
        self.released += 1


class FakeRequest:
    def __init__(self, url, *, method, headers, body):
        self.js_object = self
        self.url, self.method, self.headers, self.body = url, method, headers, body


class FakeBinding:
    def __init__(self, reader, *, status=200, mime="application/x-ndjson"):
        self.reader = reader
        self.status = status
        self.mime = mime
        self.calls = []

    async def fetch(self, request):
        self.calls.append(request)
        return SimpleNamespace(
            status=self.status,
            headers={"content-type": self.mime},
            body=SimpleNamespace(getReader=lambda: self.reader),
        )


def test_worker_binding_yields_incremental_chunks_and_cancels_on_close():
    async def exercise():
        reader = FakeReader([b'first', b'second'])
        binding = FakeBinding(reader)
        transport = CloudflareEngineServiceTransport(binding, request_factory=FakeRequest)
        result = await transport.stream_request(
            method="POST", url=ENGINE_INTERNAL_ORIGIN+ENGINE_ORCHESTRATE_STREAM_PATH,
            headers={"Content-Type": "application/json"}, body=b'{"agent":{}}',
        )
        assert len(binding.calls) == 1
        assert reader.parts == [b'first', b'second']  # not buffered
        first = await anext(result.chunks)
        await result.chunks.aclose()
        return first, reader
    first, reader = asyncio.run(exercise())
    assert first == b"first"
    assert reader.cancelled == 1 and reader.released == 1


def test_worker_binding_stream_limit_and_wrong_target_fail_closed():
    async def exercise():
        reader = FakeReader([b"x" * (MAX_NDJSON_TERMINAL_LINE_BYTES + 1), b"must-not-read"])
        binding = FakeBinding(reader)
        transport = CloudflareEngineServiceTransport(binding, request_factory=FakeRequest)
        with pytest.raises(ValueError):
            await transport.stream_request(method="POST", url="https://evil.test/orchestrate/stream", headers={}, body=b"{}")
        assert binding.calls == []
        result = await transport.stream_request(
            method="POST", url=ENGINE_INTERNAL_ORIGIN+ENGINE_ORCHESTRATE_STREAM_PATH,
            headers={}, body=b"{}",
        )
        with pytest.raises(ServiceBindingResponseTooLarge):
            _ = [x async for x in result.chunks]
        return reader
    reader = asyncio.run(exercise())
    assert reader.cancelled == 1 and reader.released == 1



def test_long_healthy_terminal_answer_over_old_one_mib_is_preserved_verbatim():
    # The canonical Engine emits one validated orchestration result line at
    # EOF. It must not be mistaken for a 64KiB EVENT or 1MiB aggregate cap.
    answer = "S" * 1_300_000
    payload = wire("event") + wire("orchestration", {"answer": answer})
    assert len(payload) > 1_048_576
    assert len(payload) < MAX_NDJSON_TERMINAL_LINE_BYTES
    result = consume(chunks_of(payload[:19], payload[19:100_000], payload[100_000:]))
    assert len(result) == 2
    assert result[-1]["orchestration"]["answer"] == answer


def test_many_small_valid_events_can_cross_old_cumulative_stream_cap():
    records = [
        wire("event", {"kind": "run_step", "sequence": i + 1, "detail": "E" * 57_000})
        for i in range(25)
    ]
    assert all(len(part) < MAX_NDJSON_LINE_BYTES for part in records)
    payload = b"".join(records) + wire("orchestration", {"status": "completed"})
    assert len(payload) > 1_048_576
    parsed = consume(chunks_of(*records, wire("orchestration", {"status": "completed"})))
    assert len(parsed) == 26
    assert parsed[-1]["orchestration"]["status"] == "completed"


def test_terminal_record_larger_than_finite_safety_max_fails_closed():
    body = wire("event") + wire("orchestration", {"answer": "X" * MAX_NDJSON_TERMINAL_LINE_BYTES})
    with pytest.raises(EngineNdjsonContractError, match="line_too_large"):
        consume(chunks_of(body))


def test_worker_binding_long_answer_from_one_physical_post_to_ndjson_parser():
    answer = "long-answer-" + "A" * 1_200_000
    payload = wire("event") + wire("orchestration", {"answer": answer})

    async def exercise():
        reader = FakeReader([payload[:17], payload[17:]])
        binding = FakeBinding(reader)
        transport = CloudflareEngineServiceTransport(binding, request_factory=FakeRequest)
        wire_response = await transport.stream_request(
            method="POST", url=ENGINE_INTERNAL_ORIGIN + ENGINE_ORCHESTRATE_STREAM_PATH,
            headers={}, body=b"{}",
        )
        decoded = [e async for e in decode_orchestration_ndjson(wire_response.chunks)]
        return decoded, reader, binding

    decoded, reader, binding = asyncio.run(exercise())
    assert decoded[-1]["orchestration"]["answer"] == answer
    assert len(binding.calls) == 1
    assert reader.cancelled == 0
    assert reader.released == 1
    assert reader.parts == []



def test_engine_stream_model_request_400kb_allowed_but_6mb_plus_refused():
    async def exercise():
        reader = FakeReader([wire("event") + wire("orchestration", {"status": "completed"})])
        binding = FakeBinding(reader)
        transport = CloudflareEngineServiceTransport(binding, request_factory=FakeRequest)
        body = b'{"messages":"' + b"A" * 400_000 + b'"}'
        result = await transport.stream_request(
            method="POST", url=ENGINE_INTERNAL_ORIGIN + ENGINE_ORCHESTRATE_STREAM_PATH,
            headers={}, body=body,
        )
        output = [x async for x in decode_orchestration_ndjson(result.chunks)]
        assert output[-1]["orchestration"]["status"] == "completed"
        assert len(binding.calls) == 1
        with pytest.raises(ValueError):
            await transport.stream_request(
                method="POST", url=ENGINE_INTERNAL_ORIGIN + ENGINE_ORCHESTRATE_STREAM_PATH,
                headers={}, body=b"X" * (6_000_000 + 1),
            )
        assert len(binding.calls) == 1
    asyncio.run(exercise())
