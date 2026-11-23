"""#8529: the Chat app's startup and shutdown handlers, run by its ASGI lifespan.

Starlette 1.0 removed ``Router.on_startup`` / ``Router.on_shutdown`` together
with the default lifespan that ran them. ``LifespanHooks`` keeps the same two
ordered lists and is itself the lifespan handed to ``Starlette(lifespan=...)``,
so the registering modules still only append to a list. The contract is the one
the removed default lifespan had:

* startup handlers run in list order before the app serves a request; when one
  raises, the later ones are skipped and no shutdown handler runs;
* shutdown handlers run in list order once serving has ended, also when it
  ended with an error; when one raises, the later ones are skipped;
* a handler takes no arguments and may be a plain or an async callable.

The object holds no per-run state, so one app can be started and stopped more
than once (each ``TestClient`` context does exactly that).
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

__all__ = ["LifespanHooks", "lifespan_hooks"]

Handler = Callable[[], Any]


async def _run(handlers: list[Handler]) -> None:
    for handler in handlers:
        result = handler()
        if inspect.isawaitable(result):
            await result


class LifespanHooks:
    """Ordered startup/shutdown handlers; also the app's lifespan context."""

    def __init__(self) -> None:
        self.on_startup: list[Handler] = []
        self.on_shutdown: list[Handler] = []

    async def startup(self) -> None:
        await _run(self.on_startup)

    async def shutdown(self) -> None:
        await _run(self.on_shutdown)

    # Starlette calls ``lifespan(app)`` and enters the returned async context
    # manager around the serving phase.
    def __call__(self, app: Any) -> "LifespanHooks":
        return self

    async def __aenter__(self) -> None:
        await self.startup()

    async def __aexit__(self, *exc_info: object) -> None:
        await self.shutdown()


def lifespan_hooks(app: Any) -> LifespanHooks:
    """Return the hooks that ``app``'s lifespan runs.

    The lists must be the very object Starlette enters, so they are read back
    from the app rather than kept in a second place that could drift from it.
    """

    hooks = app.router.lifespan_context
    if not isinstance(hooks, LifespanHooks):
        raise RuntimeError("the app was not created with LifespanHooks as its lifespan")
    return hooks
