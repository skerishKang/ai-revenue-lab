"""B14 generic live streamed-body regressions, synthetic transport only (#4379)."""
import pytest
import json
import sys
from pathlib import Path

# Reuse the canonical synthetic chunk transport without copying test scaffolding.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.pilot import platform as plat
from app.pilot.errors import UpstreamResponseTooLarge, UpstreamAuthFailed
from test_b14_completed_response_bounds import (
    live_keyless_route, ChunkCountingTransport, _completed_doc,
    MOCK_ID, MOCK_UPSTREAM, MOCK_PROVIDER, CAP, CHUNK,
)


def _call(transport):
    return plat.call_platform_chat_completions(
        model_id=MOCK_ID, upstream_model=MOCK_UPSTREAM,
        provider="Synthetic test-only gateway",
        platform_provider_id=MOCK_PROVIDER,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=32, transport=transport,
    )


@pytest.mark.asyncio
async def test_real_chunked_completed_success_records_collected_bytes(live_keyless_route):
    answer = "A" * 4096
    payload = json.dumps(_completed_doc(answer)).encode()
    stream = ChunkCountingTransport(payload)
    actual = await _call(stream)
    assert stream.calls == 1
    assert stream.served_bytes == len(payload)
    assert actual["choices"][0]["message"]["content"] == answer
    assert actual["_response_bytes"] == len(payload)


@pytest.mark.asyncio
async def test_streamed_oversized_upstream_error_is_bounded(live_keyless_route):
    # A status=500 SSE response MUST NOT call unbounded response.aread().
    payload = b"ERROR " + b"E" * (CAP + CHUNK * 3)
    stream = ChunkCountingTransport(payload, status=500)
    with pytest.raises(UpstreamResponseTooLarge):
        await list_events(stream)
    assert stream.calls == 1
    assert stream.served_bytes <= CAP + CHUNK


async def list_events(stream):
    return [evt async for evt in plat.stream_platform_chat_completions(
        model_id=MOCK_ID, upstream_model=MOCK_UPSTREAM,
        provider="Synthetic test-only gateway",
        platform_provider_id=MOCK_PROVIDER,
        messages=[{"role": "user", "content": "hi"}],
        transport=stream,
    )]


@pytest.mark.asyncio
async def test_streamed_small_auth_error_keeps_classification(live_keyless_route):
    stream = ChunkCountingTransport(b'{"error":"test"}', status=401)
    with pytest.raises(UpstreamAuthFailed):
        await list_events(stream)
    assert stream.calls == 1
