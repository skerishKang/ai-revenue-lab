"""Shipped-source readers for pixel/TTFT/classification contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path


def read(path, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)
