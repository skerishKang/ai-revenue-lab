"""Request-scoped ledger write factories, run only after answer construction."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass, field
import logging
from typing import Any

WRITE_TIMEOUT_SECONDS = 5.0
logger = logging.getLogger(__name__)
Factory = Callable[[], Awaitable[Any]]
Item = tuple[str, Context, Factory]


@dataclass
class _Queue:
    items: list[Item] = field(default_factory=list)
    drained: bool = False
    ctx: Any = None


_CURRENT: ContextVar[_Queue | None] = ContextVar("b14_deferred_writes", default=None)


def bind():
    return _CURRENT.set(_Queue())


def reset(token) -> None:
    _CURRENT.reset(token)


def skipped(request_id: str, exc: Exception) -> None:
    # Exception messages can contain provider payloads or bound values.
    logger.warning("b14_ledger_skipped request_id=%s reason=%s",
                   request_id, type(exc).__name__)


def enqueue(factory: Factory, *, request_id: str) -> None:
    """Do not construct a coroutine or start I/O on the answer path."""
    queue = _CURRENT.get()
    if queue is None:
        queue = _Queue()
        _CURRENT.set(queue)
    item = (request_id, copy_context(), factory)
    if queue.drained and queue.ctx is not None:
        # An ASGI stream may finish after the Worker returned its headers.
        _schedule([item], queue.ctx)
    else:
        queue.items.append(item)


async def _execute(request_id: str, factory: Factory) -> None:
    try:
        await factory()
    except Exception as exc:
        skipped(request_id, exc)


async def _bounded(items: list[Item]) -> None:
    try:
        # D1's request-scoped binding must survive the Worker's env reset.
        tasks = [
            asyncio.create_task(_execute(request_id, factory), context=context)
            for request_id, context, factory in items
        ]
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=WRITE_TIMEOUT_SECONDS)
    except Exception as exc:
        for request_id, _context, _factory in items:
            skipped(request_id, exc)


def _schedule(items: list[Item], ctx) -> None:
    pending = _bounded(items)
    try:
        from pyodide.ffi import create_proxy

        ctx.waitUntil(create_proxy(pending))
    except Exception as exc:
        pending.close()
        for request_id, _context, _factory in items:
            skipped(request_id, exc)


async def drain(ctx=None) -> None:
    """Worker: waitUntil; local/test: inline after constructing/sending the answer."""
    queue = _CURRENT.get()
    if queue is None:
        return
    queue.drained, queue.ctx = True, ctx
    items, queue.items = queue.items, []
    if not items:
        return
    if ctx is not None:
        _schedule(items, ctx)
    else:
        await _bounded(items)


class DeferredWritesMiddleware:
    """Local ASGI fallback; a Worker-owned queue is drained by worker.fetch."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or _CURRENT.get() is not None:
            return await self.app(scope, receive, send)
        token = bind()
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                await drain()
            finally:
                reset(token)
