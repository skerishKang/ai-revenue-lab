"""Source accessor for the recent-menu browser contract (#8060).

The raw locale read lives here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

import locale_bundle


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")
