from __future__ import annotations

"""#4317: the chat SSE close path must close the B14 stream it owns.

The dispatch-aware client is the client the Chat Worker installs. It wraps the
base client's stream, so it is the outermost generator the SSE route closes.
Delegating with a plain ``async for ... yield`` abandoned the base stream: the
route's close reached the wrapper only, and the whole B14 chain stayed open
until the event loop's asynchronous-generator finalizer closed it in a detached
task. That finalizer-time close is where the Worker reports
``RuntimeError: async generator ignored GeneratorExit``, on successful 200
responses as well.
"""

import asyncio
import gc
import json
import sys

import httpx
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.b14_client import ChatRuntimeError
from app.config import Settings
from app.dispatch_quota import (
    DispatchAwareB14Client,
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.main import api_chat_stream, create_app
from app.model_policy import DEFAULT_B14_MODEL_ID
from app.usage_gate import UsageDecision


MESSAGES = [{"role": "user", "content": "안녕하세요"}]


class RecordingDownstream(httpx.AsyncByteStream):
    """A B14 SSE body that records when the stream is really released."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.closed = False
        self.close_calls = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed = True


def _frame(content: str) -> bytes:
    payload = {
        "id": "b62_4317_close",
        "object": "chat.completion.chunk",
        "model": DEFAULT_B14_MODEL_ID,
        "choices": [
            {"index": 0, "delta": {"content": content}, "finish_reason": None}
        ],
        "business14": {
            "request_id": "b14_4317_close",
            "route_mode": "manual",
            "selected_provider": "Repro Provider",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "fallback_used": False,
        },
    }
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


def _error_frame(code: str) -> bytes:
    payload = {
        "error": {
            "code": code,
            "message": "bounded B14 stream error",
            "request_id": "b14_4317_close",
        }
    }
    return b"event: error\ndata: " + json.dumps(payload).encode("utf-8") + b"\n\n"


def _settings() -> Settings:
    return Settings(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        live_enabled=False,
    )


def _client(downstream: RecordingDownstream, *, seen: list[dict] | None = None):
    async def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=downstream,
        )

    return DispatchAwareB14Client(
        _settings(), stream_transport=httpx.MockTransport(handler)
    )


def _run(scenario) -> list[str]:
    """Run one scenario and report anything its teardown logged.

    ``asyncio.run`` shuts asynchronous generators down at the end, and the
    finalizer path is exactly where the Worker reported the ignored
    GeneratorExit. A clean teardown is part of the contract, not a side note.
    """

    problems: list[str] = []

    def hook(args) -> None:
        problems.append(f"{args.exc_type.__name__}: {args.exc_value}")

    previous = sys.unraisablehook
    sys.unraisablehook = hook

    async def main() -> None:
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: problems.append(
                f"{context.get('message')} | {context.get('exception')!r}"
            )
        )
        await scenario()
        # Turn the loop the way a leaked stream would need to be finalized.
        gc.collect()
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)

    try:
        asyncio.run(main())
    finally:
        sys.unraisablehook = previous
    return problems


def test_normal_stream_keeps_delta_order_and_one_done_and_closes_transport():
    downstream = RecordingDownstream(
        [_frame("첫"), _frame("둘"), b"data: [DONE]\n\n"]
    )

    async def scenario() -> None:
        stream = _client(downstream).stream_text_auto(MESSAGES)
        events = [event async for event in stream]
        assert [event.delta_content for event in events] == ["첫", "둘", None]
        assert [event.done for event in events] == [False, False, True]
        assert downstream.closed is True

    assert _run(scenario) == []


def test_consumer_close_closes_the_b14_transport_in_the_close_call():
    """The load-bearing regression: closing the SSE stream closes B14 now."""

    downstream = RecordingDownstream(
        [_frame("첫"), _frame("둘"), b"data: [DONE]\n\n"]
    )

    async def scenario() -> None:
        stream = _client(downstream).stream_text_auto(MESSAGES)
        first = await anext(stream)
        assert first.delta_content == "첫"
        assert downstream.closed is False

        await stream.aclose()

        # No loop turn, no garbage collection: the close itself must release the
        # model stream instead of deferring it to an async-generator finalizer.
        assert downstream.closed is True
        assert downstream.close_calls == 1

    assert _run(scenario) == []


def test_cancelled_consumer_closes_the_b14_transport_without_swallowing_cancel():
    downstream = RecordingDownstream([_frame("첫"), _frame("둘")])
    state: dict[str, object] = {}

    async def scenario() -> None:
        stream = _client(downstream).stream_text_auto(MESSAGES)
        visible = asyncio.Event()

        async def consume() -> None:
            try:
                async for event in stream:
                    if event.delta_content:
                        visible.set()
                        await asyncio.sleep(10)
            finally:
                # #4317 route contract: chat_routes._close_stream(stream).
                await stream.aclose()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(visible.wait(), timeout=1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            state["cancelled"] = True

        assert state.get("cancelled") is True
        assert downstream.closed is True

    assert _run(scenario) == []


def test_supplier_error_mid_stream_propagates_and_closes_the_transport():
    downstream = RecordingDownstream([_frame("부분"), _error_frame("upstream_rate_limited")])

    async def scenario() -> None:
        received = []
        with_cancel = None
        try:
            async for event in _client(downstream).stream_text_auto(MESSAGES):
                received.append(event)
        except ChatRuntimeError as exc:
            with_cancel = exc
        assert [event.delta_content for event in received] == ["부분"]
        assert with_cancel is not None
        assert with_cancel.status_code == 503
        assert with_cancel.code == "upstream_busy"
        assert downstream.closed is True

    assert _run(scenario) == []


def test_stream_request_keeps_the_tier_fallback_contract():
    downstream = RecordingDownstream([_frame("첫"), b"data: [DONE]\n\n"])
    seen: list[dict] = []

    async def scenario() -> None:
        [_ async for _ in _client(downstream, seen=seen).stream_text_auto(MESSAGES)]

    assert _run(scenario) == []
    business = seen[0]["business14"]
    # #5422 remains the upstream policy: the owner-pinned tier grade fallback is
    # enabled and no local attempt pin was reintroduced.
    assert business["allow_external_fallback"] is False
    assert business["product_tier"] == "free"
    assert "max_attempts" not in business
    assert "max_retries" not in business


class _ReservationStore:
    def __init__(self) -> None:
        self.consume_calls = 0
        self.refunds: list[dict] = []

    async def consume(self, **kwargs) -> UsageDecision:
        self.consume_calls += 1
        return UsageDecision(allowed=True)

    async def _refund(self, **kwargs) -> None:
        self.refunds.append(kwargs)


def test_close_does_not_double_count_usage_or_refund_an_open_reservation():
    downstream = RecordingDownstream([_frame("첫"), _frame("둘")])
    store = _ReservationStore()
    counter = DispatchAwareUsageCounterStore(store)

    async def scenario() -> None:
        await counter.consume(
            subject_type="user",
            subject_key="user-4317",
            minute_bucket="2026-10-24T03:00",
            day_bucket="2026-10-24",
            burst_limit=8,
            daily_limit=100,
            global_daily_limit=1000,
            updated_at="2026-10-24T03:00:00Z",
        )
        stream = _client(downstream).stream_text_auto(MESSAGES)
        assert (await anext(stream)).delta_content == "첫"
        await stream.aclose()

        # One authorization, one dispatch: closing the stream neither re-consumes
        # quota nor refunds a request whose dispatch already became possible.
        assert store.consume_calls == 1
        assert store.refunds == []
        assert await _refund_active_reservation() is False
        assert downstream.closed is True

    assert _run(scenario) == []


def test_next_request_after_a_mid_stream_close_completes_normally():
    first = RecordingDownstream([_frame("첫"), _frame("둘")])
    second = RecordingDownstream([_frame("새 답변"), b"data: [DONE]\n\n"])

    async def scenario() -> None:
        stream = _client(first).stream_text_auto(MESSAGES)
        assert (await anext(stream)).delta_content == "첫"
        await stream.aclose()
        assert first.closed is True

        events = [event async for event in _client(second).stream_text_auto(MESSAGES)]
        assert [event.delta_content for event in events] == ["새 답변", None]
        assert events[-1].done is True
        assert second.closed is True
        assert first.close_calls == 1

    assert _run(scenario) == []


def _scope(body: bytes, app) -> dict:
    return {
        "app": app,
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat/stream",
        "raw_path": b"/api/chat/stream",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }


def test_route_sse_close_closes_the_b14_transport():
    """The production path: api_chat_stream -> _close_stream(stream)."""

    downstream = RecordingDownstream([_frame("첫"), _frame("둘")])
    body = json.dumps(
        {"messages": [{"role": "user", "content": "안녕"}], "mode": "auto"},
        ensure_ascii=False,
    ).encode("utf-8")

    async def scenario() -> None:
        app = create_app(_settings())
        app.state.b14_client = _client(downstream)
        app.state.usage_gate_enforced = False

        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        response = await api_chat_stream(Request(_scope(body, app), receive))
        assert isinstance(response, StreamingResponse)

        iterator = response.body_iterator
        first_chunk = await anext(iterator)
        assert b"event: delta" in first_chunk
        assert "첫".encode("utf-8") in first_chunk
        assert downstream.closed is False

        await iterator.aclose()
        assert downstream.closed is True

    assert _run(scenario) == []
