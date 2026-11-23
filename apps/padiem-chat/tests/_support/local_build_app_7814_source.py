"""Golden fixture accessors for the build_app surface table (#8060).

Raw reads live here. Each call returns a fresh parsed object so the test keeps
the same contract and cannot mutate a shared copy.
"""
from __future__ import annotations

import json
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def surface_golden() -> dict:
    return json.loads((_FIXTURES / "local_build_app_7814_surface.json").read_text(encoding="utf-8"))


def bindings_golden() -> dict:
    return json.loads((_FIXTURES / "local_build_app_7814_bindings.json").read_text(encoding="utf-8"))


def state_order_golden() -> dict:
    return json.loads((_FIXTURES / "local_build_app_7814_state_order.json").read_text(encoding="utf-8"))
