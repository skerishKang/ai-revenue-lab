"""The Chat write window: mutations 503 while a cutover needs D1 quiet (#5573).

The D1 cutover (#5115 step ③) needs a bounded window in which no Chat request
writes anything: the freeze boundary has to be observable before the export,
otherwise the parity verdict and the handback plan measure a moving target.

This module is the existing stage-3 window grown by one dimension. Reads keep
working, every mutation gets one honest answer — 503 `maintenance` "잠시 점검
중" — and the late-write GET routes that a classification table later identifies
can be frozen by path without a code change.

Two ways to open the window, both default OFF:

* ``PADIEM_CHAT_WRITE_FREEZE`` — an environment switch. Any value except an
  explicit falsy one (``0/false/no/off``) freezes, so a typo fails on the safe
  side: writes stop instead of silently continuing into a freeze boundary.
* ``PADIEM_CHAT_MAINTENANCE_SENTINEL`` — a sentinel FILE checked per request.
  On the COM2 host this opens and closes the window without a restart; the
  Cloudflare entry has no filesystem, so there only the environment switch
  applies and toggling it costs one deploy.

``PADIEM_CHAT_WRITE_FREEZE_PATHS`` lists read-method routes that still write
(comma or space separated; a trailing ``*`` matches a prefix). It is empty by
default because the list must come from the measured classification table, not
from a guess.

An unreadable sentinel counts as frozen: the safe side is refusing writes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, MutableMapping

from starlette.responses import JSONResponse

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ_METHODS = frozenset({"GET", "HEAD"})
MAINTENANCE_CODE = "maintenance"
MAINTENANCE_MESSAGE = "잠시 점검 중입니다. 곧 다시 이용할 수 있습니다."

#: Only an explicit falsy value leaves the window closed; anything else freezes.
FALSY_VALUES = frozenset({"0", "false", "no", "off"})

SWITCH_ENV = "PADIEM_CHAT_WRITE_FREEZE"
SENTINEL_ENV = "PADIEM_CHAT_MAINTENANCE_SENTINEL"
FROZEN_PATHS_ENV = "PADIEM_CHAT_WRITE_FREEZE_PATHS"

__all__ = [
    "FROZEN_PATHS_ENV",
    "MAINTENANCE_CODE",
    "MAINTENANCE_MESSAGE",
    "MUTATING_METHODS",
    "READ_METHODS",
    "SENTINEL_ENV",
    "SWITCH_ENV",
    "MaintenanceModeMiddleware",
    "WriteFreezeConfig",
    "apply_write_freeze",
    "frozen_paths_from_env",
    "write_freeze_from_env",
]


def frozen_paths_from_env(value: str | None) -> tuple[str, ...]:
    """Parse the extra read-method routes that must be frozen too."""

    parts = [
        part.strip()
        for part in str(value or "").replace(",", " ").split()
        if part.strip()
    ]
    # A bare "*" would freeze every read; refuse it rather than take the site down.
    cleaned: list[str] = []
    for part in parts:
        if part == "*":
            continue
        cleaned.append(part if part.startswith("/") else "/" + part)
    return tuple(dict.fromkeys(cleaned))


@dataclass(frozen=True, slots=True)
class WriteFreezeConfig:
    """Resolved switch state. ``None`` from the resolver means "no window"."""

    enabled: bool = False
    sentinel_path: str | None = None
    frozen_paths: tuple[str, ...] = ()


def write_freeze_from_env(env: Mapping[str, str] | None = None) -> WriteFreezeConfig | None:
    """Resolve the window from the environment; ``None`` keeps today's behavior."""

    source = os.environ if env is None else env
    raw = str(source.get(SWITCH_ENV, "") or "").strip().lower()
    sentinel = str(source.get(SENTINEL_ENV, "") or "").strip()
    frozen = frozen_paths_from_env(source.get(FROZEN_PATHS_ENV))

    enabled = bool(raw) and raw not in FALSY_VALUES
    if not enabled and not sentinel:
        return None
    return WriteFreezeConfig(
        enabled=enabled,
        sentinel_path=sentinel or None,
        frozen_paths=frozen,
    )


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern.endswith("*"):
            if path.startswith(pattern[:-1]):
                return True
        elif path == pattern:
            return True
    return False


class MaintenanceModeMiddleware:
    """Raw ASGI middleware: mutations (and listed read routes) answer 503."""

    def __init__(
        self,
        app: Any,
        *,
        sentinel_path: str | Path | None = None,
        enabled: bool = False,
        frozen_paths: tuple[str, ...] | list[str] = (),
    ):
        if not sentinel_path and not enabled:
            raise ValueError("a maintenance sentinel path or an explicit switch is required")
        self._app = app
        self._sentinel = Path(sentinel_path) if sentinel_path else None
        self._enabled = bool(enabled)
        self._frozen_paths = tuple(frozen_paths)

    def _active(self) -> bool:
        if self._enabled:
            return True
        if self._sentinel is None:
            return False
        try:
            return self._sentinel.is_file()
        except OSError:
            # An unreadable sentinel is treated as maintenance: refuse writes.
            return True

    def _frozen(self, method: str, path: str) -> bool:
        if method in MUTATING_METHODS:
            return True
        return method in READ_METHODS and _matches(path, self._frozen_paths)

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or not self._active():
            await self._app(scope, receive, send)
            return
        method = str(scope.get("method") or "").upper()
        if not self._frozen(method, str(scope.get("path") or "")):
            await self._app(scope, receive, send)
            return
        response = JSONResponse(
            {"error": {"code": MAINTENANCE_CODE, "message": MAINTENANCE_MESSAGE}},
            status_code=503,
            headers={"cache-control": "no-store", "retry-after": "120"},
        )
        await response(scope, receive, send)


def apply_write_freeze(
    app: Any,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Wrap ``app`` when the window is configured; otherwise return it unchanged."""

    config = write_freeze_from_env(env)
    if config is None:
        return app
    return MaintenanceModeMiddleware(
        app,
        sentinel_path=config.sentinel_path,
        enabled=config.enabled,
        frozen_paths=config.frozen_paths,
    )
