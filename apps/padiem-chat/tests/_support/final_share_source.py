"""Shipped-source readers for the final raw-assertion cleanup (#8060).

Raw reads live here. Tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle


def read(path, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


# Alias for tests that define their own `read` helper and import this one under
# a different name.
shared_read = read
