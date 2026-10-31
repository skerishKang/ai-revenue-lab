"""Padiem Chat ASGI entrypoint.

Server responsibilities live in focused modules. This module keeps only the
module-level ASGI app and the two names other code imports from it
(``create_app`` for the Worker entrypoint, ``api_chat_stream`` for tests).
"""

from __future__ import annotations

from .app_factory import create_app
from .chat_routes import api_chat_stream
from .config import ConfigError


try:
    app = create_app()
except ConfigError as exc:
    raise RuntimeError(f"Padiem Chat configuration error: {exc}") from exc


__all__ = ["app", "create_app", "api_chat_stream"]
