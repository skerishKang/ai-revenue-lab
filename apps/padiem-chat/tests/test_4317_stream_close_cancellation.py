"""#4317: the route's stream close must survive a concurrent cancellation.

The SSE route closes the client generator chain on every exit path, including
the client-disconnect path where the response task is being cancelled at the
same moment. A plain ``await closer()`` inherits that cancellation, abandons
the multi-layer unwind halfway, and leaves the rest to asyncgen finalization —
which on the Workers runtime is what logged ``RuntimeError: async generator
ignored GeneratorExit`` around ``dispatch_quota.py`` even for healthy 200
answers. The close is shielded now, so this test pins the deterministic
contract: cancellation may interrupt the caller, never the unwind itself.
"""
from __future__ import annotations

import asyncio

import pytest

from app import chat_routes


def test_close_stream_completes_the_unwind_under_mid_close_cancellation():
    closed: list[bool] = []

    async def inner():
        try:
            yield "delta"
            yield "done"
        finally:
            # The real chain closes through several awaits (httpx, wrappers):
            # give the close real suspension time so a cancellation can land
            # inside it.
            await asyncio.sleep(0.08)
            closed.append(True)

    async def wrapper():
        stream = inner()
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def scenario() -> None:
        stream = wrapper()
        assert await stream.__anext__() == "delta"
        close_task = asyncio.create_task(chat_routes._close_stream(stream))
        # Let the close reach the inner sleep, then cancel it the way a client
        # disconnect cancels the whole response task mid-unwind.
        await asyncio.sleep(0.02)
        close_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        # The shielded close still finishes unwinding the chain.
        for _ in range(10):
            await asyncio.sleep(0.02)
        assert closed == [True], "the generator chain must be fully closed"
        await stream.aclose()

    asyncio.run(scenario())


def test_close_stream_without_cancellation_stays_a_clean_noop_on_errors():
    closed: list[bool] = []

    async def inner():
        try:
            yield "delta"
        finally:
            closed.append(True)
            raise RuntimeError("cleanup noise must not replace the route result")

    async def scenario() -> None:
        stream = inner()
        assert await stream.__anext__() == "delta"
        await chat_routes._close_stream(stream)
        assert closed == [True]

    asyncio.run(scenario())
