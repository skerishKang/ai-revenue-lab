"""Read the projects contract's deployed-worker config (#8060).

``wrangler.toml`` is a deployment manifest, not a static sheet, so its read
lives in a file-specific helper instead of the shared ``claw_static``.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2]


def wrangler_config() -> str:
    return (_APP / "wrangler.toml").read_text(encoding="utf-8")
