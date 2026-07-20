"""Utility helpers shared across repositories and services."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_utc_iso() -> str:
    """Return current UTC time as ISO-8601 with milliseconds and Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_id() -> str:
    return str(uuid.uuid4())
