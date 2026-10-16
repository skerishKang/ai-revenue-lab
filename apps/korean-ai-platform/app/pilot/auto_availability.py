"""Explicit deferral of the future B14 generic autorouter.

The owner-selected Cat Jam default and per-tier fallbacks do not use b14/auto.
Historical routing implementation is preserved for future opt-in development.
"""

from __future__ import annotations

import os

from .errors import PilotError


def ensure_generic_auto_enabled(model_id: str) -> None:
    """Reject legacy b14/auto before route, secret lookup or provider dispatch."""
    if model_id != "b14/auto":
        return
    if os.environ.get("B14_ENABLE_FUTURE_AUTO", "").strip() == "1":
        return
    raise PilotError(
        code="auto_routing_deferred",
        message="b14/auto is reserved for future development; select an explicit registered model.",
        status_code=422,
    )
