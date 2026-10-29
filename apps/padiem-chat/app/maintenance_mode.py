"""Maintenance mode for the COM2 Chat host (#5573 stage 3).

During the final data sync the host keeps answering reads while every mutation
gets one honest answer: 503 `maintenance` — "잠시 점검 중". The switch is a
sentinel FILE checked per request, so the window can be opened and closed
without a restart, and an accidentally left-behind file fails on the safe side
(writes refused, reads fine).

Only `build_app` in app.local_cpython composes this; the Cloudflare path never
imports it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, MutableMapping

from starlette.responses import JSONResponse

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAINTENANCE_CODE = "maintenance"
MAINTENANCE_MESSAGE = "잠시 점검 중입니다. 곧 다시 이용할 수 있습니다."

__all__ = [
    "MAINTENANCE_CODE",
    "MAINTENANCE_MESSAGE",
    "MUTATING_METHODS",
    "MaintenanceModeMiddleware",
]


class MaintenanceModeMiddleware:
    """Raw ASGI middleware: mutations 503 while the sentinel file exists."""

    def __init__(self, app: Any, *, sentinel_path: str | Path):
        if not sentinel_path:
            raise ValueError("a maintenance sentinel path is required")
        self._app = app
        self._sentinel = Path(sentinel_path)

    def _active(self) -> bool:
        try:
            return self._sentinel.is_file()
        except OSError:
            # An unreadable sentinel is treated as maintenance: refuse writes.
            return True

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or not self._active():
            await self._app(scope, receive, send)
            return
        if str(scope.get("method") or "").upper() not in MUTATING_METHODS:
            await self._app(scope, receive, send)
            return
        response = JSONResponse(
            {"error": {"code": MAINTENANCE_CODE, "message": MAINTENANCE_MESSAGE}},
            status_code=503,
            headers={"cache-control": "no-store", "retry-after": "120"},
        )
        await response(scope, receive, send)
